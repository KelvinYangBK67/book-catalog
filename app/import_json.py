from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import transaction
from .export import JSON_SCHEMA_VERSION
from .repository import publication_year_bounds


router = APIRouter()


class JsonImportDocument(BaseModel):
    schema_version: int
    model: str = "Work-Edition-Volume-Copy"
    works: list[dict[str, Any]]
    editions: list[dict[str, Any]]
    volumes: list[dict[str, Any]]
    copies: list[dict[str, Any]]
    publishers: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[dict[str, Any]] = Field(default_factory=list)


def import_json_document(
    document: dict[str, Any] | JsonImportDocument,
    path: Path | None = None,
) -> dict[str, Any]:
    payload = (
        document if isinstance(document, JsonImportDocument)
        else JsonImportDocument.model_validate(document)
    )
    if payload.schema_version != JSON_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported JSON schema_version {payload.schema_version}; "
            f"expected {JSON_SCHEMA_VERSION}"
        )

    with transaction(path) as connection:
        publisher_map: dict[int, int] = {}
        for publisher in payload.publishers:
            canonical = str(publisher.get("canonical_name") or "").strip()
            if not canonical:
                raise ValueError("Publisher canonical_name cannot be empty")
            existing = connection.execute(
                """SELECT id FROM publishers
                   WHERE canonical_name = ? COLLATE NOCASE""",
                (canonical,),
            ).fetchone()
            if existing:
                publisher_id = int(existing["id"])
            else:
                publisher_id = int(connection.execute(
                    "INSERT INTO publishers (canonical_name) VALUES (?)",
                    (canonical,),
                ).lastrowid)
            publisher_map[int(publisher["id"])] = publisher_id
            for alias in publisher.get("aliases", []):
                alias = str(alias or "").strip()
                if not alias:
                    continue
                conflict = connection.execute(
                    """SELECT publisher_id FROM publisher_aliases
                       WHERE alias = ? COLLATE NOCASE""",
                    (alias,),
                ).fetchone()
                if conflict and int(conflict["publisher_id"]) != publisher_id:
                    raise ValueError(
                        f"Publisher alias {alias!r} belongs to another publisher"
                    )
                connection.execute(
                    """INSERT OR IGNORE INTO publisher_aliases
                           (publisher_id, alias) VALUES (?, ?)""",
                    (publisher_id, alias),
                )

        tag_map: dict[int, int] = {}
        pending = list(payload.tags)
        while pending:
            progress = False
            for tag in list(pending):
                old_parent = tag.get("parent_id")
                if old_parent is not None and int(old_parent) not in tag_map:
                    continue
                parent_id = tag_map.get(int(old_parent)) if old_parent is not None else None
                name = str(tag.get("name") or "").strip()
                if not name:
                    raise ValueError("Tag name cannot be empty")
                existing = connection.execute(
                    """SELECT id FROM tags WHERE name = ? COLLATE NOCASE
                       AND parent_id IS ?""",
                    (name, parent_id),
                ).fetchone()
                tag_id = (
                    int(existing["id"]) if existing
                    else int(connection.execute(
                        "INSERT INTO tags (name, parent_id) VALUES (?, ?)",
                        (name, parent_id),
                    ).lastrowid)
                )
                tag_map[int(tag["id"])] = tag_id
                pending.remove(tag)
                progress = True
            if not progress:
                raise ValueError("Tag hierarchy has missing parents or a cycle")

        work_map: dict[int, int] = {}
        for work in payload.works:
            work_id = int(connection.execute(
                """INSERT INTO works (title, subtitle, authors, scripts)
                   VALUES (?, ?, ?, ?)""",
                (
                    str(work.get("title") or "").strip(),
                    str(work.get("subtitle") or "").strip(),
                    str(work.get("authors") or "").strip(),
                    str(work.get("scripts") or "").strip(),
                ),
            ).lastrowid)
            work_map[int(work["id"])] = work_id
            for old_tag_id in work.get("tag_ids", []):
                if int(old_tag_id) not in tag_map:
                    raise ValueError("作品引用了不存在的標籤")
                connection.execute(
                    "INSERT OR IGNORE INTO work_tags (work_id, tag_id) VALUES (?, ?)",
                    (work_id, tag_map[int(old_tag_id)]),
                )

        edition_map: dict[int, int] = {}
        for edition in payload.editions:
            old_primary = int(edition["primary_work_id"])
            if old_primary not in work_map:
                raise ValueError("版本引用了不存在的主要作品")
            year_start, year_end = publication_year_bounds(
                edition.get("publication_year")
            )
            old_publisher_id = edition.get("publisher_id")
            publisher_id = (
                publisher_map.get(int(old_publisher_id))
                if old_publisher_id is not None else None
            )
            edition_id = int(connection.execute(
                """INSERT INTO editions
                       (title, subtitle, identifier, translator, responsibility,
                        other_title, other_subtitle, translated_title,
                        translated_subtitle, edition_scripts, version, series,
                        publisher, publisher_id, publication_year,
                        publication_year_end, force_separate)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(edition.get("title") or ""),
                    str(edition.get("subtitle") or ""),
                    str(edition.get("identifier") or ""),
                    str(edition.get("translator") or ""),
                    str(edition.get("responsibility") or ""),
                    str(edition.get("other_title") or ""),
                    str(edition.get("other_subtitle") or ""),
                    str(edition.get("translated_title") or ""),
                    str(edition.get("translated_subtitle") or ""),
                    str(edition.get("edition_scripts") or ""),
                    str(edition.get("version") or ""),
                    str(edition.get("series") or ""),
                    str(edition.get("publisher") or ""),
                    publisher_id, year_start, year_end,
                    int(bool(edition.get("force_separate"))),
                ),
            ).lastrowid)
            edition_map[int(edition["id"])] = edition_id

        volume_map: dict[int, int] = {}
        for volume in payload.volumes:
            old_edition_id = int(volume["edition_id"])
            if old_edition_id not in edition_map:
                raise ValueError("冊引用了不存在的版本")
            year_start, year_end = publication_year_bounds(
                volume.get("publication_year")
            )
            volume_id = int(connection.execute(
                """INSERT INTO volumes
                       (edition_id, position, volume_number, volume_title,
                        identifier, version, publication_year,
                        publication_year_end, responsibility)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    edition_map[old_edition_id], int(volume.get("position", 0)),
                    str(volume.get("volume_number") or ""),
                    str(volume.get("volume_title") or ""),
                    str(volume.get("identifier") or ""),
                    str(volume.get("version") or ""),
                    year_start, year_end,
                    str(volume.get("responsibility") or ""),
                ),
            ).lastrowid)
            volume_map[int(volume["id"])] = volume_id

        for edition in payload.editions:
            edition_id = edition_map[int(edition["id"])]
            relations = list(edition.get("work_relations") or [])
            if not relations:
                relations = [{
                    "work_id": edition["primary_work_id"],
                    "position": 0,
                    "relation_type": "contained",
                    "volume_id": None,
                }]
            for position, relation in enumerate(relations):
                old_work_id = int(relation["work_id"])
                if old_work_id not in work_map:
                    raise ValueError("版本關聯引用了不存在的作品")
                relation_type = str(relation.get("relation_type") or "contained")
                old_volume_id = relation.get("volume_id")
                volume_id = (
                    volume_map.get(int(old_volume_id))
                    if old_volume_id is not None else None
                )
                if relation_type == "volume" and volume_id is None:
                    raise ValueError("分冊關聯引用了不存在的冊")
                connection.execute(
                    """INSERT INTO edition_works
                           (edition_id, work_id, position, relation_type, volume_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        edition_id, work_map[old_work_id],
                        int(relation.get("position", position)),
                        relation_type,
                        volume_id if relation_type == "volume" else None,
                    ),
                )

        copy_map: dict[int, int] = {}
        for copy_record in payload.copies:
            old_volume_id = int(copy_record["volume_id"])
            if old_volume_id not in volume_map:
                raise ValueError("實物副本引用了不存在的冊")
            copy_id = int(connection.execute(
                """INSERT INTO copies
                       (volume_id, acquisition_date, location, reading_record)
                   VALUES (?, ?, ?, ?)""",
                (
                    volume_map[old_volume_id],
                    copy_record.get("acquisition_date"),
                    str(copy_record.get("location") or ""),
                    str(copy_record.get("reading_record") or ""),
                ),
            ).lastrowid)
            copy_map[int(copy_record["id"])] = copy_id

    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "imported": {
            "works": len(work_map),
            "editions": len(edition_map),
            "volumes": len(volume_map),
            "copies": len(copy_map),
            "publishers": len(publisher_map),
            "tags": len(tag_map),
        },
    }


@router.post("/api/import/json", include_in_schema=False)
def json_import(payload: JsonImportDocument) -> dict[str, Any]:
    try:
        return import_json_document(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
