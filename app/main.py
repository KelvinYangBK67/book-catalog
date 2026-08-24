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
from .repository import (
    create_book, create_tag, delete_copy, delete_edition, delete_publisher,
    delete_tag, delete_work, get_book, get_work, list_books,
    list_publisher_names, list_publishers, list_tags, list_works, normalize_publisher,
    update_book, update_copy_details,
    update_edition_details, update_tag, update_work_details,
)
from .schemas import (
    BookInput, BookRecord, CopyInput, EditionInput,
    PublisherNormalizationInput, PublisherRecord, TagInput, TagRecord,
    WorkDetail, WorkInput, WorkSummary,
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


app = FastAPI(title="紙質書管理系統", version="0.5.2", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(export_router)
app.include_router(import_router)
if IMPE_FONTS.is_dir():
    app.mount("/fonts", StaticFiles(directory=IMPE_FONTS), name="fonts")


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace('v=0.5.3', 'v=0.9.1').replace('app.js?v=0.5.1', 'app.js?v=0.9.1')
    if not IMPE_FONTS.is_dir():
        html = html.replace('  <link rel="stylesheet" href="/static/fonts.css?v=0.5.3">\n', "")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/api/books", response_model=list[BookRecord])
def books(q: str = Query(default="", max_length=500)) -> list[dict]:
    return list_books(q)


@app.get("/api/works", response_model=list[WorkSummary])
def works(q: str = Query(default="", max_length=500)) -> list[dict]:
    return list_works(q)


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


@app.put("/api/editions/{edition_id}", response_model=WorkDetail)
def edit_edition(edition_id: int, payload: EditionInput) -> dict:
    try:
        record = update_edition_details(edition_id, payload)
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


@app.put("/api/copies/{copy_id}", response_model=BookRecord)
def edit_copy(copy_id: int, payload: CopyInput) -> dict:
    record = update_copy_details(copy_id, payload)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此實物冊")
    return record


@app.delete("/api/copies/{copy_id}")
def remove_copy(copy_id: int) -> dict:
    result = delete_copy(copy_id)
    if result is None:
        raise HTTPException(status_code=404, detail="找不到此實物冊")
    return {"deleted": True, **result}


@app.get("/api/tags", response_model=list[TagRecord])
def tags() -> list[dict]:
    return list_tags()


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


@app.put("/api/books/{copy_id}", response_model=BookRecord)
def edit_book(copy_id: int, payload: BookInput) -> dict:
    try:
        record = update_book(copy_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if record is None:
        raise HTTPException(status_code=404, detail="找不到此藏書")
    return record
