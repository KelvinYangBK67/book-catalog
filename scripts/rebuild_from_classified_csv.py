from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import connect, initialize
from app.import_csv import _book_from_row
from app.repository import create_book, normalize_publisher
from app.schemas import PublisherNormalizationInput


def rebuild(source: Path, target: Path) -> dict:
    if target.exists():
        raise FileExistsError(f'target already exists: {target}')
    initialize(target)
    publisher_aliases: dict[str, set[str]] = defaultdict(set)
    with source.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    for row_number, row in enumerate(rows, start=2):
        try:
            create_book(_book_from_row(row), target)
        except Exception as error:
            raise ValueError(f'failed to import CSV row {row_number}: {error}') from error
        canonical = str(row.get('publisher_canonical') or '').strip()
        raw_name = str(row.get('publisher') or '').strip()
        if canonical:
            publisher_aliases[canonical].add(canonical)
            if raw_name:
                publisher_aliases[canonical].add(raw_name)
    for canonical, aliases in publisher_aliases.items():
        normalize_publisher(PublisherNormalizationInput(
            canonical_name=canonical,
            aliases=sorted(aliases),
        ), target)

    connection = connect(target)
    try:
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            for table in ('works', 'editions', 'copies', 'tags', 'publishers')
        }
    finally:
        connection.close()
    return {'source_rows': len(rows), **counts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    print(json.dumps(rebuild(args.source, args.target), ensure_ascii=False))


if __name__ == '__main__':
    main()
