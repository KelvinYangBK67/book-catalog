from __future__ import annotations

from pathlib import Path
from sqlite3 import Connection, Row

from .database import connect, transaction
from .schemas import PublisherNormalizationInput, TagInput


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
