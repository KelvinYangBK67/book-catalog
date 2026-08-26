from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.database import connect, initialize
from app.repository import (
    create_book, create_copy_for_volume, create_work_record, get_work, list_works,
)
from app.schemas import BookInput, CopyInput, EditionInput, VolumeInput, WorkInput


def book_payload(
    title: str,
    *,
    edition_identifier: str = "",
    volume_number: str = "",
    volume_identifier: str = "",
    volume_version: str = "",
    volume_year: int | None = None,
    volume_responsibility: str = "",
    location: str = "",
) -> BookInput:
    return BookInput(
        work=WorkInput(title=title, authors="Author", scripts="漢文"),
        edition=EditionInput(
            identifier=edition_identifier,
            translator="Translator",
            publisher="Release Press",
        ),
        volume=VolumeInput(
            volume_number=volume_number,
            identifier=volume_identifier,
            version=volume_version,
            publication_year=volume_year,
            responsibility=volume_responsibility,
        ),
        copy=CopyInput(location=location),
    )


class ReleaseCandidateAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.db"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_runtime_schema_has_only_four_layer_ownership(self) -> None:
        initialize(self.path)
        connection = connect(self.path)
        try:
            self.assertEqual(
                [row["name"] for row in connection.execute("PRAGMA table_info(copies)")],
                ["id", "volume_id", "acquisition_date", "location", "reading_record"],
            )
            edition_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(editions)")
            }
            self.assertNotIn("work_id", edition_columns)
            self.assertNotIn("translation_script", edition_columns)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

    def test_write_schemas_reject_removed_copy_and_relation_fields(self) -> None:
        with self.assertRaises(ValidationError):
            CopyInput.model_validate({"location": "A", "identifier": "ISBN legacy"})
        with self.assertRaises(ValidationError):
            BookInput.model_validate({
                "work": {"title": "Legacy request"},
                "edition": {},
                "copy": {"location": "A", "volume_number": "1"},
            })
        with self.assertRaises(ValidationError):
            EditionInput.model_validate({
                "work_relations": [{
                    "work_id": 1,
                    "relation_type": "volume",
                    "volume_number": "1",
                }]
            })

    def test_cross_edition_volume_relations_and_moves_are_rejected(self) -> None:
        initialize(self.path)
        first = create_book(book_payload("One", volume_number="1"), self.path)
        second = create_book(book_payload("Two", volume_number="1"), self.path)
        connection = connect(self.path)
        try:
            work_two = list_works("Two", self.path)[0]["id"]
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO edition_works
                           (edition_id, work_id, position, relation_type, volume_id)
                       VALUES (?, ?, 1, 'volume', ?)""",
                    (first["edition_id"], work_two, second["volume_id"]),
                )
            connection.execute(
                """UPDATE edition_works
                   SET relation_type = 'volume', volume_id = ?
                   WHERE edition_id = ?""",
                (first["volume_id"], first["edition_id"]),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE volumes SET edition_id = ? WHERE id = ?",
                    (second["edition_id"], first["volume_id"]),
                )
        finally:
            connection.close()

    def test_database_guards_reversed_year_ranges(self) -> None:
        initialize(self.path)
        connection = connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO editions
                           (publication_year, publication_year_end)
                       VALUES (2024, 2023)"""
                )
            work = connection.execute(
                "INSERT INTO works (title) VALUES ('Year Work')"
            ).lastrowid
            edition = connection.execute(
                "INSERT INTO editions DEFAULT VALUES"
            ).lastrowid
            connection.execute(
                """INSERT INTO edition_works
                       (edition_id, work_id, position, relation_type, volume_id)
                   VALUES (?, ?, 0, 'contained', NULL)""",
                (edition, work),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO volumes
                           (edition_id, position, publication_year, publication_year_end)
                       VALUES (?, 0, 2024, 2023)""",
                    (edition,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE edition_works SET position = -1 WHERE edition_id = ?",
                    (edition,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO volumes (edition_id, position)
                       VALUES (?, -1)""",
                    (edition,),
                )
        finally:
            connection.close()

    def test_initialize_is_atomic_when_migration_fails(self) -> None:
        with patch("app.database.migrate_volume_model", side_effect=RuntimeError("stop")):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                initialize(self.path)
        connection = sqlite3.connect(self.path)
        try:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            self.assertEqual(tables, [])
        finally:
            connection.close()

    def test_rich_legacy_migration_is_idempotent_and_preserves_related_data(self) -> None:
        connection = sqlite3.connect(self.path)
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE works (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                authors TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE publishers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE publisher_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publisher_id INTEGER NOT NULL REFERENCES publishers(id),
                alias TEXT NOT NULL UNIQUE
            );
            CREATE TABLE editions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id INTEGER NOT NULL REFERENCES works(id),
                isbn TEXT NOT NULL DEFAULT '',
                identifier TEXT NOT NULL DEFAULT '',
                translator TEXT NOT NULL DEFAULT '',
                other_title TEXT NOT NULL DEFAULT '',
                translated_title TEXT NOT NULL DEFAULT '',
                translated_subtitle TEXT NOT NULL DEFAULT '',
                translation_script TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL DEFAULT '',
                publisher TEXT NOT NULL DEFAULT '',
                publisher_id INTEGER REFERENCES publishers(id),
                publication_year INTEGER
            );
            CREATE TABLE edition_works (
                edition_id INTEGER NOT NULL,
                work_id INTEGER NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                relation_type TEXT NOT NULL DEFAULT 'contained',
                volume_number TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (edition_id, work_id)
            );
            CREATE TABLE copies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edition_id INTEGER NOT NULL,
                volume_number TEXT NOT NULL DEFAULT '',
                volume_title TEXT NOT NULL DEFAULT '',
                identifier TEXT NOT NULL DEFAULT '',
                acquisition_date TEXT,
                location TEXT NOT NULL DEFAULT '',
                reading_record TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                parent_id INTEGER REFERENCES tags(id)
            );
            CREATE TABLE work_tags (
                work_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (work_id, tag_id)
            );
            INSERT INTO works (id, title, authors, language)
                VALUES (1, 'Legacy Main', 'Author', '藏文'),
                       (2, 'Contained Work', 'Other', '漢文');
            INSERT INTO publishers (id, canonical_name)
                VALUES (1, 'Canonical Press');
            INSERT INTO publisher_aliases (publisher_id, alias)
                VALUES (1, 'Legacy Press');
            INSERT INTO editions
                (id, work_id, isbn, translator, translation_script,
                 publisher, publisher_id, publication_year)
                VALUES (1, 1, 'ISBN SET', 'Translator', '藏文',
                        'Legacy Press', 1, 2001);
            INSERT INTO edition_works
                (edition_id, work_id, position, relation_type, volume_number)
                VALUES (1, 1, 0, 'volume', '1'),
                       (1, 2, 1, 'contained', '');
            INSERT INTO copies
                (id, edition_id, volume_number, volume_title, identifier, location)
                VALUES (1, 1, '1', 'First', 'ISBN V1', 'A'),
                       (2, 1, '1', 'First', 'ISBN V1', 'B'),
                       (3, 1, '2', 'Second', 'ISBN V2', 'C');
            INSERT INTO tags (id, name, parent_id)
                VALUES (1, 'History', NULL), (2, 'Tibet', 1);
            INSERT INTO work_tags (work_id, tag_id) VALUES (1, 2);
            """
        )
        connection.close()

        first_report = initialize(self.path)
        connection = connect(self.path)
        try:
            counts_before = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in (
                    "works", "editions", "volumes", "copies", "edition_works",
                    "publishers", "publisher_aliases", "tags", "work_tags",
                )
            }
            volumes = connection.execute(
                """SELECT volume_number, volume_title, identifier
                   FROM volumes ORDER BY position"""
            ).fetchall()
            copy_volume_ids = connection.execute(
                "SELECT volume_id FROM copies ORDER BY id"
            ).fetchall()
            edition = connection.execute(
                "SELECT identifier, edition_scripts, publisher_id FROM editions"
            ).fetchone()
            self.assertEqual(counts_before["volumes"], 2)
            self.assertEqual(copy_volume_ids[0][0], copy_volume_ids[1][0])
            self.assertNotEqual(copy_volume_ids[1][0], copy_volume_ids[2][0])
            self.assertEqual(
                [tuple(row) for row in volumes],
                [("1", "First", "ISBN V1"), ("2", "Second", "ISBN V2")],
            )
            self.assertEqual(tuple(edition), ("ISBN SET", "藏文", 1))
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertNotIn(
                "work_id",
                {row["name"] for row in connection.execute("PRAGMA table_info(editions)")},
            )
        finally:
            connection.close()

        second_report = initialize(self.path)
        connection = connect(self.path)
        try:
            counts_after = {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in counts_before
            }
            migration_names = {
                row[0] for row in connection.execute(
                    "SELECT name FROM schema_migrations"
                ).fetchall()
            }
        finally:
            connection.close()
        self.assertEqual(first_report, second_report)
        self.assertEqual(counts_before, counts_after)
        self.assertEqual(
            migration_names,
            {
                "work-edition-volume-copy-v1",
                "remove-legacy-three-layer-columns-v2",
            },
        )

    def test_real_multivolume_regressions_keep_scope_and_effective_sources(self) -> None:
        initialize(self.path)
        first = create_book(book_payload(
            "Course",
            edition_identifier="ISBN SET",
            volume_number="1",
            volume_identifier="ISBN V1",
            volume_version="第2版",
            volume_year=2001,
            location="A",
        ), self.path)
        second = create_book(book_payload(
            "Course",
            edition_identifier="ISBN SET",
            volume_number="2",
            volume_identifier="ISBN V2",
            volume_version="第3版",
            volume_year=2002,
            volume_responsibility="Volume Editor",
            location="B",
        ), self.path)
        create_copy_for_volume(
            first["volume_id"], CopyInput(location="A duplicate"), self.path
        )

        detail = get_work(list_works("Course", self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 1)
        volumes = detail["editions"][0]["volumes"]
        self.assertEqual(
            [group["volume"]["identifier"] for group in volumes],
            ["ISBN V1", "ISBN V2"],
        )
        self.assertEqual(
            [group["volume"]["version"] for group in volumes],
            ["第2版", "第3版"],
        )
        self.assertEqual(
            [group["volume"]["publication_year"] for group in volumes],
            [2001, 2002],
        )
        self.assertEqual([len(group["copies"]) for group in volumes], [2, 1])
        effective = volumes[1]["volume"]["effective_metadata"]
        self.assertEqual(effective["identifier"]["source"], "volume")
        self.assertEqual(
            effective["responsibility"]["value"],
            "Author; Translator; Volume Editor",
        )
        self.assertEqual(
            [item["source"] for item in effective["responsibility"]["sources"]],
            ["work", "edition", "volume"],
        )

    def test_explicit_work_creation_does_not_reuse_an_existing_work(self) -> None:
        initialize(self.path)
        payload = WorkInput(title="Explicit Work", authors="Author")
        first = create_work_record(payload, self.path)
        second = create_work_record(payload, self.path)
        self.assertNotEqual(first["id"], second["id"])

    def test_work_candidate_with_different_metadata_is_not_reused(self) -> None:
        initialize(self.path)
        first = create_book(
            BookInput(
                work=WorkInput(
                    title="Same title", subtitle="First subtitle",
                    authors="Same author", scripts="Latin",
                ),
                edition=EditionInput(publisher="Press"),
                volume=VolumeInput(),
                copy=CopyInput(location="A"),
            ),
            self.path,
        )
        second = create_book(
            BookInput(
                work=WorkInput(
                    title="Same title", subtitle="Second subtitle",
                    authors="Same author", scripts="Tibetan",
                ),
                edition=EditionInput(publisher="Press"),
                volume=VolumeInput(),
                copy=CopyInput(location="B"),
            ),
            self.path,
        )
        self.assertNotEqual(
            first["edition"]["work_ids"][0],
            second["edition"]["work_ids"][0],
        )
        self.assertEqual(
            {item["subtitle"] for item in list_works(path=self.path)},
            {"First subtitle", "Second subtitle"},
        )

    def test_single_volume_without_identifier_remains_valid(self) -> None:
        initialize(self.path)
        created = create_book(book_payload("No identifier", location="Shelf"), self.path)
        self.assertEqual(created["edition"]["identifier"], "")
        self.assertEqual(created["volume"]["identifier"], "")
        self.assertIsNone(
            created["volume"]["effective_metadata"]["identifier"]["source"]
        )


if __name__ == "__main__":
    unittest.main()
