from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .edition_matching import editions_match
from .repository import (
    create_book, get_book, get_work, list_publishers, list_works,
    normalize_publisher, update_book,
)
from .schemas import BookInput, PublisherNormalizationInput


router = APIRouter()
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000


class CsvImportSelection(BaseModel):
    row_number: int
    book: BookInput
    action: Literal["create", "replace"] = "create"
    target_copy_id: int | None = None
    target_row_number: int | None = None
    csv_fields: list[str] | None = None


class CsvImportCommit(BaseModel):
    rows: list[CsvImportSelection] = Field(max_length=MAX_ROWS)


def _text(row: dict[str, str | None], *keys: str) -> str:
    for key in keys:
        if key in row:
            return str(row.get(key) or "").strip()
    return ""


def _json_list(row: dict[str, str | None], *keys: str) -> list:
    raw = _text(row, *keys)
    return json.loads(raw) if raw else []


def _int_list(row: dict[str, str | None], *keys: str) -> list[int]:
    raw = _text(row, *keys)
    return [
        int(value.strip()) for value in raw.split(";") if value.strip()
    ]


def _book_from_row(row: dict[str, str | None]) -> BookInput:
    tag_names = _text(row, "work_tag_names", "tags")
    names_are_authoritative = (
        "work_tag_names" in row or "tags" in row
    )
    return BookInput.model_validate({
        "work": {
            "title": _text(row, "work_title", "title"),
            "subtitle": _text(row, "work_subtitle", "subtitle"),
            "authors": _text(row, "work_authors", "authors"),
            "scripts": _text(row, "work_scripts", "scripts"),
            # Names are portable across databases; numeric IDs are only a
            # fallback for older/same-database files without names.
            "tag_ids": (
                [] if names_are_authoritative
                else _int_list(row, "work_tag_ids")
            ),
            "tag_names": tag_names,
        },
        "edition": {
            "title": _text(row, "edition_title"),
            "subtitle": _text(row, "edition_subtitle"),
            "work_ids": _text(row, "edition_work_ids", "work_ids"),
            "work_relations": _json_list(row, "edition_work_relations", "work_relations"),
            "identifier": _text(row, "edition_identifier", "identifier"),
            "version": _text(row, "edition_version", "version"),
            "series": _text(row, "edition_series", "series"),
            "translator": _text(row, "edition_responsibility", "translator"),
            "responsibility": _text(row, "edition_general_responsibility"),
            "other_title": _text(row, "edition_other_title", "other_title"),
            "other_subtitle": _text(row, "edition_other_subtitle", "other_subtitle"),
            "translated_title": _text(row, "edition_translated_title", "translated_title"),
            "translated_subtitle": _text(row, "edition_translated_subtitle", "translated_subtitle"),
            "edition_scripts": _text(row, "edition_scripts", "translation_script"),
            "publisher": _text(row, "edition_publisher", "publisher"),
            "publisher_canonical": _text(row, "edition_publisher_canonical"),
            "publication_year": _text(row, "edition_publication_year", "publication_year") or None,
            "force_new_edition": _text(row, "edition_force_new", "force_new_edition").casefold()
                in {"1", "true", "yes", "y"},
        },
        "volume": {
            "position": int(_text(row, "volume_position"))
                if _text(row, "volume_position") else None,
            "volume_number": _text(row, "volume_number", "volume"),
            "volume_title": _text(row, "volume_title"),
            "identifier": _text(row, "volume_identifier", "copy_identifier"),
            "version": _text(row, "volume_version"),
            "publication_year": _text(row, "volume_publication_year") or None,
            "responsibility": _text(row, "volume_responsibility"),
        },
        "copy": {
            "acquisition_date": _text(row, "copy_acquisition_date", "acquisition_date") or None,
            "location": _text(row, "copy_location", "location"),
            "reading_record": _text(row, "copy_reading_record", "reading_record"),
        },
    })


CSV_V2_FIELD_PATHS = {
    "work_title": ("work", "title"),
    "work_subtitle": ("work", "subtitle"),
    "work_authors": ("work", "authors"),
    "work_scripts": ("work", "scripts"),
    "work_tag_ids": ("work", "tag_ids"),
    "work_tag_names": ("work", "tag_names"),
    "edition_title": ("edition", "title"),
    "edition_subtitle": ("edition", "subtitle"),
    "edition_work_ids": ("edition", "work_ids"),
    "edition_work_relations": ("edition", "work_relations"),
    "edition_identifier": ("edition", "identifier"),
    "edition_version": ("edition", "version"),
    "edition_series": ("edition", "series"),
    "edition_responsibility": ("edition", "translator"),
    "edition_general_responsibility": ("edition", "responsibility"),
    "edition_other_title": ("edition", "other_title"),
    "edition_other_subtitle": ("edition", "other_subtitle"),
    "edition_translated_title": ("edition", "translated_title"),
    "edition_translated_subtitle": ("edition", "translated_subtitle"),
    "edition_scripts": ("edition", "edition_scripts"),
    "edition_publisher": ("edition", "publisher"),
    "edition_publisher_canonical": ("edition", "publisher_canonical"),
    "edition_publication_year": ("edition", "publication_year"),
    "edition_force_new": ("edition", "force_new_edition"),
    "volume_position": ("volume", "position"),
    "volume_number": ("volume", "volume_number"),
    "volume_title": ("volume", "volume_title"),
    "volume_identifier": ("volume", "identifier"),
    "volume_version": ("volume", "version"),
    "volume_publication_year": ("volume", "publication_year"),
    "volume_responsibility": ("volume", "responsibility"),
    "copy_acquisition_date": ("copy", "acquisition_date"),
    "copy_location": ("copy", "location"),
    "copy_reading_record": ("copy", "reading_record"),
}

# Input-only compatibility for the old three-layer CSV. These names are never
# emitted by the v2 exporter; their deterministic targets make the layer
# transition explicit and keep legacy interpretation out of runtime schemas.
LEGACY_CSV_FIELD_PATHS = {
    "title": ("work", "title"),
    "subtitle": ("work", "subtitle"),
    "authors": ("work", "authors"),
    "scripts": ("work", "scripts"),
    "tags": ("work", "tag_names"),
    "work_ids": ("edition", "work_ids"),
    "work_relations": ("edition", "work_relations"),
    "identifier": ("edition", "identifier"),
    "version": ("edition", "version"),
    "series": ("edition", "series"),
    "translator": ("edition", "translator"),
    "other_title": ("edition", "other_title"),
    "other_subtitle": ("edition", "other_subtitle"),
    "translated_title": ("edition", "translated_title"),
    "translated_subtitle": ("edition", "translated_subtitle"),
    "translation_script": ("edition", "edition_scripts"),
    "publisher": ("edition", "publisher"),
    "publication_year": ("edition", "publication_year"),
    "force_new_edition": ("edition", "force_new_edition"),
    "volume": ("volume", "volume_number"),
    "copy_identifier": ("volume", "identifier"),
    "acquisition_date": ("copy", "acquisition_date"),
    "location": ("copy", "location"),
    "reading_record": ("copy", "reading_record"),
}

CSV_FIELD_PATHS = {**CSV_V2_FIELD_PATHS, **LEGACY_CSV_FIELD_PATHS}


def _merge_csv_overwrite(
    copy_id: int, incoming: BookInput, csv_fields: list[str]
) -> BookInput | None:
    current = get_book(copy_id)
    if current is None:
        return None
    incoming_data = incoming.model_dump(by_alias=True, mode="json")
    merged = {
        "work": dict(current["work"]),
        "edition": dict(current["edition"]),
        "volume": {key: current["volume"].get(key) for key in (
            "id", "position", "volume_number", "volume_title",
            "identifier", "version", "publication_year", "responsibility",
        )},
        "copy": {
            "volume_id": current["volume_id"],
            "acquisition_date": current["copy"]["acquisition_date"],
            "location": current["copy"]["location"],
            "reading_record": current["copy"]["reading_record"],
        },
    }
    paths = {CSV_FIELD_PATHS[field] for field in csv_fields if field in CSV_FIELD_PATHS}
    for csv_field in csv_fields:
        path = CSV_FIELD_PATHS.get(csv_field)
        if path is None:
            continue
        section, field = path
        merged[section][field] = incoming_data[section][field]
        if path == ("work", "tag_names"):
            merged["work"]["tag_ids"] = []
        elif path in {
            ("edition", "publisher"),
            ("edition", "publisher_canonical"),
        }:
            merged["edition"]["publisher_id"] = incoming_data["edition"]["publisher_id"]
    if ("edition", "work_ids") in paths and ("edition", "work_relations") not in paths:
        merged["edition"]["work_relations"] = []
    if ("edition", "work_relations") in paths and ("edition", "work_ids") not in paths:
        merged["edition"]["work_ids"] = []
    return BookInput.model_validate(merged)


def _key(value: object) -> str:
    return str(value or "").strip().casefold()


def _copy_key(copy_record: dict) -> tuple[str, str, str]:
    return (
        _key(copy_record.get("acquisition_date")),
        _key(copy_record.get("location")),
        _key(copy_record.get("reading_record")),
    )


def _catalog_candidates() -> list[dict]:
    candidates: list[dict] = []
    for summary in list_works():
        detail = get_work(summary["id"])
        if detail is None:
            continue
        for edition_group in detail["editions"]:
            for volume_group in edition_group["volumes"]:
                copies = volume_group["copies"] or [None]
                for copy_record in copies:
                    candidates.append({
                        "work_id": detail["id"], "work": detail["work"],
                        "edition_id": edition_group["id"],
                        "edition": edition_group["edition"],
                        "volume_id": volume_group["id"],
                        "volume": volume_group["volume"],
                        "copy": copy_record, "row_number": None,
                    })
    return candidates


def _unique(items: list[dict], field: str) -> list[dict]:
    output: list[dict] = []
    seen: set[object] = set()
    for item in items:
        value = item[field]
        key = value if value is not None else ("row", item["row_number"])
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def preview_csv(content: bytes) -> list[dict]:
    if len(content) > MAX_CSV_BYTES:
        raise ValueError("CSV file is larger than 5 MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV must use UTF-8 encoding") from error
    reader = csv.DictReader(StringIO(text, newline=""))
    fieldnames = reader.fieldnames or []
    if not fieldnames or not ("work_title" in fieldnames or "title" in fieldnames):
        raise ValueError("CSV is missing work_title/title")

    csv_fields = list(dict.fromkeys(
        field for field in fieldnames if field in CSV_FIELD_PATHS
    ))
    publisher_ids = {
        alias.strip().casefold(): publisher["id"]
        for publisher in list_publishers()
        for alias in publisher["aliases"]
    }
    candidates = _catalog_candidates()
    previews: list[dict] = []
    for index, row in enumerate(reader, start=2):
        if index > MAX_ROWS + 1:
            raise ValueError(f"CSV may contain at most {MAX_ROWS} rows")
        if not any(str(value or "").strip() for value in row.values()):
            continue
        raw_schema_version = _text(row, "schema_version")
        if raw_schema_version and raw_schema_version != "2":
            raise ValueError(
                f"CSV row {index}: unsupported schema_version "
                f"{raw_schema_version}; expected 2"
            )
        try:
            book = _book_from_row(row)
            if book.edition.publisher and book.edition.publisher_id is None:
                book.edition.publisher_id = publisher_ids.get(
                    book.edition.publisher.strip().casefold()
                )
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"CSV row {index}: {error}") from error

        work_matches = [
            item for item in candidates
            if _key(item["work"]["title"]) == _key(book.work.title)
            and _key(item["work"]["authors"]) == _key(book.work.authors)
        ]
        edition_matches = [
            item for item in work_matches
            if editions_match(item["edition"], book.edition)
        ]
        volume_matches = [
            item for item in edition_matches
            if _key(item["volume"]["volume_number"]) == _key(book.volume.volume_number)
            and _key(item["volume"]["volume_title"]) == _key(book.volume.volume_title)
        ]
        incoming_copy = book.copy_.model_dump(mode="json")
        copy_matches = [
            item for item in volume_matches
            if item["copy"] is not None
            and _copy_key(item["copy"]) == _copy_key(incoming_copy)
        ]

        previews.append({
            "row_number": index,
            "book": book.model_dump(by_alias=True, mode="json"),
            "csv_fields": csv_fields,
            "schema_version": _text(row, "schema_version") or "legacy",
            "work_candidates": [
                {
                    "id": item["work_id"] if item["work_id"] > 0 else None,
                    "row_number": item["row_number"],
                }
                for item in _unique(work_matches, "work_id")
            ],
            "edition_candidates": [
                {
                    "id": item["edition_id"] if item["edition_id"] > 0 else None,
                    "row_number": item["row_number"],
                }
                for item in _unique(edition_matches, "edition_id")
            ],
            "matching_volumes": [{
                "id": item["volume_id"] if item["volume_id"] > 0 else None,
                "row_number": item["row_number"],
                "volume_number": item["volume"]["volume_number"],
                "volume_title": item["volume"]["volume_title"],
            } for item in _unique(volume_matches, "volume_id")],
            "matching_copies": [{
                "id": item["copy"]["id"],
                "location": item["copy"]["location"],
                "row_number": item["row_number"],
            } for item in copy_matches],
            "matching_volume_copies": [{
                "id": item["copy"]["id"],
                "location": item["copy"]["location"],
                "row_number": item["row_number"],
            } for item in volume_matches if item["copy"] is not None],
            "matching_edition_copies": [{
                "id": item["copy"]["id"] if item["copy"] else None,
                "row_number": item["row_number"],
                "volume_number": item["volume"]["volume_number"],
                "volume_title": item["volume"]["volume_title"],
                "location": item["copy"]["location"] if item["copy"] else "",
            } for item in edition_matches],
        })
        # Negative IDs are preview-only structural identities. They let later
        # rows recognize one in-file Work/Edition/Volume without pretending
        # that a database record already exists.
        candidates.append({
            "work_id": (
                work_matches[0]["work_id"] if work_matches else -index
            ),
            "work": book.work.model_dump(mode="json"),
            "edition_id": (
                edition_matches[0]["edition_id"] if edition_matches else -index
            ),
            "edition": book.edition.model_dump(mode="json"),
            "volume_id": (
                volume_matches[0]["volume_id"] if volume_matches else -index
            ),
            "volume": book.volume.model_dump(mode="json"),
            "copy": {"id": None, **incoming_copy}, "row_number": index,
        })
    return previews


@router.post("/api/import/csv/preview", include_in_schema=False)
async def csv_preview(request: Request) -> dict:
    try:
        rows = preview_csv(await request.body())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"rows": rows}


def _prepare_publisher(book: BookInput) -> None:
    canonical = book.edition.publisher_canonical.strip()
    if not canonical:
        return
    aliases = [book.edition.publisher] if book.edition.publisher else []
    normalized = normalize_publisher(PublisherNormalizationInput(
        canonical_name=canonical, aliases=aliases,
    ))
    book.edition.publisher_id = normalized["id"]


@router.post("/api/import/csv", include_in_schema=False)
def csv_import(payload: CsvImportCommit) -> dict:
    created_ids: list[int] = []
    overwritten_ids: list[int] = []
    copy_by_row: dict[int, int] = {}
    for selection in payload.rows:
        _prepare_publisher(selection.book)
        if selection.action == "create":
            copy_id = create_book(selection.book)["id"]
            created_ids.append(copy_id)
        else:
            copy_id = selection.target_copy_id
            if copy_id is None and selection.target_row_number is not None:
                copy_id = copy_by_row.get(selection.target_row_number)
            if copy_id is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"CSV 第 {selection.row_number} 行未選擇實物副本",
                )
            book = selection.book
            if selection.csv_fields is not None:
                book = _merge_csv_overwrite(copy_id, book, selection.csv_fields)
            updated = book is not None and update_book(
                copy_id, book,
                overwrite_hierarchy=selection.csv_fields is not None,
            )
            if not updated:
                raise HTTPException(
                    status_code=422,
                    detail="指定的實物副本已不存在",
                )
            overwritten_ids.append(copy_id)
        copy_by_row[selection.row_number] = copy_id
    return {
        "imported": len(created_ids),
        "overwritten": len(overwritten_ids),
        "copy_ids": created_ids,
        "overwritten_copy_ids": overwritten_ids,
    }
