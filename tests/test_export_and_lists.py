from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app.database import initialize
from app.export import export_csv, export_json
from app.repository import create_book, create_tag, get_work, list_works, update_tag
from app.schemas import (
    BookInput, CopyInput, EditionInput, TagInput, VolumeInput, WorkInput,
    identifier_warnings, normalize_version_text,
)


class ListNormalizationTests(unittest.TestCase):
    def test_semicolon_lists_and_numeric_versions_are_normalized(self) -> None:
        work = WorkInput(
            title='Test', authors='One；  Two', scripts='Latin、 Chinese',
            tag_names='Buddhism， Tibet',
        )
        edition = EditionInput(
            version='2； Revised、 3',
            translator='First， Second', other_title='；Parallel',
            other_subtitle='Subtitle；',
        )

        self.assertEqual(work.authors, 'One; Two')
        self.assertEqual(work.scripts, 'Latin; Chinese')
        self.assertEqual(work.tag_names, ['Buddhism', 'Tibet'])
        self.assertEqual(edition.version, '第2版; Revised; 第3版')
        self.assertEqual(edition.translator, 'First; Second')
        self.assertEqual(edition.other_title, '; Parallel')
        self.assertEqual(edition.other_subtitle, 'Subtitle;')

    def test_identifier_types_and_binding_priority_are_normalized(self) -> None:
        edition = EditionInput(
            identifier=(
                '978-0-19-005261-4 (pbk.); '
                '978-0-19-005260-7 (hbk.); '
                '978-0-19-005262-1 (ebook); '
                'ISSN 0169-8524'
            )
        )
        self.assertEqual(
            edition.identifier,
            'ISBN 9780190052607; ISSN 0169-8524',
        )
        self.assertEqual(
            EditionInput(identifier='統一書號：2018·204').identifier,
            '統一書號 2018·204',
        )
        self.assertEqual(
            EditionInput(
                identifier='ISBN 978-7-5600-3007-4; ISBN 978-7-5600-3319-8'
            ).identifier,
            'ISBN 9787560030074; ISBN 9787560033198',
        )
        self.assertEqual(
            EditionInput(identifier='識別號 識別號 书号 10019·1998').identifier,
            '书号 10019·1998',
        )

    def test_isbn_checksum_and_canonicalization(self) -> None:
        for value in ('0-306-40615-2', '0306406152', 'ISBN 0-306-40615-2'):
            self.assertEqual(
                EditionInput(identifier=value).identifier,
                'ISBN 9780306406157',
            )
        self.assertEqual(
            EditionInput(identifier='ISBN 0-8044-2957-X').identifier,
            'ISBN 9780804429573',
        )
        self.assertEqual(
            EditionInput(identifier='ISBN 979-10-90636-07-1').identifier,
            'ISBN 9791090636071',
        )
        self.assertEqual(
            EditionInput(identifier='ISBN 9780306406158').identifier,
            'ISBN 9780306406158',
        )
        self.assertEqual(
            identifier_warnings('ISBN 9780306406158'),
            ['ISBN 校驗碼不正確，請核對實物；仍可保存。'],
        )
        self.assertEqual(
            EditionInput(identifier='9780306406158').identifier,
            '識別號 9780306406158',
        )
        self.assertEqual(
            identifier_warnings('識別號 9780306406158'),
            ['疑似 ISBN，校驗未通過；仍保留為普通識別號。'],
        )
        for value in (
            'LCCN 9780306406158', '統一書號 9780306406158', 'CATALOG 9780306406158'
        ):
            self.assertEqual(identifier_warnings(value), [])
        self.assertEqual(
            EditionInput(
                identifier='ISBN 0-306-40615-2; ISSN 0169-8524; LCCN 2001012345'
            ).identifier,
            'ISBN 9780306406157; ISSN 0169-8524; LCCN 2001012345',
        )
        self.assertEqual(
            EditionInput(identifier='书号 10019·1998').identifier,
            '书号 10019·1998',
        )

    def test_chinese_isbn_suffix_is_discarded_after_validating_main_body(self) -> None:
        self.assertEqual(
            EditionInput(identifier='ISBN 978-7-5062-8280-2/O·731').identifier,
            'ISBN 9787506282802',
        )
        self.assertEqual(
            EditionInput(identifier='ISBN 7-5062-8280-1/O·731').identifier,
            'ISBN 9787506282802',
        )
        invalid_ten = EditionInput(identifier='ISBN 7-5062-8280-X/O·731')
        self.assertEqual(invalid_ten.identifier, 'ISBN 750628280X')
        self.assertTrue(identifier_warnings(invalid_ten.identifier))
        invalid = EditionInput(identifier='ISBN 978-7-5062-8280-3/O·731')
        self.assertEqual(invalid.identifier, 'ISBN 9787506282803')
        self.assertTrue(identifier_warnings(invalid.identifier))

    def test_editing_tag_keeps_work_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'tags.db'
            initialize(database)
            tag = create_tag(TagInput(name='Original'), database)
            create_book(BookInput(
                work=WorkInput(title='Tagged Book', tag_ids=[tag['id']]),
                edition=EditionInput(version='1'),
                copy=CopyInput(location='Shelf'),
            ), database)

            update_tag(tag['id'], TagInput(name='Renamed'), database)
            work = list_works(path=database)[0]
            detail = get_work(work['id'], database)

            assert detail is not None
            self.assertEqual(detail['work']['tag_ids'], [tag['id']])
            self.assertEqual(work['tags'][0]['name'], 'Renamed')


class ExportTests(unittest.TestCase):
    def test_json_and_csv_exports_include_complete_copy_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "export.db")
            with patch.dict(os.environ, {"LIBRARY_DATABASE": database}):
                initialize()
                tag = create_tag(TagInput(name="Buddhism"))
                create_book(BookInput(
                    work=WorkInput(
                        title="Export Test", authors="One; Two",
                        scripts="Tibetan; Chinese", tag_ids=[tag["id"]],
                    ),
                    edition=EditionInput(
                        identifier="ISSN 1234-5678; ISBN 9780306406157 (pbk.)",
                        version="2; Revised", publisher="Test Press",
                    ),
                    volume=VolumeInput(identifier="ISBN 9783161484100"),
                    copy=CopyInput(location="Study", reading_record="Read"),
                ))

                json_response = export_json()
                csv_response = export_csv()

            exported = json.loads(json_response.body)
            self.assertEqual(exported["schema_version"], 2)
            self.assertEqual(exported["model"], "Work-Edition-Volume-Copy")
            self.assertEqual(exported["works"][0]["tag_names"], ["Buddhism"])
            self.assertEqual(
                exported["editions"][0]["version"], normalize_version_text("2; Revised")
            )
            self.assertEqual(
                exported["editions"][0]["identifier"],
                "ISSN 1234-5678; ISBN 9780306406157",
            )
            self.assertEqual(
                exported["volumes"][0]["identifier"], "ISBN 9783161484100"
            )
            self.assertEqual(exported["copies"][0]["reading_record"], "Read")

            csv_text = csv_response.body.decode("utf-8-sig")
            rows = list(csv.DictReader(StringIO(csv_text)))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["schema_version"], "2")
            self.assertEqual(row["work_title"], "Export Test")
            self.assertEqual(
                row["edition_identifier"], "ISSN 1234-5678; ISBN 9780306406157"
            )
            self.assertEqual(row["volume_identifier"], "ISBN 9783161484100")
            self.assertEqual(row["copy_location"], "Study")
            self.assertEqual(row["copy_reading_record"], "Read")
            self.assertNotIn("copy_identifier", row)

if __name__ == '__main__':
    unittest.main()
