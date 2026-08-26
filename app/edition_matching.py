from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


EDITION_IDENTITY_FIELDS = (
    "title",
    "subtitle",
    "edition_scripts",
    "translator",
    "version",
    "series",
)


def _value(record: Any, name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(name)
    try:
        return record[name]
    except (KeyError, TypeError, IndexError):
        return getattr(record, name, None)


def _text(value: Any) -> str:
    return str(value or "").strip().casefold()


def publisher_identity(record: Any) -> tuple[str, Any]:
    publisher_id = _value(record, "publisher_id")
    if publisher_id is not None:
        return ("id", int(publisher_id))
    canonical = _text(_value(record, "publisher_canonical"))
    return ("name", canonical or _text(_value(record, "publisher")))


def edition_identity(record: Any) -> tuple[Any, ...]:
    return (
        *(_text(_value(record, field)) for field in EDITION_IDENTITY_FIELDS),
        publisher_identity(record),
    )


def editions_match(left: Any, right: Any) -> bool:
    """Pure identity comparison; identifier and publication year are not identity."""
    if bool(_value(left, "force_separate")) or bool(_value(right, "force_separate")):
        return False
    return edition_identity(left) == edition_identity(right)


def find_edition_candidates(
    candidates: Iterable[Any], edition: Any, *, exclude_id: int | None = None
) -> list[Any]:
    return [
        candidate
        for candidate in candidates
        if (exclude_id is None or _value(candidate, "id") != exclude_id)
        and editions_match(candidate, edition)
    ]


def detect_duplicate(
    candidates: Iterable[Any], edition: Any, *, exclude_id: int | None = None
) -> Any | None:
    matches = find_edition_candidates(
        candidates, edition, exclude_id=exclude_id
    )
    return matches[0] if matches else None
