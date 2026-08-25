from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _value(record: Any, name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(name)
    try:
        return record[name]
    except (KeyError, TypeError, IndexError):
        return getattr(record, name, None)


def _text(value: Any) -> str:
    return str(value or "").strip().casefold()


def identifier_parts(record: Any) -> set[str]:
    return {
        _text(part)
        for part in str(_value(record, "identifier") or "").split(";")
        if _text(part)
    }


def publisher_identity(record: Any) -> tuple[str, Any]:
    publisher_id = _value(record, "publisher_id")
    if publisher_id is not None:
        return ("id", int(publisher_id))
    canonical = _text(_value(record, "publisher_canonical"))
    return ("name", canonical or _text(_value(record, "publisher")))


def editions_match(left: Any, right: Any) -> bool:
    left_identifiers = identifier_parts(left)
    right_identifiers = identifier_parts(right)
    if left_identifiers and right_identifiers:
        return bool(left_identifiers & right_identifiers)
    return (
        _text(_value(left, "title")) == _text(_value(right, "title"))
        and _text(_value(left, "subtitle")) == _text(_value(right, "subtitle"))
        and _text(_value(left, "version")) == _text(_value(right, "version"))
        and publisher_identity(left) == publisher_identity(right)
        and _value(left, "publication_year") == _value(right, "publication_year")
        and _text(_value(left, "series")) == _text(_value(right, "series"))
    )


def find_matching_edition(
    candidates: list[Any], edition: Any, *, exclude_id: int | None = None
) -> Any | None:
    for candidate in candidates:
        if exclude_id is not None and _value(candidate, "id") == exclude_id:
            continue
        if editions_match(candidate, edition):
            return candidate
    return None
