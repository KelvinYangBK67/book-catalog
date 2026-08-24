from __future__ import annotations

import csv
import json
from io import StringIO

from fastapi import APIRouter
from fastapi.responses import Response

from .repository import list_books, list_works


router = APIRouter()


def export_records() -> list[dict]:
    tag_lookup = {
        (work['title'], work['authors']): [tag['name'] for tag in work['tags']]
        for work in list_works()
    }
    records = list_books()
    for record in records:
        key = (record['work']['title'], record['work']['authors'])
        record['work']['tag_names'] = tag_lookup.get(key, [])
    return records


@router.get('/api/export/json', include_in_schema=False)
def export_json() -> Response:
    content = json.dumps(export_records(), ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type='application/json',
        headers={'Content-Disposition': 'attachment; filename=book-catalog.json'},
    )


@router.get('/api/export/csv', include_in_schema=False)
def export_csv() -> Response:
    fields = [
        'copy_id', 'title', 'subtitle', 'authors', 'scripts', 'tags',
        'identifier', 'version', 'series', 'translator', 'other_title', 'other_subtitle',
        'translated_title', 'translated_subtitle', 'edition_scripts',
        'publisher', 'publisher_canonical', 'publication_year',
        'volume', 'acquisition_date', 'location', 'reading_record',
    ]
    output = StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for record in export_records():
        work = record['work']
        edition = record['edition']
        copy = record['copy']
        writer.writerow({
            'copy_id': record['id'], 'title': work['title'],
            'subtitle': work['subtitle'], 'authors': work['authors'],
            'scripts': work['scripts'], 'tags': '; '.join(work['tag_names']),
            'identifier': edition['identifier'], 'version': edition['version'],
            'series': edition['series'],
            'translator': edition['translator'], 'other_title': edition['other_title'],
            'other_subtitle': edition['other_subtitle'],
            'translated_title': edition['translated_title'],
            'translated_subtitle': edition['translated_subtitle'],
            'edition_scripts': edition['edition_scripts'],
            'publisher': edition['publisher'],
            'publisher_canonical': edition['publisher_canonical'],
            'publication_year': edition['publication_year'],
            'volume': copy['volume'], 'acquisition_date': copy['acquisition_date'],
            'location': copy['location'], 'reading_record': copy['reading_record'],
        })
    return Response(
        content='\ufeff' + output.getvalue(),
        media_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename=book-catalog.csv'},
    )
