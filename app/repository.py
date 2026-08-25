from __future__ import annotations

from pathlib import Path
import re
from sqlite3 import Connection, Row

from .database import connect, initialize, transaction
from .edition_matching import find_matching_edition
from .schemas import (
    BookBatchInput, BookInput, CopyInput, EditionInput,
    PublisherNormalizationInput, TagInput, WorkInput,
)


def natural_volume_key(value: str) -> tuple[object, ...]:
    text = str(value or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)*", text):
        return (0, *(int(part) for part in text.split(".")))
    return (1, text.casefold())


SELECT_BOOK = """
SELECT
    c.id AS copy_id, c.volume, c.acquisition_date, c.location, c.reading_record,
    e.id AS edition_id, e.identifier, e.translator, e.other_title, e.other_subtitle, e.translated_title,
    e.translated_subtitle, e.edition_scripts, e.version, e.series, e.publisher,
    e.publisher_id, COALESCE(p.canonical_name, '') AS publisher_canonical,
    e.publication_year,
    w.id AS work_id, w.title, w.subtitle, w.authors, w.scripts,
    (SELECT GROUP_CONCAT(wt.tag_id) FROM work_tags wt WHERE wt.work_id = w.id) AS tag_ids_csv
FROM copies c
JOIN editions e ON e.id = c.edition_id
JOIN works w ON w.id = e.work_id
LEFT JOIN publishers p ON p.id = e.publisher_id
"""


def _book_record(row: Row) -> dict:
    return {
        "id": row["copy_id"],
        "work": {
            "title": row["title"], "subtitle": row["subtitle"],
            "authors": row["authors"], "scripts": row["scripts"],
            "tag_ids": [int(value) for value in (row["tag_ids_csv"] or "").split(",") if value],
            "tag_names": [],
        },
        "edition": {
            "identifier": row["identifier"],
            "translator": row["translator"],
            "other_title": row["other_title"],
            "other_subtitle": row["other_subtitle"],
            "translated_title": row["translated_title"],
            "translated_subtitle": row["translated_subtitle"],
            "edition_scripts": row["edition_scripts"],
            "version": row["version"],
            "series": row["series"],
            "publisher": row["publisher"],
            "publisher_id": row["publisher_id"],
            "publisher_canonical": row["publisher_canonical"],
            "publication_year": row["publication_year"],
        },
        "copy": {
            "volume": row["volume"],
            "acquisition_date": row["acquisition_date"],
            "location": row["location"],
            "reading_record": row["reading_record"],
        },
    }


def _set_work_tags(
    connection: Connection, work_id: int, tag_ids: list[int], tag_names: list[str], replace: bool
) -> None:
    resolved_ids = list(tag_ids)
    for raw_name in tag_names:
        name = raw_name.strip()
        if not name:
            continue
        row = connection.execute(
            """SELECT id FROM tags WHERE name = ? COLLATE NOCASE
               ORDER BY CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END, id LIMIT 1""",
            (name,),
        ).fetchone()
        if row:
            resolved_ids.append(row["id"])
        else:
            cursor = connection.execute("INSERT INTO tags (name, parent_id) VALUES (?, NULL)", (name,))
            resolved_ids.append(int(cursor.lastrowid))
    unique_ids = sorted(set(resolved_ids))
    if unique_ids:
        placeholders = ",".join("?" for _ in unique_ids)
        found = connection.execute(
            f"SELECT COUNT(*) FROM tags WHERE id IN ({placeholders})", unique_ids
        ).fetchone()[0]
        if found != len(unique_ids):
            raise ValueError("包含不存在的標籤")
        non_leaf = connection.execute(
            f"""SELECT t.name FROM tags t WHERE t.id IN ({placeholders})
                AND EXISTS (SELECT 1 FROM tags child WHERE child.parent_id = t.id)
                ORDER BY t.name LIMIT 1""",
            unique_ids,
        ).fetchone()
        if non_leaf:
            raise ValueError(
                f"標籤「{non_leaf['name']}」已有下級分類，只能將作品掛在葉節點標籤上"
            )
    if replace:
        connection.execute("DELETE FROM work_tags WHERE work_id = ?", (work_id,))
    connection.executemany(
        "INSERT OR IGNORE INTO work_tags (work_id, tag_id) VALUES (?, ?)",
        [(work_id, tag_id) for tag_id in unique_ids],
    )


def _find_or_create_work(connection: Connection, work: WorkInput, replace_tags: bool = False) -> int:
    row = connection.execute(
        """SELECT id FROM works
           WHERE title = ? COLLATE NOCASE AND authors = ? COLLATE NOCASE
           ORDER BY id LIMIT 1""",
        (work.title, work.authors),
    ).fetchone()
    if row:
        connection.execute(
            """UPDATE works SET
                   subtitle = CASE WHEN subtitle = '' THEN ? ELSE subtitle END,
                   scripts = CASE WHEN scripts = '' THEN ? ELSE scripts END
               WHERE id = ?""",
            (work.subtitle, work.scripts, row["id"]),
        )
        _set_work_tags(connection, row["id"], work.tag_ids, work.tag_names, replace_tags)
        return row["id"]
    cursor = connection.execute(
        "INSERT INTO works (title, subtitle, authors, scripts) VALUES (?, ?, ?, ?)",
        (work.title, work.subtitle, work.authors, work.scripts),
    )
    work_id = int(cursor.lastrowid)
    _set_work_tags(connection, work_id, work.tag_ids, work.tag_names, True)
    return work_id


def _resolve_publisher(connection: Connection, raw_name: str, publisher_id: int | None) -> int | None:
    name = raw_name.strip()
    if publisher_id is not None:
        exists = connection.execute("SELECT id FROM publishers WHERE id = ?", (publisher_id,)).fetchone()
        if not exists:
            raise ValueError("出版社實體不存在")
        if name:
            connection.execute(
                "INSERT OR IGNORE INTO publisher_aliases (publisher_id, alias) VALUES (?, ?)",
                (publisher_id, name),
            )
        return publisher_id
    if not name:
        return None
    alias = connection.execute(
        "SELECT publisher_id FROM publisher_aliases WHERE alias = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if alias:
        return alias["publisher_id"]
    return None


def _find_or_create_edition(connection: Connection, work_id: int, edition: EditionInput) -> int:
    publisher_id = _resolve_publisher(connection, edition.publisher, edition.publisher_id)
    values = (
        work_id, edition.identifier, edition.translator, edition.other_title, edition.other_subtitle,
        edition.translated_title, edition.translated_subtitle, edition.edition_scripts,
        edition.version, edition.series, edition.publisher, publisher_id, edition.publication_year,
    )
    candidate = dict(edition.model_dump())
    candidate["publisher_id"] = publisher_id
    rows = connection.execute(
        """SELECT e.*, COALESCE(p.canonical_name, '') AS publisher_canonical
           FROM editions e LEFT JOIN publishers p ON p.id = e.publisher_id
           WHERE e.work_id = ? ORDER BY e.id""",
        (work_id,),
    ).fetchall()
    row = find_matching_edition(rows, candidate)
    if row:
        connection.execute(
            """UPDATE editions SET
                   identifier = CASE WHEN identifier = '' THEN ? ELSE identifier END,
                   translator = CASE WHEN translator = '' THEN ? ELSE translator END,
                   other_title = CASE WHEN other_title = '' THEN ? ELSE other_title END,
                   other_subtitle = CASE WHEN other_subtitle = '' THEN ? ELSE other_subtitle END,
                   translated_title = CASE WHEN translated_title = '' THEN ? ELSE translated_title END,
                   translated_subtitle = CASE WHEN translated_subtitle = '' THEN ? ELSE translated_subtitle END,
                   edition_scripts = CASE WHEN edition_scripts = '' THEN ? ELSE edition_scripts END,
                   series = CASE WHEN series = '' THEN ? ELSE series END,
                   publisher = CASE WHEN publisher = '' THEN ? ELSE publisher END,
                   publisher_id = COALESCE(publisher_id, ?),
                   publication_year = COALESCE(publication_year, ?)
               WHERE id = ?""",
            (
                edition.identifier, edition.translator, edition.other_title, edition.other_subtitle,
                edition.translated_title, edition.translated_subtitle, edition.edition_scripts,
                edition.series, edition.publisher, publisher_id, edition.publication_year, row["id"],
            ),
        )
        return row["id"]
    cursor = connection.execute(
        """INSERT INTO editions
           (work_id, identifier, translator, other_title, other_subtitle, translated_title, translated_subtitle,
            edition_scripts, version, series, publisher, publisher_id, publication_year)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        values,
    )
    return int(cursor.lastrowid)


def _cleanup_orphans(connection: Connection, edition_id: int, work_id: int) -> None:
    connection.execute(
        "DELETE FROM editions WHERE id = ? AND NOT EXISTS (SELECT 1 FROM copies WHERE edition_id = ?)",
        (edition_id, edition_id),
    )
    connection.execute(
        "DELETE FROM works WHERE id = ? AND NOT EXISTS (SELECT 1 FROM editions WHERE work_id = ?)",
        (work_id, work_id),
    )


def create_book(book: BookInput, path: Path | None = None) -> dict:
    with transaction(path) as connection:
        work_id = _find_or_create_work(connection, book.work)
        edition_id = _find_or_create_edition(connection, work_id, book.edition)
        cursor = connection.execute(
            "INSERT INTO copies (edition_id, volume, acquisition_date, location, reading_record) VALUES (?, ?, ?, ?, ?)",
            (
                edition_id,
                book.copy_.volume,
                book.copy_.acquisition_date.isoformat() if book.copy_.acquisition_date else None,
                book.copy_.location,
                book.copy_.reading_record,
            ),
        )
        copy_id = int(cursor.lastrowid)
    record = get_book(copy_id, path)
    assert record is not None
    return record


def create_books_batch(batch: BookBatchInput, path: Path | None = None) -> list[dict]:
    copy_ids: list[int] = []
    with transaction(path) as connection:
        work_id = _find_or_create_work(connection, batch.work)
        edition_id = _find_or_create_edition(connection, work_id, batch.edition)
        for volume in dict.fromkeys(batch.volumes):
            cursor = connection.execute(
                "INSERT INTO copies (edition_id, volume, acquisition_date, location, reading_record) VALUES (?, ?, ?, ?, ?)",
                (
                    edition_id, volume,
                    batch.copy_.acquisition_date.isoformat() if batch.copy_.acquisition_date else None,
                    batch.copy_.location, batch.copy_.reading_record,
                ),
            )
            copy_ids.append(int(cursor.lastrowid))
    return [
        record for copy_id in copy_ids
        if (record := get_book(copy_id, path)) is not None
    ]


def get_book(copy_id: int, path: Path | None = None) -> dict | None:
    connection = connect(path)
    try:
        row = connection.execute(SELECT_BOOK + " WHERE c.id = ?", (copy_id,)).fetchone()
        return _book_record(row) if row else None
    finally:
        connection.close()


def list_books(query: str = "", path: Path | None = None) -> list[dict]:
    connection = connect(path)
    try:
        sql = SELECT_BOOK
        parameters: tuple[str, ...] = ()
        if query.strip():
            pattern = f"%{query.strip()}%"
            sql += """
                WHERE w.title LIKE ? COLLATE NOCASE OR w.authors LIKE ? COLLATE NOCASE
                   OR w.subtitle LIKE ? COLLATE NOCASE OR w.scripts LIKE ? COLLATE NOCASE
                   OR e.identifier LIKE ? COLLATE NOCASE OR e.series LIKE ? COLLATE NOCASE
                   OR e.other_title LIKE ? COLLATE NOCASE
                   OR e.other_subtitle LIKE ? COLLATE NOCASE OR e.edition_scripts LIKE ? COLLATE NOCASE
                   OR e.translated_title LIKE ? COLLATE NOCASE
                   OR e.translated_subtitle LIKE ? COLLATE NOCASE
                   OR e.translator LIKE ? COLLATE NOCASE OR e.version LIKE ? COLLATE NOCASE
                   OR e.publisher LIKE ? COLLATE NOCASE
                   OR CAST(e.publication_year AS TEXT) LIKE ? COLLATE NOCASE
                   OR p.canonical_name LIKE ? COLLATE NOCASE
                   OR EXISTS (SELECT 1 FROM publisher_aliases pa
                              WHERE pa.publisher_id = e.publisher_id AND pa.alias LIKE ? COLLATE NOCASE)
                   OR c.volume LIKE ? COLLATE NOCASE OR c.acquisition_date LIKE ? COLLATE NOCASE
                   OR c.location LIKE ? COLLATE NOCASE OR c.reading_record LIKE ? COLLATE NOCASE
                   OR EXISTS (SELECT 1 FROM work_tags wt JOIN tags t ON t.id = wt.tag_id
                              WHERE wt.work_id = w.id AND t.name LIKE ? COLLATE NOCASE)
            """
            parameters = (pattern,) * 22
        sql += " ORDER BY w.title COLLATE NOCASE, e.publication_year IS NULL, e.publication_year, e.id, c.id"
        return [_book_record(row) for row in connection.execute(sql, parameters).fetchall()]
    finally:
        connection.close()


def list_works(query: str = "", path: Path | None = None) -> list[dict]:
    connection = connect(path)
    try:
        sql = """
            SELECT w.id, w.title, w.subtitle, w.authors, w.scripts,
                   COUNT(DISTINCT e.id) AS edition_count,
                   COUNT(DISTINCT c.id) AS copy_count
            FROM works w
            JOIN editions e ON e.work_id = w.id
            JOIN copies c ON c.edition_id = e.id
        """
        parameters: tuple[str, ...] = ()
        if query.strip():
            pattern = f"%{query.strip()}%"
            sql += """
                WHERE w.title LIKE ? COLLATE NOCASE OR w.authors LIKE ? COLLATE NOCASE
                   OR w.subtitle LIKE ? COLLATE NOCASE OR w.scripts LIKE ? COLLATE NOCASE
                   OR e.identifier LIKE ? COLLATE NOCASE OR e.series LIKE ? COLLATE NOCASE
                   OR e.other_title LIKE ? COLLATE NOCASE
                   OR e.other_subtitle LIKE ? COLLATE NOCASE OR e.edition_scripts LIKE ? COLLATE NOCASE
                   OR e.translated_title LIKE ? COLLATE NOCASE
                   OR e.translated_subtitle LIKE ? COLLATE NOCASE
                   OR e.translator LIKE ? COLLATE NOCASE OR e.version LIKE ? COLLATE NOCASE
                   OR e.publisher LIKE ? COLLATE NOCASE
                   OR CAST(e.publication_year AS TEXT) LIKE ? COLLATE NOCASE
                   OR EXISTS (SELECT 1 FROM publishers p WHERE p.id = e.publisher_id
                              AND p.canonical_name LIKE ? COLLATE NOCASE)
                   OR EXISTS (SELECT 1 FROM publisher_aliases pa
                              WHERE pa.publisher_id = e.publisher_id AND pa.alias LIKE ? COLLATE NOCASE)
                   OR c.volume LIKE ? COLLATE NOCASE OR c.acquisition_date LIKE ? COLLATE NOCASE
                   OR c.location LIKE ? COLLATE NOCASE OR c.reading_record LIKE ? COLLATE NOCASE
                   OR EXISTS (SELECT 1 FROM work_tags wt JOIN tags t ON t.id = wt.tag_id
                              WHERE wt.work_id = w.id AND t.name LIKE ? COLLATE NOCASE)
            """
            parameters = (pattern,) * 22
        sql += " GROUP BY w.id, w.title, w.subtitle, w.authors, w.scripts ORDER BY w.title COLLATE NOCASE, w.id"
        records = [dict(row) for row in connection.execute(sql, parameters).fetchall()]
        for record in records:
            record["tags"] = _tags_for_work(connection, record["id"])
            record["publishers"] = [row[0] for row in connection.execute(
                """SELECT DISTINCT COALESCE(p.canonical_name, e.publisher) AS value
                   FROM editions e LEFT JOIN publishers p ON p.id = e.publisher_id
                   WHERE e.work_id = ? AND COALESCE(p.canonical_name, e.publisher) <> '' ORDER BY value""",
                (record["id"],),
            ).fetchall()]
            record["locations"] = [row[0] for row in connection.execute(
                """SELECT DISTINCT c.location FROM copies c JOIN editions e ON e.id = c.edition_id
                   WHERE e.work_id = ? AND c.location <> '' ORDER BY c.location""",
                (record["id"],),
            ).fetchall()]
            record["years"] = [row[0] for row in connection.execute(
                "SELECT DISTINCT publication_year FROM editions WHERE work_id = ? AND publication_year IS NOT NULL ORDER BY publication_year",
                (record["id"],),
            ).fetchall()]
            script_values: list[str] = []
            for row in connection.execute(
                "SELECT CASE WHEN TRIM(edition_scripts) <> '' THEN edition_scripts ELSE ? END FROM editions WHERE work_id = ? ORDER BY id",
                (record["scripts"], record["id"]),
            ).fetchall():
                for value in str(row[0] or "").split(";"):
                    value = value.strip()
                    if value and value not in script_values:
                        script_values.append(value)
            record["effective_scripts"] = script_values
        return records
    finally:
        connection.close()


def get_work(work_id: int, path: Path | None = None) -> dict | None:
    connection = connect(path)
    try:
        work = connection.execute(
            "SELECT id, title, subtitle, authors, scripts FROM works WHERE id = ?", (work_id,)
        ).fetchone()
        if not work:
            return None
        rows = connection.execute(
            """SELECT e.id AS edition_id, e.identifier, e.translator, e.other_title, e.other_subtitle,
                      e.translated_title, e.translated_subtitle, e.edition_scripts,
                      e.version, e.series, e.publisher, e.publisher_id,
                      COALESCE(p.canonical_name, '') AS publisher_canonical,
                      e.publication_year, c.id AS copy_id, c.volume, c.location
               FROM editions e JOIN copies c ON c.edition_id = e.id
               LEFT JOIN publishers p ON p.id = e.publisher_id
               WHERE e.work_id = ?
               ORDER BY e.publication_year IS NULL, e.publication_year, e.id, c.id""",
            (work_id,),
        ).fetchall()
        editions: list[dict] = []
        by_id: dict[int, dict] = {}
        for row in rows:
            edition_id = row["edition_id"]
            if edition_id not in by_id:
                group = {
                    "id": edition_id,
                    "edition": {
                        "identifier": row["identifier"], "translator": row["translator"],
                        "other_title": row["other_title"],
                        "other_subtitle": row["other_subtitle"],
                        "translated_title": row["translated_title"],
                        "translated_subtitle": row["translated_subtitle"],
                        "edition_scripts": row["edition_scripts"],
                        "version": row["version"], "series": row["series"],
                        "publisher": row["publisher"],
                        "publisher_id": row["publisher_id"],
                        "publisher_canonical": row["publisher_canonical"],
                        "publication_year": row["publication_year"],
                    },
                    "copies": [],
                }
                by_id[edition_id] = group
                editions.append(group)
            by_id[edition_id]["copies"].append({
                "id": row["copy_id"], "volume": row["volume"], "location": row["location"],
            })
        for group in editions:
            group["copies"].sort(
                key=lambda copy: (natural_volume_key(copy["volume"]), copy["id"])
            )
        return {
            "id": work["id"],
            "work": {
                "title": work["title"], "subtitle": work["subtitle"],
                "authors": work["authors"], "scripts": work["scripts"],
                "tag_ids": [tag["id"] for tag in _tags_for_work(connection, work_id)],
                "tag_names": [],
            },
            "editions": editions,
        }
    finally:
        connection.close()


def update_book(copy_id: int, book: BookInput, path: Path | None = None) -> dict | None:
    with transaction(path) as connection:
        old = connection.execute(
            """SELECT c.edition_id, e.work_id FROM copies c
               JOIN editions e ON e.id = c.edition_id WHERE c.id = ?""",
            (copy_id,),
        ).fetchone()
        if not old:
            return None
        work_id = _find_or_create_work(connection, book.work, replace_tags=True)
        edition_id = _find_or_create_edition(connection, work_id, book.edition)
        connection.execute(
            """UPDATE copies SET edition_id = ?, volume = ?, acquisition_date = ?, location = ?,
               reading_record = ? WHERE id = ?""",
            (
                edition_id,
                book.copy_.volume,
                book.copy_.acquisition_date.isoformat() if book.copy_.acquisition_date else None,
                book.copy_.location, book.copy_.reading_record, copy_id,
            ),
        )
        _cleanup_orphans(connection, old["edition_id"], old["work_id"])
    return get_book(copy_id, path)


def update_work_details(work_id: int, work: WorkInput, path: Path | None = None) -> dict | None:
    merged = False
    result_id = work_id
    with transaction(path) as connection:
        exists = connection.execute("SELECT id FROM works WHERE id = ?", (work_id,)).fetchone()
        if not exists:
            return None
        duplicate = connection.execute(
            """SELECT id FROM works WHERE id <> ? AND title = ? COLLATE NOCASE
               AND authors = ? COLLATE NOCASE ORDER BY id LIMIT 1""",
            (work_id, work.title, work.authors),
        ).fetchone()
        if duplicate:
            result_id = duplicate["id"]
            connection.execute(
                "UPDATE editions SET work_id = ? WHERE work_id = ?", (result_id, work_id)
            )
            _set_work_tags(connection, result_id, work.tag_ids, work.tag_names, False)
            connection.execute("DELETE FROM works WHERE id = ?", (work_id,))
            merged = True
        else:
            connection.execute(
                "UPDATE works SET title = ?, subtitle = ?, authors = ?, scripts = ? WHERE id = ?",
                (work.title, work.subtitle, work.authors, work.scripts, work_id),
            )
            _set_work_tags(connection, work_id, work.tag_ids, work.tag_names, True)
    if merged:
        initialize(path)
    return get_work(result_id, path)


def update_edition_details(
    edition_id: int, edition: EditionInput, path: Path | None = None
) -> dict | None:
    with transaction(path) as connection:
        current = connection.execute(
            "SELECT work_id FROM editions WHERE id = ?", (edition_id,)
        ).fetchone()
        if not current:
            return None
        publisher_id = _resolve_publisher(connection, edition.publisher, edition.publisher_id)
        connection.execute(
            """UPDATE editions SET identifier = ?, translator = ?, other_title = ?, other_subtitle = ?,
               translated_title = ?, translated_subtitle = ?, edition_scripts = ?, version = ?, series = ?,
               publisher = ?, publisher_id = ?, publication_year = ? WHERE id = ?""",
            (
                edition.identifier, edition.translator, edition.other_title, edition.other_subtitle,
                edition.translated_title, edition.translated_subtitle,
                edition.edition_scripts, edition.version, edition.series, edition.publisher,
                publisher_id, edition.publication_year, edition_id,
            ),
        )
        candidate = dict(edition.model_dump())
        candidate["publisher_id"] = publisher_id
        rows = connection.execute(
            """SELECT e.*, COALESCE(p.canonical_name, '') AS publisher_canonical
               FROM editions e LEFT JOIN publishers p ON p.id = e.publisher_id
               WHERE e.work_id = ? ORDER BY e.id""",
            (current["work_id"],),
        ).fetchall()
        duplicate = find_matching_edition(rows, candidate, exclude_id=edition_id)
        if duplicate:
            connection.execute(
                "UPDATE copies SET edition_id = ? WHERE edition_id = ?",
                (duplicate["id"], edition_id),
            )
            connection.execute("DELETE FROM editions WHERE id = ?", (edition_id,))
    return get_work(current["work_id"], path)


def update_copy_details(copy_id: int, copy: CopyInput, path: Path | None = None) -> dict | None:
    with transaction(path) as connection:
        cursor = connection.execute(
            """UPDATE copies SET volume = ?, acquisition_date = ?, location = ?,
               reading_record = ? WHERE id = ?""",
            (
                copy.volume,
                copy.acquisition_date.isoformat() if copy.acquisition_date else None,
                copy.location, copy.reading_record, copy_id,
            ),
        )
        if cursor.rowcount == 0:
            return None
    return get_book(copy_id, path)


def delete_work(work_id: int, path: Path | None = None) -> bool:
    with transaction(path) as connection:
        cursor = connection.execute("DELETE FROM works WHERE id = ?", (work_id,))
        return cursor.rowcount > 0


def delete_edition(edition_id: int, path: Path | None = None) -> dict | None:
    with transaction(path) as connection:
        current = connection.execute(
            "SELECT work_id FROM editions WHERE id = ?", (edition_id,)
        ).fetchone()
        if not current:
            return None
        work_id = current["work_id"]
        connection.execute("DELETE FROM editions WHERE id = ?", (edition_id,))
        work_deleted = connection.execute(
            """DELETE FROM works WHERE id = ?
               AND NOT EXISTS (SELECT 1 FROM editions WHERE work_id = ?)""",
            (work_id, work_id),
        ).rowcount > 0
        return {"work_id": work_id, "work_deleted": work_deleted}


def delete_copy(copy_id: int, path: Path | None = None) -> dict | None:
    with transaction(path) as connection:
        current = connection.execute(
            """SELECT c.edition_id, e.work_id FROM copies c
               JOIN editions e ON e.id = c.edition_id WHERE c.id = ?""",
            (copy_id,),
        ).fetchone()
        if not current:
            return None
        edition_id = current["edition_id"]
        work_id = current["work_id"]
        connection.execute("DELETE FROM copies WHERE id = ?", (copy_id,))
        edition_deleted = connection.execute(
            """DELETE FROM editions WHERE id = ?
               AND NOT EXISTS (SELECT 1 FROM copies WHERE edition_id = ?)""",
            (edition_id, edition_id),
        ).rowcount > 0
        work_deleted = connection.execute(
            """DELETE FROM works WHERE id = ?
               AND NOT EXISTS (SELECT 1 FROM editions WHERE work_id = ?)""",
            (work_id, work_id),
        ).rowcount > 0
        return {
            "work_id": work_id,
            "edition_id": edition_id,
            "edition_deleted": edition_deleted,
            "work_deleted": work_deleted,
        }


def list_tags(path: Path | None = None) -> list[dict]:
    connection = connect(path)
    try:
        return list_tags_from_connection(connection)
    finally:
        connection.close()


def _tags_for_work(connection: Connection, work_id: int) -> list[dict]:
    assigned = {
        row["tag_id"] for row in connection.execute(
            "SELECT tag_id FROM work_tags WHERE work_id = ?", (work_id,)
        ).fetchall()
    }
    return [tag for tag in list_tags_from_connection(connection) if tag["id"] in assigned]


def list_tags_from_connection(connection: Connection) -> list[dict]:
    rows = connection.execute("SELECT id, name, parent_id FROM tags ORDER BY id").fetchall()
    by_id = {row["id"]: row for row in rows}

    def path_for(row: Row) -> str:
        names = [row["name"]]
        parent_id = row["parent_id"]
        visited = {row["id"]}
        while parent_id is not None and parent_id in by_id and parent_id not in visited:
            visited.add(parent_id)
            parent = by_id[parent_id]
            names.append(parent["name"])
            parent_id = parent["parent_id"]
        return " → ".join(reversed(names))

    return sorted(
        [{
            "id": row["id"], "name": row["name"], "parent_id": row["parent_id"],
            "path": path_for(row),
            "has_children": connection.execute(
                "SELECT 1 FROM tags WHERE parent_id = ? LIMIT 1", (row["id"],)
            ).fetchone() is not None,
            "assigned_work_count": connection.execute(
                "SELECT COUNT(*) FROM work_tags WHERE tag_id = ?", (row["id"],)
            ).fetchone()[0],
        } for row in rows],
        key=lambda item: (item["path"].casefold(), item["id"]),
    )


def create_tag(tag: TagInput, path: Path | None = None) -> dict:
    with transaction(path) as connection:
        if tag.parent_id is not None:
            parent = connection.execute("SELECT id FROM tags WHERE id = ?", (tag.parent_id,)).fetchone()
            if not parent:
                raise ValueError("上級標籤不存在")
            if connection.execute(
                "SELECT 1 FROM work_tags WHERE tag_id = ? LIMIT 1", (tag.parent_id,)
            ).fetchone():
                raise ValueError("此標籤已有藏書，請先重新分類後再建立下級標籤。")
        existing = connection.execute(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE AND parent_id IS ?",
            (tag.name, tag.parent_id),
        ).fetchone()
        if existing:
            raise ValueError("同一上級下已有同名標籤")
        cursor = connection.execute(
            "INSERT INTO tags (name, parent_id) VALUES (?, ?)",
            (tag.name, tag.parent_id),
        )
        tag_id = int(cursor.lastrowid)
        return next(record for record in list_tags_from_connection(connection) if record["id"] == tag_id)


def update_tag(tag_id: int, tag: TagInput, path: Path | None = None) -> dict | None:
    with transaction(path) as connection:
        exists = connection.execute("SELECT id FROM tags WHERE id = ?", (tag_id,)).fetchone()
        if not exists:
            return None
        if tag.parent_id == tag_id:
            raise ValueError("標籤不能以自己作為上級")
        if tag.parent_id is not None and connection.execute(
            "SELECT 1 FROM work_tags WHERE tag_id = ? LIMIT 1", (tag.parent_id,)
        ).fetchone():
            raise ValueError("此標籤已有藏書，請先重新分類後再建立下級標籤。")
        parent_id = tag.parent_id
        visited = {tag_id}
        while parent_id is not None:
            if parent_id in visited:
                raise ValueError("標籤層級不能形成循環")
            visited.add(parent_id)
            parent = connection.execute(
                "SELECT parent_id FROM tags WHERE id = ?", (parent_id,)
            ).fetchone()
            if not parent:
                raise ValueError("上級標籤不存在")
            parent_id = parent["parent_id"]
        duplicate = connection.execute(
            """SELECT id FROM tags WHERE id <> ? AND name = ? COLLATE NOCASE
               AND parent_id IS ?""",
            (tag_id, tag.name, tag.parent_id),
        ).fetchone()
        if duplicate:
            raise ValueError("同一上級下已有同名標籤")
        connection.execute(
            "UPDATE tags SET name = ?, parent_id = ? WHERE id = ?",
            (tag.name, tag.parent_id, tag_id),
        )
        return next(record for record in list_tags_from_connection(connection) if record["id"] == tag_id)


def list_tag_violations(path: Path | None = None) -> list[dict]:
    connection = connect(path)
    try:
        tags = {item["id"]: item for item in list_tags_from_connection(connection)}
        rows = connection.execute(
            """SELECT wt.work_id, w.title, wt.tag_id FROM work_tags wt
               JOIN works w ON w.id = wt.work_id
               WHERE EXISTS (SELECT 1 FROM tags child WHERE child.parent_id = wt.tag_id)
               ORDER BY w.title COLLATE NOCASE, wt.work_id"""
        ).fetchall()
        return [{
            "work_id": row["work_id"], "work_title": row["title"],
            "tag_id": row["tag_id"], "tag_path": tags[row["tag_id"]]["path"],
        } for row in rows]
    finally:
        connection.close()


def delete_tag(tag_id: int, path: Path | None = None) -> dict | None:
    with transaction(path) as connection:
        exists = connection.execute(
            "SELECT id FROM tags WHERE id = ?", (tag_id,)
        ).fetchone()
        if not exists:
            return None
        rows = connection.execute(
            """WITH RECURSIVE descendants(id, depth) AS (
                   SELECT id, 0 FROM tags WHERE id = ?
                   UNION ALL
                   SELECT t.id, descendants.depth + 1
                   FROM tags t JOIN descendants ON t.parent_id = descendants.id
               )
               SELECT id, depth FROM descendants ORDER BY depth DESC""",
            (tag_id,),
        ).fetchall()
        ids = [row["id"] for row in rows]
        connection.executemany(
            "DELETE FROM tags WHERE id = ?", [(current_id,) for current_id in ids]
        )
        return {"deleted_count": len(ids)}


def list_publishers(path: Path | None = None) -> list[dict]:
    connection = connect(path)
    try:
        publishers = connection.execute(
            "SELECT id, canonical_name FROM publishers ORDER BY canonical_name COLLATE NOCASE"
        ).fetchall()
        return [
            {
                "id": publisher["id"],
                "canonical_name": publisher["canonical_name"],
                "aliases": [row[0] for row in connection.execute(
                    "SELECT alias FROM publisher_aliases WHERE publisher_id = ? ORDER BY alias COLLATE NOCASE",
                    (publisher["id"],),
                ).fetchall()],
            }
            for publisher in publishers
        ]
    finally:
        connection.close()


def list_publisher_names(path: Path | None = None) -> list[str]:
    connection = connect(path)
    try:
        return [
            row["name"] for row in connection.execute(
                """SELECT DISTINCT TRIM(publisher) AS name
                   FROM editions WHERE TRIM(publisher) <> ''
                   ORDER BY name COLLATE NOCASE"""
            ).fetchall()
        ]
    finally:
        connection.close()


def normalize_publisher(
    payload: PublisherNormalizationInput, path: Path | None = None
) -> dict:
    canonical_name = payload.canonical_name.strip()
    aliases = list(dict.fromkeys(
        value.strip() for value in [canonical_name, *payload.aliases] if value.strip()
    ))
    with transaction(path) as connection:
        target = connection.execute(
            "SELECT id FROM publishers WHERE canonical_name = ? COLLATE NOCASE",
            (canonical_name,),
        ).fetchone()
        if target:
            target_id = target["id"]
        else:
            cursor = connection.execute(
                "INSERT INTO publishers (canonical_name) VALUES (?)", (canonical_name,)
            )
            target_id = int(cursor.lastrowid)

        for alias_name in aliases:
            existing = connection.execute(
                "SELECT publisher_id FROM publisher_aliases WHERE alias = ? COLLATE NOCASE",
                (alias_name,),
            ).fetchone()
            if existing and existing["publisher_id"] != target_id:
                source_id = existing["publisher_id"]
                source_aliases = connection.execute(
                    "SELECT alias FROM publisher_aliases WHERE publisher_id = ?", (source_id,)
                ).fetchall()
                connection.execute(
                    "UPDATE editions SET publisher_id = ? WHERE publisher_id = ?",
                    (target_id, source_id),
                )
                connection.execute(
                    "DELETE FROM publisher_aliases WHERE publisher_id = ?", (source_id,)
                )
                for source_alias in source_aliases:
                    connection.execute(
                        "INSERT OR IGNORE INTO publisher_aliases (publisher_id, alias) VALUES (?, ?)",
                        (target_id, source_alias["alias"]),
                    )
                connection.execute("DELETE FROM publishers WHERE id = ?", (source_id,))
            connection.execute(
                "INSERT OR IGNORE INTO publisher_aliases (publisher_id, alias) VALUES (?, ?)",
                (target_id, alias_name),
            )
            connection.execute(
                """UPDATE editions SET publisher_id = ?
                   WHERE publisher_id IS NULL AND publisher = ? COLLATE NOCASE""",
                (target_id, alias_name),
            )
    return next(item for item in list_publishers(path) if item["id"] == target_id)


def delete_publisher(publisher_id: int, path: Path | None = None) -> bool:
    with transaction(path) as connection:
        cursor = connection.execute(
            "DELETE FROM publishers WHERE id = ?", (publisher_id,)
        )
        return cursor.rowcount > 0
