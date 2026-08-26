from __future__ import annotations

from pathlib import Path
from sqlite3 import Connection, Row
from typing import Any

from .database import transaction


class MergeConflict(ValueError):
    def __init__(
        self, entity: str, target_id: int, source_id: int,
        conflicts: list[dict[str, Any]],
    ) -> None:
        super().__init__(f"{entity} merge has {len(conflicts)} unresolved conflict(s)")
        self.entity = entity
        self.target_id = target_id
        self.source_id = source_id
        self.conflicts = conflicts


def _text(value: Any) -> str:
    return str(value or "").strip()


def _has(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _field_resolution(
    target: Row, source: Row, fields: tuple[str, ...]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updates: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for field in fields:
        target_value = target[field]
        source_value = source[field]
        if _has(target_value) and _has(source_value):
            equal = (
                _text(target_value).casefold() == _text(source_value).casefold()
                if isinstance(target_value, str) or isinstance(source_value, str)
                else target_value == source_value
            )
            if not equal:
                conflicts.append({
                    "field": field,
                    "target": target_value,
                    "source": source_value,
                })
        elif not _has(target_value) and _has(source_value):
            updates[field] = source_value
    return updates, conflicts


def _apply_updates(
    connection: Connection, table: str, record_id: int, updates: dict[str, Any]
) -> None:
    if not updates:
        return
    assignments = ", ".join(f"{field} = ?" for field in updates)
    connection.execute(
        f"UPDATE {table} SET {assignments} WHERE id = ?",
        (*updates.values(), record_id),
    )


def _rows(
    connection: Connection, table: str, target_id: int, source_id: int
) -> tuple[Row, Row]:
    target = connection.execute(
        f"SELECT * FROM {table} WHERE id = ?", (target_id,)
    ).fetchone()
    source = connection.execute(
        f"SELECT * FROM {table} WHERE id = ?", (source_id,)
    ).fetchone()
    if not target or not source:
        raise ValueError(f"{table} merge record does not exist")
    if target_id == source_id:
        raise ValueError("merge source and target must differ")
    return target, source


def merge_works(
    target_id: int, source_id: int, path: Path | None = None
) -> dict[str, Any]:
    with transaction(path) as connection:
        target, source = _rows(connection, "works", target_id, source_id)
        updates, conflicts = _field_resolution(
            target, source, ("title", "subtitle", "authors", "scripts")
        )
        source_links = connection.execute(
            """SELECT edition_id, relation_type, volume_id
               FROM edition_works WHERE work_id = ?""",
            (source_id,),
        ).fetchall()
        for link in source_links:
            target_link = connection.execute(
                """SELECT relation_type, volume_id FROM edition_works
                   WHERE edition_id = ? AND work_id = ?""",
                (link["edition_id"], target_id),
            ).fetchone()
            if target_link and (
                target_link["relation_type"] != link["relation_type"]
                or target_link["volume_id"] != link["volume_id"]
            ):
                conflicts.append({
                    "field": "edition_relation",
                    "edition_id": link["edition_id"],
                    "target": {
                        "relation_type": target_link["relation_type"],
                        "volume_id": target_link["volume_id"],
                    },
                    "source": {
                        "relation_type": link["relation_type"],
                        "volume_id": link["volume_id"],
                    },
                })
        if conflicts:
            raise MergeConflict("Work", target_id, source_id, conflicts)

        _apply_updates(connection, "works", target_id, updates)
        connection.execute(
            """INSERT OR IGNORE INTO work_tags (work_id, tag_id)
               SELECT ?, tag_id FROM work_tags WHERE work_id = ?""",
            (target_id, source_id),
        )
        for link in source_links:
            target_link = connection.execute(
                """SELECT 1 FROM edition_works
                   WHERE edition_id = ? AND work_id = ?""",
                (link["edition_id"], target_id),
            ).fetchone()
            if target_link:
                connection.execute(
                    "DELETE FROM edition_works WHERE edition_id = ? AND work_id = ?",
                    (link["edition_id"], source_id),
                )
            else:
                connection.execute(
                    """UPDATE edition_works SET work_id = ?
                       WHERE edition_id = ? AND work_id = ?""",
                    (target_id, link["edition_id"], source_id),
                )
        connection.execute("DELETE FROM works WHERE id = ?", (source_id,))
        return {
            "entity": "Work", "target_id": target_id, "source_id": source_id,
            "merged": True,
        }


def merge_editions(
    target_id: int, source_id: int, path: Path | None = None
) -> dict[str, Any]:
    with transaction(path) as connection:
        target, source = _rows(connection, "editions", target_id, source_id)
        fields = (
            "title", "subtitle", "identifier", "translator", "responsibility", "other_title",
            "other_subtitle", "translated_title", "translated_subtitle",
            "edition_scripts", "version", "series", "publisher", "publisher_id",
            "publication_year", "publication_year_end",
        )
        updates, conflicts = _field_resolution(target, source, fields)
        target_relations = {
            row["work_id"]: row
            for row in connection.execute(
                """SELECT work_id, relation_type, volume_id
                   FROM edition_works WHERE edition_id = ?""",
                (target_id,),
            ).fetchall()
        }
        source_relations = connection.execute(
            """SELECT work_id, relation_type, volume_id
               FROM edition_works WHERE edition_id = ? ORDER BY position""",
            (source_id,),
        ).fetchall()
        for relation in source_relations:
            existing = target_relations.get(relation["work_id"])
            if existing and (
                existing["relation_type"] != relation["relation_type"]
                or existing["volume_id"] != relation["volume_id"]
            ):
                conflicts.append({
                    "field": "work_relation",
                    "work_id": relation["work_id"],
                    "target": {
                        "relation_type": existing["relation_type"],
                        "volume_id": existing["volume_id"],
                    },
                    "source": {
                        "relation_type": relation["relation_type"],
                        "volume_id": relation["volume_id"],
                    },
                })
        if conflicts:
            raise MergeConflict("Edition", target_id, source_id, conflicts)

        _apply_updates(connection, "editions", target_id, updates)
        # Remove source relations before moving linked Volumes.  The database
        # guard forbids a relation from pointing across Edition boundaries.
        connection.execute(
            "DELETE FROM edition_works WHERE edition_id = ?", (source_id,)
        )
        next_volume_position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM volumes WHERE edition_id = ?",
            (target_id,),
        ).fetchone()[0]
        source_volumes = connection.execute(
            "SELECT id FROM volumes WHERE edition_id = ? ORDER BY position, id",
            (source_id,),
        ).fetchall()
        for offset, volume in enumerate(source_volumes):
            connection.execute(
                "UPDATE volumes SET edition_id = ?, position = ? WHERE id = ?",
                (target_id, next_volume_position + offset, volume["id"]),
            )

        next_relation_position = connection.execute(
            """SELECT COALESCE(MAX(position), -1) + 1
               FROM edition_works WHERE edition_id = ?""",
            (target_id,),
        ).fetchone()[0]
        for relation in source_relations:
            if relation["work_id"] in target_relations:
                continue
            connection.execute(
                """INSERT INTO edition_works
                       (edition_id, work_id, position, relation_type, volume_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    target_id, relation["work_id"], next_relation_position,
                    relation["relation_type"], relation["volume_id"],
                ),
            )
            next_relation_position += 1
        connection.execute("DELETE FROM editions WHERE id = ?", (source_id,))
        return {
            "entity": "Edition", "target_id": target_id, "source_id": source_id,
            "moved_volume_ids": [row["id"] for row in source_volumes],
            "merged": True,
        }


def merge_volumes(
    target_id: int, source_id: int, path: Path | None = None
) -> dict[str, Any]:
    with transaction(path) as connection:
        target, source = _rows(connection, "volumes", target_id, source_id)
        conflicts: list[dict[str, Any]] = []
        if target["edition_id"] != source["edition_id"]:
            conflicts.append({
                "field": "edition_id",
                "target": target["edition_id"],
                "source": source["edition_id"],
            })
        updates, field_conflicts = _field_resolution(
            target,
            source,
            (
                "volume_number", "volume_title", "identifier", "version",
                "publication_year", "publication_year_end", "responsibility",
            ),
        )
        conflicts.extend(field_conflicts)
        if conflicts:
            raise MergeConflict("Volume", target_id, source_id, conflicts)

        _apply_updates(connection, "volumes", target_id, updates)
        connection.execute(
            "UPDATE copies SET volume_id = ? WHERE volume_id = ?",
            (target_id, source_id),
        )
        connection.execute(
            "UPDATE edition_works SET volume_id = ? WHERE volume_id = ?",
            (target_id, source_id),
        )
        connection.execute("DELETE FROM volumes WHERE id = ?", (source_id,))
        return {
            "entity": "Volume", "target_id": target_id, "source_id": source_id,
            "merged": True,
        }
