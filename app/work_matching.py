from __future__ import annotations

from collections.abc import Iterable, Mapping
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


def work_identity(record: Any) -> tuple[str, str]:
    return (_text(_value(record, "title")), _text(_value(record, "authors")))


def works_match_exactly(left: Any, right: Any) -> bool:
    return work_identity(left) == work_identity(right)


def find_work_candidates(candidates: Iterable[Any], work: Any) -> list[Any]:
    """Return exact identity candidates without mutating or merging them."""
    identity = work_identity(work)
    return [candidate for candidate in candidates if work_identity(candidate) == identity]


def detect_duplicate(candidates: Iterable[Any], work: Any) -> Any | None:
    matches = find_work_candidates(candidates, work)
    return matches[0] if matches else None
