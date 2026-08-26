from __future__ import annotations

import csv
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app.database import connect, initialize
from app.export import export_csv, export_document
from app.import_csv import (
    CsvImportCommit,
    CsvImportSelection,
    csv_import,
    preview_csv,
)
from app.import_json import import_json_document
from app.main import (
    add_book, add_volume, add_volume_copy, book as api_book, copy as api_copy,
    edit_copy, edit_volume, edition as api_edition, work as api_work,
)
from app.repository import (
    create_book,
    create_copy_for_volume,
    create_tag,
    create_work_record,
    get_work,
    list_books,
    list_publishers,
    list_tags,
    normalize_publisher,
)
from app.schemas import (
    BookInput, CopyDetail, EditionDetail, VolumeDetail, WorkDetail,
    CopyInput,
    EditionInput,
    PublisherNormalizationInput,
    TagInput,
    VolumeInput,
    WorkInput,
)


def import_all(rows: list[dict]) -> dict:
    return csv_import(CsvImportCommit(rows=[
        CsvImportSelection(
            row_number=row["row_number"],
            book=BookInput.model_validate(row["book"]),
            csv_fields=row["csv_fields"],
            action="create",
        )
        for row in rows
    ]))


class JsonV2RoundTripTests(unittest.TestCase):
    def test_schema_version_roundtrip_preserves_relations_tags_and_publishers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.db"
            target = Path(directory) / "target.db"
            initialize(source)
            initialize(target)

            parent = create_tag(TagInput(name="History"), source)
            leaf = create_tag(
                TagInput(name="Modern", parent_id=parent["id"]), source
            )
            other = create_work_record(
                WorkInput(title="Contained Work", authors="Second Author"), source
            )
            publisher = normalize_publisher(PublisherNormalizationInput(
                canonical_name="Canonical Press",
                aliases=["Raw Press", "Other Raw Press"],
            ), source)
            first = create_book(BookInput(
                work=WorkInput(
                    title="Round Trip", authors="Author", scripts="Latin",
                    tag_ids=[leaf["id"]],
                ),
                edition=EditionInput(
                    title="Edition Title",
                    identifier="CATALOG SET",
                    version="Second",
                    publisher="Raw Press",
                    publisher_id=publisher["id"],
                    work_ids=[other["id"]],
                ),
                volume=VolumeInput(
                    position=1, volume_number="1", identifier="CATALOG V1",
                    version="Volume Version", publication_year=2001,
                    responsibility="Volume Editor",
                ),
                copy=CopyInput(location="Shelf A", reading_record="Read"),
            ), source)
            create_copy_for_volume(
                first["volume_id"], CopyInput(location="Shelf B"), source
            )
            second = BookInput(
                work=WorkInput(
                    title="Round Trip", authors="Author", scripts="Latin",
                    tag_ids=[leaf["id"]],
                ),
                edition=EditionInput(
                    title="Edition Title",
                    identifier="CATALOG SET",
                    version="Second",
                    publisher="Raw Press",
                    publisher_id=publisher["id"],
                    work_ids=[other["id"]],
                ),
                volume=VolumeInput(
                    position=2, volume_number="2", identifier="CATALOG V2",
                    version="Other Volume Version", publication_year=2002,
                    responsibility="Other Editor",
                ),
                copy=CopyInput(location="Shelf C"),
            )
            create_book(second, source)

            document = export_document(source)
            self.assertEqual(document["schema_version"], 2)
            result = import_json_document(document, target)
            self.assertEqual(result["imported"]["copies"], 3)

            roundtrip = export_document(target)
            self.assertEqual(roundtrip["schema_version"], 2)
            self.assertEqual(
                [v["identifier"] for v in roundtrip["volumes"]],
                ["CATALOG V1", "CATALOG V2"],
            )
            self.assertEqual(
                [v["publication_year"] for v in roundtrip["volumes"]],
                [2001, 2002],
            )
            self.assertEqual(len(roundtrip["copies"]), 3)
            self.assertEqual(len(roundtrip["editions"][0]["work_relations"]), 2)
            self.assertEqual(
                {tag["name"] for tag in roundtrip["tags"]},
                {"History", "Modern"},
            )
            self.assertEqual(
                roundtrip["publishers"][0]["canonical_name"], "Canonical Press"
            )
            self.assertEqual(
                set(roundtrip["publishers"][0]["aliases"]),
                {"Canonical Press", "Raw Press", "Other Raw Press"},
            )


class CsvV2RoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name) / "source.db"
        self.target = Path(self.temp.name) / "target.db"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _source_csv(self) -> bytes:
        with patch.dict(os.environ, {"LIBRARY_DATABASE": str(self.source)}):
            initialize()
            tag = create_tag(TagInput(name="Portable Tag"))
            normalized = normalize_publisher(PublisherNormalizationInput(
                canonical_name="Canonical Press", aliases=["Raw Press"],
            ))
            first = create_book(BookInput(
                work=WorkInput(
                    title="CSV Round Trip", authors="Author",
                    tag_ids=[tag["id"]],
                ),
                edition=EditionInput(
                    identifier="CATALOG SET", version="Common Version",
                    publisher="Raw Press", publisher_id=normalized["id"],
                ),
                volume=VolumeInput(
                    volume_number="1", identifier="CATALOG V1",
                    version="Volume One Version", publication_year=2001,
                    responsibility="Editor One",
                ),
                copy=CopyInput(location="Shelf A"),
            ))
            create_copy_for_volume(
                first["volume_id"], CopyInput(location="Shelf B")
            )
            create_book(BookInput(
                work=WorkInput(
                    title="CSV Round Trip", authors="Author",
                    tag_ids=[tag["id"]],
                ),
                edition=EditionInput(
                    identifier="CATALOG SET", version="Common Version",
                    publisher="Raw Press", publisher_id=normalized["id"],
                ),
                volume=VolumeInput(
                    volume_number="2", identifier="CATALOG V2",
                    version="Volume Two Version", publication_year=2002,
                    responsibility="Editor Two",
                ),
                copy=CopyInput(location="Shelf C"),
            ))
            return export_csv().body

    def test_new_csv_roundtrip_preserves_four_layers(self) -> None:
        content = self._source_csv()
        header = next(csv.reader(StringIO(content.decode("utf-8-sig"))))
        self.assertIn("edition_identifier", header)
        self.assertIn("volume_identifier", header)
        self.assertIn("copy_location", header)
        self.assertNotIn("copy_identifier", header)

        with patch.dict(os.environ, {"LIBRARY_DATABASE": str(self.target)}):
            initialize()
            rows = preview_csv(content)
            result = import_all(rows)
            self.assertEqual(result["imported"], 3)
            books = list_books()
            self.assertEqual(len({book["edition_id"] for book in books}), 1)
            self.assertEqual(len({book["volume_id"] for book in books}), 2)
            self.assertEqual(len(books), 3)
            self.assertEqual(
                {book["edition"]["identifier"] for book in books}, {"CATALOG SET"}
            )
            by_volume = {
                book["volume"]["volume_number"]: book["volume"]
                for book in books
            }
            self.assertEqual(by_volume["1"]["identifier"], "CATALOG V1")
            self.assertEqual(by_volume["2"]["identifier"], "CATALOG V2")
            self.assertEqual(by_volume["1"]["publication_year"], 2001)
            self.assertEqual(by_volume["2"]["publication_year"], 2002)
            self.assertEqual(by_volume["1"]["responsibility"], "Editor One")
            self.assertEqual(by_volume["2"]["responsibility"], "Editor Two")
            self.assertEqual(
                {item["name"] for item in list_tags()}, {"Portable Tag"}
            )
            self.assertEqual(
                list_publishers()[0]["canonical_name"], "Canonical Press"
            )

    def test_legacy_copy_identifier_maps_to_volume(self) -> None:
        legacy = (
            "title,authors,identifier,volume_number,volume_title,"
            "copy_identifier,location,acquisition_date,reading_record\n"
            "Legacy Book,Legacy Author,CATALOG SET,1,First,"
            "CATALOG VOLUME,Shelf,2020-01-02,Read\n"
        ).encode()
        with patch.dict(os.environ, {"LIBRARY_DATABASE": str(self.target)}):
            initialize()
            rows = preview_csv(legacy)
            self.assertEqual(
                rows[0]["book"]["volume"]["identifier"], "CATALOG VOLUME"
            )
            self.assertNotIn("identifier", rows[0]["book"]["copy"])
            import_all(rows)
            book = list_books()[0]
            self.assertEqual(book["edition"]["identifier"], "CATALOG SET")
            self.assertEqual(book["volume"]["identifier"], "CATALOG VOLUME")
            self.assertEqual(book["copy"]["location"], "Shelf")
            self.assertEqual(book["copy"]["reading_record"], "Read")

    def test_duplicate_volume_and_copy_are_detected_separately(self) -> None:
        with patch.dict(os.environ, {"LIBRARY_DATABASE": str(self.target)}):
            initialize()
            create_book(BookInput(
                work=WorkInput(title="Duplicate", authors="Author"),
                edition=EditionInput(version="First"),
                volume=VolumeInput(volume_number="1"),
                copy=CopyInput(location="Shelf A"),
            ))
            rows = preview_csv((
                "title,authors,version,volume,location\n"
                "Duplicate,Author,First,1,Shelf B\n"
                "Duplicate,Author,First,1,Shelf A\n"
            ).encode())
            self.assertEqual(len(rows[0]["matching_volumes"]), 1)
            self.assertEqual(len(rows[0]["matching_copies"]), 0)
            self.assertGreaterEqual(len(rows[1]["matching_volumes"]), 1)
            self.assertEqual(len(rows[1]["matching_copies"]), 1)


class FourLayerApiTests(unittest.TestCase):
    def test_independent_edition_volume_and_copy_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api.db"
            with patch.dict(os.environ, {"LIBRARY_DATABASE": str(path)}):
                initialize()
                record = add_book(BookInput(
                    work=WorkInput(title="API Book", authors="Author"),
                    edition=EditionInput(
                        identifier="CATALOG SET", version="Common", publisher="Press",
                    ),
                    volume=VolumeInput(volume_number="1"),
                    copy=CopyInput(location="Shelf A"),
                ))
                work_id = record["edition"]["work_ids"][0]
                edition_id = record["edition_id"]
                volume_id = record["volume_id"]
                copy_id = record["id"]

                WorkDetail.model_validate(api_work(work_id))
                edition_detail = EditionDetail.model_validate(
                    api_edition(edition_id)
                )
                self.assertEqual(edition_detail.volumes[0].id, volume_id)

                volume_2 = VolumeDetail.model_validate(add_volume(
                    edition_id,
                    VolumeInput(
                        volume_number="2", identifier="CATALOG V2",
                        version="Volume Version", publication_year=2002,
                        responsibility="Editor",
                    ),
                ))
                duplicate_shape = VolumeDetail.model_validate(add_volume(
                    edition_id,
                    VolumeInput(
                        volume_number="2", identifier="CATALOG V2",
                        version="Volume Version", publication_year=2002,
                        responsibility="Editor",
                    ),
                ))
                self.assertNotEqual(duplicate_shape.id, volume_2.id)
                self.assertEqual(len(api_edition(edition_id)["volumes"]), 3)

                copy_2 = CopyDetail.model_validate(add_volume_copy(
                    volume_2.id, CopyInput(location="Shelf B")
                ))
                updated_volume = VolumeDetail.model_validate(edit_volume(
                    volume_2.id,
                    VolumeInput(
                        volume_number="2", identifier="CATALOG V2 revised",
                        version="Volume Version", publication_year=2003,
                        responsibility="Editor",
                    ),
                ))
                self.assertEqual(
                    updated_volume.volume.identifier, "CATALOG V2 revised"
                )
                updated_copy = CopyDetail.model_validate(edit_copy(
                    copy_2.id,
                    CopyInput(location="Archive", reading_record="Unread"),
                ))
                self.assertEqual(updated_copy.location, "Archive")
                self.assertFalse(hasattr(updated_copy, "identifier"))

                compatibility = api_book(copy_2.id)
                self.assertEqual(
                    compatibility["volume"]["identifier"], "CATALOG V2 revised"
                )
                self.assertEqual(api_copy(copy_id)["volume_id"], volume_id)

if __name__ == "__main__":
    unittest.main()
