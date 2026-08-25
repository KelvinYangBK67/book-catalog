from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.database import initialize
from app.import_csv import CsvImportCommit, CsvImportSelection, csv_import, preview_csv
from app.repository import create_book, list_books, list_publishers, normalize_publisher
from app.schemas import (
    BookInput, CopyInput, EditionInput, PublisherNormalizationInput, WorkInput,
    normalize_version_text,
)


def make_book(publisher: str = 'Raw Press') -> BookInput:
    return BookInput(
        work=WorkInput(title='Shared Title', authors='Shared Author'),
        edition=EditionInput(version='2', series='Collected Works', publisher=publisher),
        copy=CopyInput(volume='1', location='Shelf A'),
    )


class ImportAndNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'library.db'
        self.environment = patch.dict(os.environ, {'LIBRARY_DATABASE': str(self.path)})
        self.environment.start()
        initialize()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp.cleanup()

    def test_series_is_persisted_and_numeric_version_is_normalized(self) -> None:
        record = create_book(make_book())
        self.assertEqual(record['edition']['series'], 'Collected Works')
        self.assertEqual(record['edition']['version'], normalize_version_text('2'))

    def test_publisher_is_normalized_only_after_explicit_action(self) -> None:
        first = create_book(make_book('Raw Press'))
        self.assertEqual(first['edition']['publisher_canonical'], '')
        self.assertEqual(list_publishers(), [])

        normalized = normalize_publisher(PublisherNormalizationInput(
            canonical_name='Preferred Press',
            aliases=['Raw Press', 'Second Raw Name'],
        ))
        second = create_book(make_book('Second Raw Name'))

        self.assertEqual(normalized['canonical_name'], 'Preferred Press')
        self.assertEqual(second['edition']['publisher_canonical'], 'Preferred Press')
        self.assertEqual(set(normalized['aliases']), {
            'Preferred Press', 'Raw Press', 'Second Raw Name',
        })

    def test_csv_preview_resolves_publisher_alias_like_form_submission(self) -> None:
        normalize_publisher(PublisherNormalizationInput(
            canonical_name='Preferred Press', aliases=['Raw Press', 'Alias Press'],
        ))
        create_book(make_book('Raw Press'))
        rows = preview_csv(
            b'title,authors,version,series,publisher,volume,location\n'
            b'Shared Title,Shared Author,2,Collected Works,Alias Press,1,Shelf B\n'
        )
        self.assertEqual(len(rows[0]['matching_copies']), 1)
        self.assertIsNotNone(rows[0]['book']['edition']['publisher_id'])

    def test_csv_preview_detects_existing_and_in_file_copy_matches(self) -> None:
        create_book(make_book())
        csv_bytes = (
            'title,authors,version,series,publisher,volume,location\n'
            'Shared Title,Shared Author,2,Collected Works,Raw Press,1,Shelf B\n'
            'Shared Title,Shared Author,2,Collected Works,Raw Press,1,Shelf C\n'
        ).encode()

        rows = preview_csv(csv_bytes)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['book']['edition']['series'], 'Collected Works')
        self.assertEqual(len(rows[0]['matching_copies']), 1)
        self.assertEqual(len(rows[1]['matching_copies']), 2)

    def test_three_volumes_are_grouped_under_one_work_and_edition(self) -> None:
        rows = preview_csv(
            b'title,authors,version,volume,location\n'
            b'Zhuangzi Collected Commentary,Guo Qingfan,3,1,Shelf A\n'
            b'Zhuangzi Collected Commentary,Guo Qingfan,3,2,Shelf A\n'
            b'Zhuangzi Collected Commentary,Guo Qingfan,3,3,Shelf A\n'
        )

        self.assertEqual(len(rows[1]['matching_copies']), 0)
        self.assertEqual(len(rows[1]['matching_edition_copies']), 1)
        self.assertEqual(len(rows[2]['matching_edition_copies']), 2)
        csv_import(CsvImportCommit(rows=[
            CsvImportSelection(
                row_number=row['row_number'],
                book=BookInput.model_validate(row['book']),
                action='create',
            )
            for row in rows
        ]))

        books = list_books()
        self.assertEqual(len(books), 3)
        self.assertEqual(len({book['work']['title'] for book in books}), 1)
        self.assertEqual(len({book['edition']['version'] for book in books}), 1)
        self.assertEqual(
            {book['copy']['volume_number'] for book in books},
            {'1', '2', '3'},
        )

    def test_csv_commit_obeys_copy_choice_and_merges_hierarchy(self) -> None:
        rows = preview_csv(
            b'title,authors,version,series,volume,location\n'
            b'Shared Title,Shared Author,2,Collected Works,1,Shelf A\n'
            b'Shared Title,Shared Author,2,Collected Works,1,Shelf B\n'
        )
        result = csv_import(CsvImportCommit(rows=[
            CsvImportSelection(
                row_number=rows[0]['row_number'],
                book=BookInput.model_validate(rows[0]['book']),
                action='create',
            ),
            CsvImportSelection(
                row_number=rows[1]['row_number'],
                book=BookInput.model_validate(rows[1]['book']),
                action='replace',
                target_row_number=rows[0]['row_number'],
            ),
        ]))

        self.assertEqual(result['imported'], 1)
        self.assertEqual(result['overwritten'], 1)
        books = list_books()
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]['edition']['series'], 'Collected Works')
        self.assertEqual(books[0]['copy']['location'], 'Shelf B')

    def test_csv_requires_explicit_identifier_transition_choice(self) -> None:
        original_book = make_book()
        original_book.edition.identifier = "ISBN SET"
        create_book(original_book)

        rows = preview_csv(
            b'title,authors,identifier,version,series,publisher,volume,copy_identifier,location\n'
            b'Shared Title,Shared Author,ISBN SET,2,Collected Works,Raw Press,2,ISBN VOLUME-2,Shelf B\n'
        )
        self.assertTrue(rows[0]['identifier_transition_required'])
        self.assertEqual(rows[0]['transition_edition_identifier'], 'ISBN SET')

        imported = BookInput.model_validate(rows[0]['book'])
        imported.copy_.identifier_transition = 'keep'
        csv_import(CsvImportCommit(rows=[CsvImportSelection(
            row_number=rows[0]['row_number'],
            book=imported,
            csv_fields=rows[0]['csv_fields'],
            action='create',
        )]))

        books = list_books()
        self.assertEqual(len(books), 2)
        self.assertEqual({book['edition']['identifier'] for book in books}, {'ISBN SET'})
        self.assertEqual(
            {book['copy']['identifier'] for book in books},
            {'', 'ISBN VOLUME-2'},
        )

    def test_csv_can_overwrite_an_existing_copy(self) -> None:
        original = create_book(make_book())
        rows = preview_csv(
            b'title,authors,version,series,publisher,volume,location,reading_record\n'
            b'Shared Title,Shared Author,2,Collected Works,Raw Press,1,New Shelf,Replaced\n'
        )
        result = csv_import(CsvImportCommit(rows=[
            CsvImportSelection(
                row_number=rows[0]['row_number'],
                book=BookInput.model_validate(rows[0]['book']),
                action='replace',
                target_copy_id=original['id'],
            ),
        ]))

        self.assertEqual(result['imported'], 0)
        self.assertEqual(result['overwritten_copy_ids'], [original['id']])
        books = list_books()
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]['copy']['location'], 'New Shelf')
        self.assertEqual(books[0]['copy']['reading_record'], 'Replaced')


    def test_csv_present_empty_fields_clear_values_and_absent_fields_are_preserved(self) -> None:
        original = create_book(BookInput(
            work=WorkInput(
                title='Clearable', subtitle='Old subtitle', authors='Author', scripts='Tibetan',
                tag_names=['Old tag'],
            ),
            edition=EditionInput(
                identifier='ISBN 123', translator='Translator', series='Series',
                publisher='Press', publication_year=2020,
            ),
            copy=CopyInput(volume='1', location='Old shelf', reading_record='Read'),
        ))
        rows = preview_csv(
            b'title,authors,subtitle,tags,identifier,series,location\n'
            b'Clearable,Author,,,,,New shelf\n'
        )

        csv_import(CsvImportCommit(rows=[CsvImportSelection(
            row_number=rows[0]['row_number'],
            book=BookInput.model_validate(rows[0]['book']),
            csv_fields=rows[0]['csv_fields'],
            action='replace',
            target_copy_id=original['id'],
        )]))

        book = list_books()[0]
        self.assertEqual(book['work']['subtitle'], '')
        self.assertEqual(book['work']['scripts'], 'Tibetan')
        self.assertEqual(book['work']['tag_ids'], [])
        self.assertEqual(book['edition']['identifier'], '')
        self.assertEqual(book['edition']['series'], '')
        self.assertEqual(book['edition']['translator'], 'Translator')
        self.assertEqual(book['edition']['publisher'], 'Press')
        self.assertEqual(book['edition']['publication_year'], 2020)
        self.assertEqual(book['copy']['location'], 'New shelf')
        self.assertEqual(book['copy']['reading_record'], 'Read')
