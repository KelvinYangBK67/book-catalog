from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal


MetadataSource = Literal["work", "edition", "volume"]

OVERRIDE_FIELDS = (
    "title", "subtitle", "scripts", "identifier", "version", "publication_year",
)
APPEND_FIELDS = ("responsibility",)


@dataclass(frozen=True)
class ResolvedValue:
    value: Any
    source: MetadataSource | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResponsibilityPart:
    value: str
    source: MetadataSource

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedAppendValue:
    value: str
    sources: tuple[ResponsibilityPart, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "sources": [source.as_dict() for source in self.sources],
        }


def _value(record: Any, name: str) -> Any:
    if record is None:
        return None
    if isinstance(record, Mapping):
        return record.get(name)
    try:
        return record[name]
    except (KeyError, TypeError, IndexError):
        return getattr(record, name, None)


def _present(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _year_value(record: Any) -> Any:
    start = _value(record, "publication_year")
    end = _value(record, "publication_year_end")
    if not _present(start):
        return None
    if _present(end) and str(end) != str(start):
        return f"{start}\u2013{end}"
    return start


def resolve_override(
    candidates: tuple[tuple[MetadataSource, Any], ...]
) -> ResolvedValue:
    for source, value in candidates:
        if _present(value):
            return ResolvedValue(value=value, source=source)
    return ResolvedValue(value=None, source=None)


def _semicolon_parts(value: Any) -> list[str]:
    return [
        part.strip()
        for part in str(value or "").split(";")
        if part.strip()
    ]


def resolve_append(
    candidates: tuple[tuple[MetadataSource, Any], ...]
) -> ResolvedAppendValue:
    parts: list[str] = []
    sources: list[ResponsibilityPart] = []
    seen: set[str] = set()
    for source, raw in candidates:
        source_parts: list[str] = []
        for part in _semicolon_parts(raw):
            key = part.casefold()
            if key in seen:
                continue
            seen.add(key)
            parts.append(part)
            source_parts.append(part)
        if source_parts:
            sources.append(
                ResponsibilityPart(value="; ".join(source_parts), source=source)
            )
    return ResolvedAppendValue(value="; ".join(parts), sources=tuple(sources))


def resolve_metadata(work: Any, edition: Any, volume: Any) -> dict[str, Any]:
    """Resolve effective bibliographic metadata without mutating any input."""
    title = resolve_override((
        ("volume", _value(volume, "volume_title")),
        ("edition", _value(edition, "title")),
        ("edition", _value(edition, "translated_title")),
        ("work", _value(work, "title")),
    ))
    subtitle = resolve_override((
        ("edition", _value(edition, "subtitle")),
        ("edition", _value(edition, "translated_subtitle")),
        ("work", _value(work, "subtitle")),
    ))
    scripts = resolve_override((
        ("volume", _value(volume, "scripts")),
        ("edition", _value(edition, "edition_scripts")),
        ("work", _value(work, "scripts")),
    ))
    identifier = resolve_override((
        ("volume", _value(volume, "identifier")),
        ("edition", _value(edition, "identifier")),
    ))
    version = resolve_override((
        ("volume", _value(volume, "version")),
        ("edition", _value(edition, "version")),
    ))
    publication_year = resolve_override((
        ("volume", _year_value(volume)),
        ("edition", _year_value(edition)),
    ))
    responsibility = resolve_append((
        ("work", _value(work, "authors")),
        ("edition", _value(edition, "translator")),
        ("volume", _value(volume, "responsibility")),
    ))
    return {
        "title": title.as_dict(),
        "subtitle": subtitle.as_dict(),
        "scripts": scripts.as_dict(),
        "identifier": identifier.as_dict(),
        "version": version.as_dict(),
        "publication_year": publication_year.as_dict(),
        "responsibility": responsibility.as_dict(),
    }
