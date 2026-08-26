from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from app.database import connect, initialize
from app.edition_matching import editions_match, find_edition_candidates
from app.work_matching import find_work_candidates
from app.merge_service import MergeConflict, merge_editions, merge_volumes, merge_works
from app.metadata_resolver import resolve_metadata
from app.repository import create_book, get_work, list_works
from app.schemas import (
    BookInput, BookRecord, CopyInput, EditionInput, VolumeInput,
    WorkDetail, WorkInput,
)


def book(title: str, volume_number: str, volume_version: str) -> BookInput:
    return BookInput(
        work=WorkInput(title=title, authors="Author", scripts="Greek"),
        edition=EditionInput(
            title="Collected edition",
            edition_scripts="Chinese",
            translator="Alice (translator)",
            publisher="Press",
            identifier="ISBN SET",
        ),
        volume=VolumeInput(
            volume_number=volume_number,
            version=volume_version,
            responsibility="Bob (editor)",
        ),
        copy=CopyInput(location=f"Shelf {volume_number}"),
    )


class ResolverTests(unittest.TestCase):
    def test_override_append_and_sources(self) -> None:
        resolved = resolve_metadata(
            {
                "title": "Work title",
                "subtitle": "Work subtitle",
                "authors": "Author",
                "scripts": "Greek",
            },
            {
                "title": "Edition title",
                "subtitle": "",
                "identifier": "ISBN SET",
                "version": "First edition",
                "publication_year": 2001,
                "publication_year_end": None,
                "edition_scripts": "Chinese",
                "translator": "Alice (translator)",
            },
            {
                "volume_title": "",
                "identifier": "ISBN V2",
                "version": "Second edition",
                "publication_year": 2003,
                "publication_year_end": None,
                "responsibility": "Bob (editor)",
                "scripts": "Latin",
            },
        )
        self.assertEqual(resolved["title"], {"value": "Edition title", "source": "edition"})
        self.assertEqual(resolved["subtitle"], {"value": "Work subtitle", "source": "work"})
        self.assertEqual(resolved["scripts"], {"value": "Latin", "source": "volume"})
        self.assertEqual(resolved["identifier"], {"value": "ISBN V2", "source": "volume"})
        self.assertEqual(resolved["version"], {"value": "Second edition", "source": "volume"})
        self.assertEqual(resolved["publication_year"], {"value": 2003, "source": "volume"})
        self.assertEqual(
            resolved["responsibility"]["value"],
            "Author; Alice (translator); Bob (editor)",
        )
        self.assertEqual(
            [part["source"] for part in resolved["responsibility"]["sources"]],
            ["work", "edition", "volume"],
        )

    def test_scripts_fall_back_to_work(self) -> None:
        resolved = resolve_metadata(
            {"scripts": "Tibetan"}, {"edition_scripts": ""}, {}
        )
        self.assertEqual(resolved["scripts"], {"value": "Tibetan", "source": "work"})


class MatchingTests(unittest.TestCase):
    def test_matching_is_pure_and_ignores_volume_level_differences(self) -> None:
        candidate = {
            "id": 1, "title": "Edition", "subtitle": "",
            "edition_scripts": "Chinese", "translator": "Translator",
            "version": "", "series": "", "publisher_id": 7,
            "identifier": "ISBN A", "publication_year": 2001,
            "force_separate": 0,
        }
        incoming = {
            **candidate, "id": 2, "identifier": "ISBN B",
            "publication_year": 2003,
        }
        before_candidate = copy.deepcopy(candidate)
        before_incoming = copy.deepcopy(incoming)
        self.assertTrue(editions_match(candidate, incoming))
        self.assertEqual(find_edition_candidates([candidate], incoming), [candidate])
        self.assertEqual(candidate, before_candidate)
        self.assertEqual(incoming, before_incoming)

    def test_work_candidate_detection_is_pure_and_exact(self) -> None:
        candidates = [
            {"id": 1, "title": " Work ", "authors": "Author"},
            {"id": 2, "title": "Work", "authors": "Different"},
        ]
        before = copy.deepcopy(candidates)
        matches = find_work_candidates(
            candidates, {"title": "work", "authors": " author "}
        )
        self.assertEqual([item["id"] for item in matches], [1])
        self.assertEqual(candidates, before)


class RepositorySemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "library.db"
        initialize(self.path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_volume_versions_share_edition_and_effective_values_are_resolved(self) -> None:
        create_book(book("Tragedies", "1", "Second edition"), self.path)
        create_book(book("Tragedies", "2", "Third edition"), self.path)
        detail = get_work(list_works(path=self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 1)
        volumes = [group["volume"] for group in detail["editions"][0]["volumes"]]
        self.assertEqual([item["version"] for item in volumes], ["Second edition", "Third edition"])
        self.assertEqual(
            [item["effective_metadata"]["version"]["source"] for item in volumes],
            ["volume", "volume"],
        )
        self.assertTrue(all(
            item["effective_metadata"]["identifier"]["value"] == "ISBN SET"
            and item["effective_metadata"]["identifier"]["source"] == "edition"
            for item in volumes
        ))
        self.assertTrue(all(
            item["effective_metadata"]["responsibility"]["value"]
            == "Author; Alice (translator); Bob (editor)"
            for item in volumes
        ))

    def test_four_layer_records_validate_against_api_schemas(self) -> None:
        created = create_book(book("API schema", "1", "Second edition"), self.path)
        BookRecord.model_validate(created)
        detail = get_work(list_works(path=self.path)[0]["id"], self.path)
        WorkDetail.model_validate(detail)

    def test_initialize_does_not_merge_duplicate_editions(self) -> None:
        create_book(book("Keep editions", "1", ""), self.path)
        duplicate = book("Keep editions", "2", "")
        duplicate.edition.force_new_edition = True
        create_book(duplicate, self.path)
        initialize(self.path)
        connection = connect(self.path)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM editions").fetchone()[0], 2
            )
        finally:
            connection.close()


class MergeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "library.db"
        initialize(self.path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_work_conflict_rolls_back_without_overwrite(self) -> None:
        connection = connect(self.path)
        try:
            first = connection.execute(
                "INSERT INTO works (title, authors) VALUES ('A', 'Author')"
            ).lastrowid
            second = connection.execute(
                "INSERT INTO works (title, authors) VALUES ('B', 'Author')"
            ).lastrowid
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(MergeConflict) as raised:
            merge_works(first, second, self.path)
        self.assertEqual(raised.exception.conflicts[0]["field"], "title")
        connection = connect(self.path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM works").fetchone()[0], 2)
        finally:
            connection.close()

    def test_edition_merge_conflict_does_not_move_volumes(self) -> None:
        first = create_book(book("Edition conflict A", "1", ""), self.path)
        second_book = book("Edition conflict B", "1", "")
        second_book.edition.identifier = "ISBN OTHER"
        second = create_book(second_book, self.path)
        with self.assertRaises(MergeConflict):
            merge_editions(first["edition_id"], second["edition_id"], self.path)
        connection = connect(self.path)
        try:
            edition_ids = {
                row[0] for row in connection.execute(
                    "SELECT edition_id FROM volumes"
                ).fetchall()
            }
            self.assertEqual(edition_ids, {first["edition_id"], second["edition_id"]})
        finally:
            connection.close()

    def test_volume_merge_preserves_copies_when_metadata_has_no_conflict(self) -> None:
        created = create_book(book("Merge volumes", "", "Second edition"), self.path)
        second_created = create_book(
            book("Merge volumes", "1", "Second edition"), self.path
        )
        merge_volumes(created["volume_id"], second_created["volume_id"], self.path)
        connection = connect(self.path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM volumes").fetchone()[0], 1)
            rows = connection.execute("SELECT DISTINCT volume_id FROM copies").fetchall()
            self.assertEqual([row[0] for row in rows], [created["volume_id"]])
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
