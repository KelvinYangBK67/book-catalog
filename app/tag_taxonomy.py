from __future__ import annotations

from pathlib import Path
from sqlite3 import Connection

from .database import transaction


MAIN_TAG_TREE: tuple[tuple[str, tuple], ...] = (
    ("人文", (
        ("語言與文字", (("語言", ()), ("語言學", ()))),
        ("文學", ()),
        ("歷史", ()),
        ("區域與文明研究", (
            ("中國研究", ()), ("印度學", ()), ("西藏研究", ()),
            ("內亞研究", ()), ("東南亞研究", ()), ("埃及學", ()),
            ("希臘羅馬研究", ()),
        )),
        ("考古與文博", ()),
    )),
    ("思想", (
        ("哲學", (
            ("德國觀念論", ()), ("歐陸哲學", ()), ("分析哲學", ()),
        )),
        ("宗教", (("佛教", ()), ("伊斯蘭教", ()))),
        ("馬克思主義", ()),
    )),
    ("社會科學", (("社會學", ()), ("教育學", ()))),
    ("形式科學", (("數學", ()),)),
    ("自然科學", (("化學", ()), ("生物學", ()))),
)


def _walk_tree(nodes: tuple[tuple[str, tuple], ...], parent: str | None = None):
    for name, children in nodes:
        yield name, parent
        yield from _walk_tree(children, name)


def _tag_rows(connection: Connection) -> list[dict]:
    return [
        dict(row) for row in connection.execute(
            "SELECT id, name, parent_id FROM tags ORDER BY id"
        ).fetchall()
    ]


def apply_main_tag_taxonomy(path: Path | None = None) -> dict:
    """Install the curated tree without deleting tags or Work relations."""
    created: list[dict] = []
    moved: list[dict] = []
    reused: list[dict] = []
    with transaction(path) as connection:
        rows = _tag_rows(connection)
        assigned_before = {
            (row["work_id"], row["tag_id"]) for row in connection.execute(
                "SELECT work_id, tag_id FROM work_tags"
            ).fetchall()
        }
        selected_by_name: dict[str, int] = {}

        for name, parent_name in _walk_tree(MAIN_TAG_TREE):
            parent_id = selected_by_name.get(parent_name) if parent_name else None
            exact_parent = next(
                (row for row in rows
                 if row["name"].casefold() == name.casefold()
                 and row["parent_id"] == parent_id),
                None,
            )
            record = exact_parent or next(
                (row for row in rows
                 if row["name"].casefold() == name.casefold()),
                None,
            )
            if record is None:
                cursor = connection.execute(
                    "INSERT INTO tags (name, parent_id) VALUES (?, ?)",
                    (name, parent_id),
                )
                record = {
                    "id": int(cursor.lastrowid), "name": name,
                    "parent_id": parent_id,
                }
                rows.append(record)
                created.append(dict(record))
            elif record["parent_id"] != parent_id:
                old_parent_id = record["parent_id"]
                connection.execute(
                    "UPDATE tags SET parent_id = ? WHERE id = ?",
                    (parent_id, record["id"]),
                )
                record["parent_id"] = parent_id
                moved.append({
                    "id": record["id"], "name": name,
                    "from_parent_id": old_parent_id,
                    "to_parent_id": parent_id,
                })
            else:
                reused.append({
                    "id": record["id"], "name": name,
                    "parent_id": parent_id,
                })
            selected_by_name[name] = record["id"]

        assigned_after = {
            (row["work_id"], row["tag_id"]) for row in connection.execute(
                "SELECT work_id, tag_id FROM work_tags"
            ).fetchall()
        }
        if assigned_after != assigned_before:
            raise RuntimeError("標籤樹調整不得修改任何作品與標籤關聯")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("標籤樹調整造成 foreign key 錯誤")

    return {
        "created": created,
        "moved": moved,
        "reused": reused,
        "node_ids": selected_by_name,
    }
