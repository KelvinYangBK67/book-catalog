from __future__ import annotations

import csv
from io import StringIO
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .edition_matching import editions_match
from .repository import create_book, list_books, list_publishers, update_book
from .schemas import BookInput


router = APIRouter()
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000


class CsvImportSelection(BaseModel):
    row_number: int
    book: BookInput
    action: Literal['create', 'replace'] = 'create'
    target_copy_id: int | None = None
    target_row_number: int | None = None


class CsvImportCommit(BaseModel):
    rows: list[CsvImportSelection] = Field(max_length=MAX_ROWS)


def _text(row: dict[str, str | None], key: str) -> str:
    return str(row.get(key) or '').strip()


def _book_from_row(row: dict[str, str | None]) -> BookInput:
    year = _text(row, 'publication_year')
    return BookInput.model_validate({
        'work': {
            'title': _text(row, 'title'),
            'subtitle': _text(row, 'subtitle'),
            'authors': _text(row, 'authors'),
            'scripts': _text(row, 'scripts'),
            'tag_names': _text(row, 'tags'),
        },
        'edition': {
            'identifier': _text(row, 'identifier'),
            'version': _text(row, 'version'),
            'series': _text(row, 'series'),
            'translator': _text(row, 'translator'),
            'other_title': _text(row, 'other_title'),
            'other_subtitle': _text(row, 'other_subtitle'),
            'translated_title': _text(row, 'translated_title'),
            'translated_subtitle': _text(row, 'translated_subtitle'),
            'edition_scripts': _text(row, 'edition_scripts') or _text(row, 'translation_script'),
            'publisher': _text(row, 'publisher'),
            'publication_year': int(year) if year else None,
        },
        'copy': {
            'volume': _text(row, 'volume'),
            'acquisition_date': _text(row, 'acquisition_date') or None,
            'location': _text(row, 'location'),
            'reading_record': _text(row, 'reading_record'),
        },
    })


def _key(value: str) -> str:
    return value.strip().casefold()


def preview_csv(content: bytes) -> list[dict]:
    if len(content) > MAX_CSV_BYTES:
        raise ValueError('CSV file is larger than 5 MB')
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise ValueError('CSV must use UTF-8 encoding') from error
    reader = csv.DictReader(StringIO(text, newline=''))
    if not reader.fieldnames or 'title' not in reader.fieldnames:
        raise ValueError('CSV is missing the title column')

    publisher_ids = {
        alias.strip().casefold(): publisher['id']
        for publisher in list_publishers()
        for alias in publisher['aliases']
    }
    candidates = [
        {
            'book': candidate,
            'id': candidate['id'],
            'location': candidate['copy']['location'],
            'row_number': None,
        }
        for candidate in list_books()
    ]
    previews: list[dict] = []
    for index, row in enumerate(reader, start=2):
        if index > MAX_ROWS + 1:
            raise ValueError(f'CSV may contain at most {MAX_ROWS} rows')
        if not any(str(value or '').strip() for value in row.values()):
            continue
        try:
            book = _book_from_row(row)
            if book.edition.publisher and book.edition.publisher_id is None:
                book.edition.publisher_id = publisher_ids.get(
                    book.edition.publisher.strip().casefold()
                )
        except (ValueError, TypeError) as error:
            raise ValueError(f'CSV row {index}: {error}') from error
        edition_matches = [
            candidate
            for candidate in candidates
            if _key(candidate['book']['work']['title']) == _key(book.work.title)
            and _key(candidate['book']['work']['authors']) == _key(book.work.authors)
            and editions_match(candidate['book']['edition'], book.edition)
        ]
        duplicates = [
            {
                'id': candidate['id'],
                'location': candidate['location'],
                'row_number': candidate['row_number'],
            }
            for candidate in edition_matches
            if _key(candidate['book']['copy']['volume']) == _key(book.copy_.volume)
        ]
        previews.append({
            'row_number': index,
            'book': book.model_dump(by_alias=True, mode='json'),
            'matching_copies': duplicates,
            'matching_edition_copies': [
                {
                    'id': candidate['id'],
                    'row_number': candidate['row_number'],
                    'volume': candidate['book']['copy']['volume'],
                    'location': candidate['location'],
                }
                for candidate in edition_matches
            ],
        })
        candidates.append({
            'book': book.model_dump(by_alias=True, mode='json'),
            'id': None,
            'location': book.copy_.location,
            'row_number': index,
        })
    return previews


@router.post('/api/import/csv/preview', include_in_schema=False)
async def csv_preview(request: Request) -> dict:
    try:
        rows = preview_csv(await request.body())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {'rows': rows}


@router.post('/api/import/csv', include_in_schema=False)
def csv_import(payload: CsvImportCommit) -> dict:
    created_ids: list[int] = []
    overwritten_ids: list[int] = []
    copy_by_row: dict[int, int] = {}
    for selection in payload.rows:
        if selection.action == 'create':
            copy_id = create_book(selection.book)['id']
            created_ids.append(copy_id)
        else:
            copy_id = selection.target_copy_id
            if copy_id is None and selection.target_row_number is not None:
                copy_id = copy_by_row.get(selection.target_row_number)
            if copy_id is None:
                raise HTTPException(
                    status_code=422,
                    detail=f'CSV row {selection.row_number} has no copy selected for replacement',
                )
            if update_book(copy_id, selection.book) is None:
                raise HTTPException(
                    status_code=422,
                    detail=f'Copy #{copy_id} selected by CSV row {selection.row_number} no longer exists',
                )
            overwritten_ids.append(copy_id)
        copy_by_row[selection.row_number] = copy_id
    return {
        'imported': len(created_ids),
        'overwritten': len(overwritten_ids),
        'copy_ids': created_ids,
        'overwritten_copy_ids': overwritten_ids,
    }
