from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

from .database import connect
from .repository import list_books, list_works, publication_year_display


router = APIRouter()
JSON_SCHEMA_VERSION = 2
CSV_SCHEMA_VERSION = 2

CSV_FIELDS = [
    "schema_version",
    "work_id", "work_title", "work_subtitle", "work_authors",
    "work_scripts", "work_tag_ids", "work_tag_names",
    "edition_id", "edition_title", "edition_subtitle",
    "edition_work_ids", "edition_work_relations",
    "edition_identifier", "edition_version", "edition_series",
    "edition_responsibility", "edition_general_responsibility",
    "edition_other_title", "edition_other_subtitle",
    "edition_translated_title", "edition_translated_subtitle",
    "edition_scripts", "edition_publisher", "edition_publisher_canonical",
    "edition_publication_year",
    "volume_id", "volume_position", "volume_number", "volume_title",
    "volume_identifier", "volume_version", "volume_publication_year",
    "volume_responsibility",
    "copy_id", "copy_acquisition_date", "copy_location",
    "copy_reading_record",
]


def _rows(connection, sql: str) -> list[dict]:
    return [dict(row) for row in connection.execute(sql).fetchall()]


def export_document(path: Path | None = None) -> dict:
    connection = connect(path)
    try:
        works = _rows(
            connection,
            """SELECT id, title, subtitle, authors, scripts
               FROM works ORDER BY id""",
        )
        tag_names = {
            row["work_id"]: []
            for row in connection.execute("SELECT id AS work_id FROM works")
        }
        tag_ids = {work_id: [] for work_id in tag_names}
        for row in connection.execute(
            """SELECT wt.work_id, t.id, t.name FROM work_tags wt
               JOIN tags t ON t.id = wt.tag_id ORDER BY wt.work_id, t.id"""
        ):
            tag_ids[row["work_id"]].append(row["id"])
            tag_names[row["work_id"]].append(row["name"])
        for work in works:
            work["tag_ids"] = tag_ids.get(work["id"], [])
            work["tag_names"] = tag_names.get(work["id"], [])

        editions = _rows(
            connection,
            """SELECT e.id,
                      (SELECT ew.work_id FROM edition_works ew
                       WHERE ew.edition_id = e.id
                       ORDER BY ew.position LIMIT 1) AS primary_work_id,
                      e.title, e.subtitle,
                      e.identifier, e.translator, e.responsibility,
                      e.other_title, e.other_subtitle,
                      e.translated_title, e.translated_subtitle, e.edition_scripts,
                      e.version, e.series, e.publisher, e.publisher_id,
                      e.publication_year, e.publication_year_end, e.force_separate
               FROM editions e ORDER BY e.id""",
        )
        relations: dict[int, list[dict]] = {}
        for row in connection.execute(
            """SELECT edition_id, work_id, position, relation_type, volume_id
               FROM edition_works ORDER BY edition_id, position"""
        ):
            relations.setdefault(row["edition_id"], []).append({
                "work_id": row["work_id"],
                "position": row["position"],
                "relation_type": row["relation_type"],
                "volume_id": row["volume_id"],
            })
        for edition in editions:
            edition["publication_year"] = publication_year_display(
                edition["publication_year"], edition.pop("publication_year_end")
            )
            edition["work_relations"] = relations.get(edition["id"], [])

        volumes = _rows(
            connection,
            """SELECT id, edition_id, position, volume_number, volume_title,
                      identifier, version, publication_year,
                      publication_year_end, responsibility
               FROM volumes ORDER BY edition_id, position, id""",
        )
        for volume in volumes:
            volume["publication_year"] = publication_year_display(
                volume["publication_year"], volume.pop("publication_year_end")
            )

        copies = _rows(
            connection,
            """SELECT id, volume_id, acquisition_date, location, reading_record
               FROM copies ORDER BY id""",
        )
        publishers = _rows(
            connection,
            "SELECT id, canonical_name FROM publishers ORDER BY id",
        )
        aliases: dict[int, list[str]] = {}
        for row in connection.execute(
            """SELECT publisher_id, alias FROM publisher_aliases
               ORDER BY publisher_id, id"""
        ):
            aliases.setdefault(row["publisher_id"], []).append(row["alias"])
        for publisher in publishers:
            publisher["aliases"] = aliases.get(publisher["id"], [])

        tags = _rows(
            connection,
            "SELECT id, name, parent_id FROM tags ORDER BY id",
        )
        return {
            "schema_version": JSON_SCHEMA_VERSION,
            "model": "Work-Edition-Volume-Copy",
            "works": works,
            "editions": editions,
            "volumes": volumes,
            "copies": copies,
            "publishers": publishers,
            "tags": tags,
        }
    finally:
        connection.close()


def export_records() -> list[dict]:
    tag_lookup = {work["id"]: work for work in list_works()}
    records = list_books()
    for record in records:
        work_id = next(iter(record["edition"].get("work_ids", [])), None)
        summary = tag_lookup.get(work_id, {})
        record["work"]["tag_names"] = [
            tag["name"] for tag in summary.get("tags", [])
        ]
    return records


@router.get("/api/export/json", include_in_schema=False)
def export_json() -> Response:
    content = json.dumps(export_document(), ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=book-catalog.json"},
    )


@router.get("/api/export/csv", include_in_schema=False)
def export_csv() -> Response:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for record in export_records():
        work = record["work"]
        edition = record["edition"]
        volume = record["volume"]
        copy_record = record["copy"]
        writer.writerow({
            "schema_version": CSV_SCHEMA_VERSION,
            "work_id": next(iter(edition.get("work_ids", [])), ""),
            "work_title": work["title"],
            "work_subtitle": work["subtitle"],
            "work_authors": work["authors"],
            "work_scripts": work["scripts"],
            "work_tag_ids": "; ".join(str(item) for item in work.get("tag_ids", [])),
            "work_tag_names": "; ".join(work.get("tag_names", [])),
            "edition_id": record["edition_id"],
            "edition_title": edition["title"],
            "edition_subtitle": edition["subtitle"],
            "edition_work_ids": "; ".join(
                str(work_id) for work_id in edition.get("work_ids", [])
            ),
            "edition_work_relations": json.dumps(
                edition.get("work_relations", []),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "edition_identifier": edition["identifier"],
            "edition_version": edition["version"],
            "edition_series": edition["series"],
            "edition_responsibility": edition["translator"],
            "edition_general_responsibility": edition["responsibility"],
            "edition_other_title": edition["other_title"],
            "edition_other_subtitle": edition["other_subtitle"],
            "edition_translated_title": edition["translated_title"],
            "edition_translated_subtitle": edition["translated_subtitle"],
            "edition_scripts": edition["edition_scripts"],
            "edition_publisher": edition["publisher"],
            "edition_publisher_canonical": edition["publisher_canonical"],
            "edition_publication_year": edition["publication_year"],
            "volume_id": volume["id"],
            "volume_position": volume["position"],
            "volume_number": volume["volume_number"],
            "volume_title": volume["volume_title"],
            "volume_identifier": volume["identifier"],
            "volume_version": volume["version"],
            "volume_publication_year": volume["publication_year"],
            "volume_responsibility": volume["responsibility"],
            "copy_id": record["id"],
            "copy_acquisition_date": copy_record["acquisition_date"],
            "copy_location": copy_record["location"],
            "copy_reading_record": copy_record["reading_record"],
        })
    return Response(
        content="﻿" + output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=book-catalog.csv"},
    )
