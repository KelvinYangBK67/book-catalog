from __future__ import annotations

import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .database import initialize
from .export import router as export_router
from .import_csv import router as import_router
from .import_json import router as import_json_router
from .repository import (
    create_book, create_books_batch, create_copy_for_volume, create_tag,
    create_volume_record, create_work_record, delete_copy, delete_edition, delete_publisher, delete_volume,
    delete_tag, delete_work, get_book, get_copy_details, get_edition, get_volume_detail, get_work, list_books, list_editions,
    list_publisher_names, list_publishers, list_tag_violations, list_tags, list_works, normalize_publisher,
    move_edition_identifier_to_volume, update_book, update_copy_details, update_edition_details,
    update_tag, update_volume_details, update_work_details,
)
from .schemas import (
    BookBatchInput, BookInput, BookRecord, CopyDetail, CopyInput, CopyUpdateInput,
    EditionDetail, EditionIdentifierMoveInput, EditionInput, EditionSummary,
    PublisherNormalizationInput, PublisherRecord, TagInput, TagRecord,
    VolumeDetail, VolumeInput, WorkDetail, WorkInput, WorkSummary,
)


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
IMPE_FONTS = Path(os.getenv("LIBRARY_FONT_ROOT", r"D:\Repositories\IMPE\assets\fonts"))
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/woff2", ".woff2")


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(title="紙質書管理系統", version="0.7.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(export_router)
app.include_router(import_router)
app.include_router(import_json_router)
if IMPE_FONTS.is_dir():
    app.mount("/fonts", StaticFiles(directory=IMPE_FONTS), name="fonts")


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    if not IMPE_FONTS.is_dir():
        html = html.replace('  <link rel="stylesheet" href="/static/fonts.css?v=1.0.5">\n', "")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/api/books", response_model=list[BookRecord])
def books(q: str = Query(default="", max_length=500)) -> list[dict]:
    return list_books(q)


@app.get("/api/works", response_model=list[WorkSummary])
def works(q: str = Query(default="", max_length=500)) -> list[dict]:
    return list_works(q)


@app.get("/api/editions", response_model=list[EditionSummary])
def editions(q: str = Query(default="", max_length=500)) -> list[dict]:
    return list_editions(q)


@app.post("/api/works", response_model=WorkDetail, status_code=status.HTTP_201_CREATED)
def add_work(payload: WorkInput) -> dict:
    try:
        return create_work_record(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/works/{work_id}", response_model=WorkDetail)
def work(work_id: int) -> dict:
    record = get_work(work_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此作品")
    return record


@app.put("/api/works/{work_id}", response_model=WorkDetail)
def edit_work(work_id: int, payload: WorkInput) -> dict:
    try:
        record = update_work_details(work_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此作品")
    return record


@app.delete("/api/works/{work_id}")
def remove_work(work_id: int) -> dict:
    if not delete_work(work_id):
        raise HTTPException(status_code=404, detail="找不到此作品")
    return {"deleted": True}


@app.get("/api/editions/{edition_id}", response_model=EditionDetail)
def edition(edition_id: int) -> dict:
    record = get_edition(edition_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此版本")
    return record


@app.put("/api/editions/{edition_id}", response_model=EditionDetail)
def edit_edition(edition_id: int, payload: EditionInput) -> dict:
    try:
        record = update_edition_details(edition_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此版本")
    detail = get_edition(edition_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="找不到此版本")
    return detail


@app.post(
    "/api/editions/{edition_id}/move-identifier-to-volume",
    response_model=EditionDetail,
)
def move_edition_identifier(
    edition_id: int, payload: EditionIdentifierMoveInput
) -> dict:
    try:
        record = move_edition_identifier_to_volume(
            edition_id, payload.volume_id
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此版本")
    return record


@app.delete("/api/editions/{edition_id}")
def remove_edition(edition_id: int) -> dict:
    result = delete_edition(edition_id)
    if result is None:
        raise HTTPException(status_code=404, detail="找不到此版本")
    return {"deleted": True, **result}


@app.get("/api/copies/{copy_id}", response_model=CopyDetail)
def copy(copy_id: int) -> dict:
    record = get_copy_details(copy_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此實物副本")
    return record


@app.put("/api/copies/{copy_id}", response_model=CopyDetail)
def edit_copy(copy_id: int, payload: CopyUpdateInput) -> dict:
    try:
        record = update_copy_details(copy_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此實物副本")
    return record


@app.post(
    "/api/editions/{edition_id}/volumes",
    response_model=VolumeDetail,
    status_code=status.HTTP_201_CREATED,
)
def add_volume(edition_id: int, payload: VolumeInput) -> dict:
    try:
        record = create_volume_record(edition_id, payload)
        detail = get_volume_detail(record["id"])
        assert detail is not None
        return detail
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/volumes/{volume_id}", response_model=VolumeDetail)
def volume(volume_id: int) -> dict:
    record = get_volume_detail(volume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此冊")
    return record


@app.put("/api/volumes/{volume_id}", response_model=VolumeDetail)
def edit_volume(volume_id: int, payload: VolumeInput) -> dict:
    try:
        updated = update_volume_details(volume_id, payload)
        record = get_volume_detail(volume_id) if updated is not None else None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此冊")
    return record




@app.delete("/api/volumes/{volume_id}")
def remove_volume(volume_id: int) -> dict:
    try:
        result = delete_volume(volume_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="找不到此冊")
    return {"deleted": True, **result}


@app.post(
    "/api/volumes/{volume_id}/copies",
    response_model=CopyDetail,
    status_code=status.HTTP_201_CREATED,
)
def add_volume_copy(volume_id: int, payload: CopyInput) -> dict:
    try:
        return create_copy_for_volume(volume_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/api/copies/{copy_id}")
def remove_copy(copy_id: int) -> dict:
    result = delete_copy(copy_id)
    if result is None:
        raise HTTPException(status_code=404, detail="找不到此實物副本")
    return {"deleted": True, **result}


@app.get("/api/tags", response_model=list[TagRecord])
def tags() -> list[dict]:
    return list_tags()


@app.get("/api/tags/violations")
def tag_violations() -> list[dict]:
    return list_tag_violations()


@app.post("/api/tags", response_model=TagRecord, status_code=status.HTTP_201_CREATED)
def add_tag(payload: TagInput) -> dict:
    try:
        return create_tag(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.put("/api/tags/{tag_id}", response_model=TagRecord)
def edit_tag(tag_id: int, payload: TagInput) -> dict:
    try:
        record = update_tag(tag_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此標籤")
    return record


@app.delete("/api/tags/{tag_id}")
def remove_tag(tag_id: int) -> dict:
    result = delete_tag(tag_id)
    if result is None:
        raise HTTPException(status_code=404, detail="找不到此標籤")
    return {"deleted": True, **result}


@app.get("/api/publishers", response_model=list[PublisherRecord])
def publishers() -> list[dict]:
    return list_publishers()


@app.get("/api/publishers/names", response_model=list[str])
def publisher_names() -> list[str]:
    return list_publisher_names()


@app.post("/api/publishers/normalize", response_model=PublisherRecord)
def normalize_publisher_name(payload: PublisherNormalizationInput) -> dict:
    return normalize_publisher(payload)


@app.delete("/api/publishers/{publisher_id}")
def remove_publisher(publisher_id: int) -> dict:
    if not delete_publisher(publisher_id):
        raise HTTPException(status_code=404, detail="找不到此出版社正規型")
    return {"deleted": True}


@app.get("/api/books/{copy_id}", response_model=BookRecord)
def book(copy_id: int) -> dict:
    record = get_book(copy_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此藏書")
    return record


@app.post("/api/books", response_model=BookRecord, status_code=status.HTTP_201_CREATED)
def add_book(payload: BookInput) -> dict:
    try:
        return create_book(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/books/batch", response_model=list[BookRecord], status_code=status.HTTP_201_CREATED)
def add_books_batch(payload: BookBatchInput) -> list[dict]:
    try:
        return create_books_batch(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.put("/api/books/{copy_id}", response_model=BookRecord)
def edit_book(copy_id: int, payload: BookInput) -> dict:
    try:
        record = update_book(copy_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此藏書")
    return record
