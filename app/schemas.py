from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CleanModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class WorkInput(CleanModel):
    title: str = Field(min_length=1, max_length=500)
    subtitle: str = Field(default="", max_length=500)
    authors: str = Field(default="", max_length=1000)
    scripts: str = Field(default="", max_length=500)
    tag_ids: list[int] = Field(default_factory=list)
    tag_names: list[str] = Field(default_factory=list)


class EditionInput(CleanModel):
    identifier: str = Field(default="", max_length=1000)
    translator: str = Field(default="", max_length=500)
    other_title: str = Field(default="", max_length=1000)
    translated_title: str = Field(default="", max_length=500)
    translated_subtitle: str = Field(default="", max_length=500)
    translation_script: str = Field(default="", max_length=500)
    version: str = Field(default="", max_length=200)
    publisher: str = Field(default="", max_length=500)
    publisher_id: int | None = None
    publisher_canonical: str = ""
    publication_year: int | None = Field(default=None, ge=0, le=9999)

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


class PublisherAliasInput(CleanModel):
    alias: str = Field(min_length=1, max_length=500)


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


class WorkDetail(BaseModel):
    id: int
    work: WorkInput
    editions: list[EditionGroup]
