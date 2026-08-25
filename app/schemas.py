from __future__ import annotations

from datetime import date
import re
from typing import Literal

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
    groups: dict[str, list[tuple[int, int, str, bool]]] = {}
    order: list[str] = []
    priorities = {'hbk': 3, 'pbk': 2, 'ebook': 1}
    for position, raw_part in enumerate(normalized.split('; ')):
        part = raw_part.strip()
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
        if kind not in groups:
            order.append(kind)
            groups[kind] = []
        groups[kind].append((
            priorities.get(qualifier, 0), position, rendered, bool(qualifier)
        ))

    output: list[str] = []
    seen: set[str] = set()
    for kind in order:
        items = groups[kind]
        qualified = [item for item in items if item[3]]
        selected = [max(qualified, key=lambda item: (item[0], -item[1]))] if qualified else items
        for _, _, rendered, _ in selected:
            key = rendered.casefold()
            if key not in seen:
                seen.add(key)
                output.append(rendered)
    return '; '.join(output)



class CleanModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class WorkEditionRelation(CleanModel):
    edition_id: int
    relation_type: Literal["volume", "contained"] = "contained"
    volume_number: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def volume_number_only_applies_to_volumes(self) -> "WorkEditionRelation":
        if self.relation_type == "contained":
            self.volume_number = ""
        return self


class WorkInput(CleanModel):
    title: str = Field(min_length=1, max_length=500)
    subtitle: str = Field(default="", max_length=500)
    authors: str = Field(default="", max_length=1000)
    scripts: str = Field(default="", max_length=500)
    tag_ids: list[int] = Field(default_factory=list)
    tag_names: list[str] = Field(default_factory=list)
    edition_relations: list[WorkEditionRelation] | None = Field(default=None, max_length=200)

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


class EditionWorkRelation(CleanModel):
    work_id: int
    relation_type: Literal["volume", "contained"] = "contained"
    volume_number: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def volume_number_only_applies_to_volumes(self) -> "EditionWorkRelation":
        if self.relation_type == "contained":
            self.volume_number = ""
        return self


class EditionInput(CleanModel):
    title: str = Field(default="", max_length=500)
    subtitle: str = Field(default="", max_length=500)
    work_ids: list[int] = Field(default_factory=list, max_length=200)
    work_relations: list[EditionWorkRelation] = Field(default_factory=list, max_length=200)
    existing_edition_id: int | None = None
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
    publication_year: int | str | None = None
    series: str = Field(default='', max_length=500)
    force_new_edition: bool = False

    @field_validator("work_ids", mode="before")
    @classmethod
    def normalize_work_ids(cls, value: object) -> object:
        if isinstance(value, str):
            value = normalize_semicolon_text(value).split("; ")
        return list(dict.fromkeys(int(item) for item in (value or []) if str(item).strip()))

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
        if value in (None, ""):
            return None
        text = str(value).strip().replace("\u2014", "\u2013").replace("-", "\u2013")
        parts = text.split("\u2013")
        if len(parts) not in {1, 2} or not all(part.isdigit() for part in parts):
            raise ValueError("\u51fa\u7248\u5e74\u4efd\u61c9\u70ba\u5e74\u4efd\u6216\u5e74\u4efd\u7bc4\u570d\uff0c\u4f8b\u5982 2002\u20132003")
        years = [int(part) for part in parts]
        if any(year < 0 or year > 9999 for year in years) or years != sorted(years):
            raise ValueError("\u51fa\u7248\u5e74\u4efd\u7bc4\u570d\u7121\u6548")
        return years[0] if len(years) == 1 or years[0] == years[1] else f"{years[0]}\u2013{years[1]}"


class CopyInput(CleanModel):
    volume_number: str = Field(default="", max_length=100)
    volume_title: str = Field(default="", max_length=500)
    identifier: str = Field(default="", max_length=1000)
    effective_identifier: str = ""
    identifier_transition: Literal["keep", "demote"] | None = None
    acquisition_date: date | None = None
    location: str = Field(default="", max_length=500)
    reading_record: str = Field(default="", max_length=5000)


    @model_validator(mode="before")
    @classmethod
    def accept_legacy_volume(cls, value: object) -> object:
        if isinstance(value, dict) and "volume_number" not in value and "volume" in value:
            value = dict(value)
            value["volume_number"] = value["volume"]
        return value

    @field_validator("identifier", mode="before")
    @classmethod
    def normalize_identifiers(cls, value: object) -> object:
        return normalize_identifier_text(value)

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
    volume_numbers: list[str] = Field(min_length=1, max_length=500)
    volume_titles: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_volumes(cls, value: object) -> object:
        if isinstance(value, dict) and "volume_numbers" not in value and "volumes" in value:
            value = dict(value)
            value["volume_numbers"] = value["volumes"]
        return value

    @field_validator("volume_numbers", mode="before")
    @classmethod
    def normalize_volume_numbers(cls, value: object) -> object:
        if isinstance(value, str):
            value = normalize_semicolon_text(value).split("; ")
        return [str(item).strip() for item in (value or []) if str(item).strip()]

    @field_validator("volume_titles", mode="before")
    @classmethod
    def normalize_volume_titles(cls, value: object) -> object:
        if isinstance(value, str):
            value = normalize_semicolon_slots(value).split("; ")
        return [str(item).strip() for item in (value or [])]


class BookRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    edition_id: int
    work: WorkInput
    edition: EditionInput
    copy_: CopyInput = Field(alias="copy")


class CopySummary(BaseModel):
    id: int
    volume_number: str
    volume_title: str
    identifier: str
    effective_identifier: str
    location: str


class EditionGroup(BaseModel):
    id: int
    edition: EditionInput
    copies: list[CopySummary]


class EditionSummary(BaseModel):
    id: int
    title: str
    subtitle: str
    translated_title: str
    translated_subtitle: str
    identifier: str
    publisher: str
    publisher_canonical: str
    publication_year: int | str | None
    version: str
    series: str
    edition_scripts: str
    work_ids: list[int]
    work_relations: list[EditionWorkRelation]
    copy_count: int


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
    years: list[int | str]
    effective_scripts: list[str]


class WorkDetail(BaseModel):
    id: int
    work: WorkInput
    editions: list[EditionGroup]
