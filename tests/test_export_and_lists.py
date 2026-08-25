from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.database import initialize
from app.export import export_csv, export_json
from app.repository import create_book, create_tag, get_work, list_works, update_tag
from app.schemas import BookInput, CopyInput, EditionInput, TagInput, WorkInput


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
            'ISBN 978-0-19-005260-7; ISSN 0169-8524',
        )
        self.assertEqual(
            EditionInput(identifier='統一書號：2018·204').identifier,
            '統一書號 2018·204',
        )
        self.assertEqual(
            EditionInput(identifier='識別號 識別號 书号 10019·1998').identifier,
            '书号 10019·1998',
        )
        self.assertEqual(
            EditionInput(identifier='书号 10019·1998').identifier,
            '书号 10019·1998',
        )

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
            database = str(Path(directory) / 'export.db')
            with patch.dict(os.environ, {'LIBRARY_DATABASE': database}):
                initialize()
                tag = create_tag(TagInput(name='Buddhism'))
                create_book(BookInput(
                    work=WorkInput(
                        title='Export Test', authors='One; Two',
                        scripts='Tibetan; Chinese', tag_ids=[tag['id']],
                    ),
                    edition=EditionInput(
                        identifier='ISSN 1234-5678; ISBN 978-1-2-3 (pbk.)',
                        version='2; Revised', publisher='Test Press',
                    ),
                    copy=CopyInput(location='Study', reading_record='Read'),
                ))

                json_response = export_json()
                csv_response = export_csv()

            exported = json.loads(json_response.body)
            self.assertEqual(exported[0]['work']['tag_names'], ['Buddhism'])
            self.assertEqual(exported[0]['edition']['version'], '第2版; Revised')
            self.assertEqual(
                exported[0]['edition']['identifier'],
                'ISSN 1234-5678; ISBN 978-1-2-3',
            )
            csv_text = csv_response.body.decode('utf-8-sig')
            self.assertIn('copy_id,title,subtitle,authors', csv_text)
            self.assertIn('other_title,other_subtitle', csv_text)
            self.assertIn('edition_scripts', csv_text)
            self.assertIn('Export Test', csv_text)
            self.assertIn('ISSN 1234-5678; ISBN 978-1-2-3', csv_text)
            self.assertIn('Read', csv_text)


if __name__ == '__main__':
    unittest.main()
