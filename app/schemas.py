from __future__ import annotations

from datetime import date
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_semicolon_text(value: object) -> object:
    if not isinstance(value, str):
        return value
    for separator in ('；', '、', '，'):
        value = value.replace(separator, ';')
    return '; '.join(part.strip() for part in value.split(';') if part.strip())


def normalize_semicolon_slots(value: object) -> object:
    if not isinstance(value, str):
        return value
    for separator in ('；', '、', '，'):
        value = value.replace(separator, ';')
    return '; '.join(part.strip() for part in value.split(';'))


def normalize_version_text(value: object) -> object:
    normalized = normalize_semicolon_text(value)
    if not isinstance(normalized, str):
        return normalized
    return '; '.join(
        f'第{part}版' if part.isdecimal() else part
        for part in normalized.split('; ')
    )


def normalize_identifier_text(value: object) -> object:
    normalized = normalize_semicolon_text(value)
    if not isinstance(normalized, str) or not normalized:
        return normalized
    choices: dict[str, tuple[int, int, str]] = {}
    order: list[str] = []
    priorities = {'hbk': 3, 'pbk': 2, 'ebook': 1}
    for position, raw_part in enumerate(normalized.split('; ')):
        part = raw_part.strip()
        # Normalization may run more than once (for example after an import
        # followed by an edit). Generic labels must not accumulate.
        part = re.sub(r'^(?:識別號\s*[:：]?\s*)+', '', part).strip()
        qualifier_match = re.search(
            r'\s*\((hbk|pbk|ebook)\.?\)\s*$', part, flags=re.IGNORECASE
        )
        qualifier = qualifier_match.group(1).lower() if qualifier_match else ''
        if qualifier_match:
            part = part[:qualifier_match.start()].strip()
        explicit = re.match(r'^(ISBN|ISSN)\s*[:：]?\s*(.+)$', part, flags=re.IGNORECASE)
        if explicit:
            kind = explicit.group(1).upper()
            content = explicit.group(2).strip()
        elif re.match(r'^(?:97[89][\d\s-]*|\d[\d\s-]{8,}[\dXx])(?:\b|/)', part):
            kind, content = 'ISBN', part
        elif re.match(r'^(?:統一書號|统一书号|書號|书号)\s*[:：]?\s*', part):
            match = re.match(
                r'^(統一書號|统一书号|書號|书号)\s*[:：]?\s*(.*)$', part
            )
            assert match is not None
            kind, content = match.group(1), match.group(2).strip()
        else:
            label = re.match(r'^([A-Za-z][A-Za-z0-9_-]*)\s*[:：]?\s+(.+)$', part)
            if label:
                kind, content = label.group(1).upper(), label.group(2).strip()
            else:
                kind, content = '識別號', part
        rendered = f'{kind} {content}'
        if kind not in choices:
            order.append(kind)
            choices[kind] = (priorities.get(qualifier, 0), position, rendered)
        elif priorities.get(qualifier, 0) > choices[kind][0]:
            choices[kind] = (priorities.get(qualifier, 0), position, rendered)
    return '; '.join(choices[kind][2] for kind in order)


class CleanModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class WorkInput(CleanModel):
    title: str = Field(min_length=1, max_length=500)
    subtitle: str = Field(default="", max_length=500)
    authors: str = Field(default="", max_length=1000)
    scripts: str = Field(default="", max_length=500)
    tag_ids: list[int] = Field(default_factory=list)
    tag_names: list[str] = Field(default_factory=list)

    @field_validator('authors', 'scripts', mode='before')
    @classmethod
    def normalize_lists(cls, value: object) -> object:
        return normalize_semicolon_text(value)

    @field_validator('tag_names', mode='before')
    @classmethod
    def normalize_tag_names(cls, value: object) -> object:
        raw_items = [value] if isinstance(value, str) else (value or [])
        return [
            part.strip()
            for item in raw_items
            for part in str(normalize_semicolon_text(str(item))).split(';')
            if part.strip()
        ]


class EditionInput(CleanModel):
    identifier: str = Field(default="", max_length=1000)
    translator: str = Field(default="", max_length=500)
    other_title: str = Field(default="", max_length=1000)
    other_subtitle: str = Field(default="", max_length=1000)
    translated_title: str = Field(default="", max_length=500)
    translated_subtitle: str = Field(default="", max_length=500)
    edition_scripts: str = Field(default="", max_length=500)
    version: str = Field(default="", max_length=200)
    publisher: str = Field(default="", max_length=500)
    publisher_id: int | None = None
    publisher_canonical: str = ""
    publication_year: int | None = Field(default=None, ge=0, le=9999)
    series: str = Field(default='', max_length=500)

    @model_validator(mode='before')
    @classmethod
    def normalize_paired_titles(cls, value: object) -> object:
        if isinstance(value, dict):
            value = dict(value)
            for field in ('other_title', 'other_subtitle'):
                if field in value:
                    value[field] = normalize_semicolon_slots(value[field])
        return value

    @field_validator('translator', 'edition_scripts', 'series', mode='before')
    @classmethod
    def normalize_lists(cls, value: object) -> object:
        return normalize_semicolon_text(value)

    @field_validator('identifier', mode='before')
    @classmethod
    def normalize_identifiers(cls, value: object) -> object:
        return normalize_identifier_text(value)

    @field_validator('version', mode='before')
    @classmethod
    def normalize_versions(cls, value: object) -> object:
        return normalize_version_text(value)

    @field_validator("publication_year", mode="before")
    @classmethod
    def empty_year_is_none(cls, value: object) -> object:
        return None if value in (None, "") else value


class CopyInput(CleanModel):
    volume: str = Field(default="", max_length=100)
    acquisition_date: date | None = None
    location: str = Field(default="", max_length=500)
    reading_record: str = Field(default="", max_length=5000)

    @field_validator("acquisition_date", mode="before")
    @classmethod
    def empty_date_is_none(cls, value: object) -> object:
        return None if value in (None, "") else value


class BookInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    work: WorkInput
    edition: EditionInput
    copy_: CopyInput = Field(alias="copy")


class BookBatchInput(BaseModel):
    work: WorkInput
    edition: EditionInput
    copy_: CopyInput = Field(alias="copy")
    volumes: list[str] = Field(min_length=1, max_length=500)

    @field_validator("volumes", mode="before")
    @classmethod
    def normalize_volumes(cls, value: object) -> object:
        if isinstance(value, str):
            value = normalize_semicolon_text(value).split("; ")
        return [str(item).strip() for item in (value or []) if str(item).strip()]


class BookRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    work: WorkInput
    edition: EditionInput
    copy_: CopyInput = Field(alias="copy")


class CopySummary(BaseModel):
    id: int
    volume: str
    location: str


class EditionGroup(BaseModel):
    id: int
    edition: EditionInput
    copies: list[CopySummary]


class TagInput(CleanModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = None


class TagRecord(BaseModel):
    id: int
    name: str
    parent_id: int | None
    path: str
    has_children: bool = False
    assigned_work_count: int = 0


class PublisherNormalizationInput(CleanModel):
    canonical_name: str = Field(min_length=1, max_length=500)
    aliases: list[str] = Field(default_factory=list)


class PublisherRecord(BaseModel):
    id: int
    canonical_name: str
    aliases: list[str]


class WorkSummary(BaseModel):
    id: int
    title: str
    subtitle: str
    authors: str
    scripts: str
    edition_count: int
    copy_count: int
    tags: list[TagRecord]
    publishers: list[str]
    locations: list[str]
    years: list[int]
    effective_scripts: list[str]


class WorkDetail(BaseModel):
    id: int
    work: WorkInput
    editions: list[EditionGroup]
