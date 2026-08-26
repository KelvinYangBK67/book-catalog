from __future__ import annotations

from pathlib import Path
from sqlite3 import Connection, Row

from .database import connect, initialize, transaction
from .admin_repository import (
    _tags_for_work, create_tag, delete_publisher, delete_tag, list_publisher_names,
    list_publishers, list_tag_violations, list_tags, list_tags_from_connection,
    normalize_publisher, update_tag,
)
from .edition_matching import editions_match
from .metadata_resolver import resolve_metadata
from .work_matching import find_work_candidates
from .schemas import (
    BookBatchInput, BookInput, CopyInput, CopyUpdateInput, EditionInput,
    VolumeInput, WorkInput,
)


def publication_year_bounds(value: object) -> tuple[int | None, int | None]:
    if value in (None, ""):
        return None, None
    parts = str(value).replace("\u2014", "\u2013").replace("-", "\u2013").split("\u2013")
    years = [int(part) for part in parts]
    return years[0], years[-1]


def publication_year_display(start: int | None, end: int | None) -> int | str | None:
    if start is None:
        return None
    if end is None or end == start:
        return start
    return f"{start}\u2013{end}"


SELECT_BOOK = """
SELECT
    c.id AS copy_id, c.volume_id, c.acquisition_date, c.location, c.reading_record,
    v.position AS volume_position, v.volume_number, v.volume_title,
    v.identifier AS volume_identifier, v.version AS volume_version,
    v.publication_year AS volume_publication_year,
    v.publication_year_end AS volume_publication_year_end,
    v.responsibility AS volume_responsibility,
    e.id AS edition_id, e.title AS edition_title, e.subtitle AS edition_subtitle,
    e.identifier, e.translator, e.responsibility, e.other_title, e.other_subtitle, e.translated_title,
    e.translated_subtitle, e.edition_scripts, e.version, e.series, e.publisher,
    e.publisher_id, COALESCE(p.canonical_name, '') AS publisher_canonical,
    e.publication_year, e.publication_year_end,
    (SELECT GROUP_CONCAT(work_id) FROM (
        SELECT work_id FROM edition_works WHERE edition_id = e.id ORDER BY position
    )) AS edition_work_ids_csv,
    w.id AS work_id, w.title, w.subtitle, w.authors, w.scripts,
    (SELECT GROUP_CONCAT(wt.tag_id) FROM work_tags wt WHERE wt.work_id = w.id) AS tag_ids_csv
FROM copies c
JOIN volumes v ON v.id = c.volume_id
JOIN editions e ON e.id = v.edition_id
JOIN edition_works primary_ew
  ON primary_ew.edition_id = e.id
 AND primary_ew.position = (
     SELECT MIN(primary_position.position)
     FROM edition_works primary_position
     WHERE primary_position.edition_id = e.id
 )
JOIN works w ON w.id = primary_ew.work_id
LEFT JOIN publishers p ON p.id = e.publisher_id
"""


def _resolved_metadata_from_book_row(row: Row, work: Row | None = None) -> dict:
    work_row = work or row
    return resolve_metadata(
        {
            "title": work_row["title"],
            "subtitle": work_row["subtitle"],
            "authors": work_row["authors"],
            "scripts": work_row["scripts"],
        },
        {
            "title": row["edition_title"],
            "subtitle": row["edition_subtitle"],
            "translated_title": row["translated_title"],
            "translated_subtitle": row["translated_subtitle"],
            "edition_scripts": row["edition_scripts"],
            "identifier": row["identifier"],
            "version": row["version"],
            "publication_year": row["publication_year"],
            "publication_year_end": row["publication_year_end"],
            "translator": row["translator"],
            "responsibility": row["responsibility"],
        },
        {
            "volume_title": row["volume_title"],
            "identifier": row["volume_identifier"],
            "version": row["volume_version"],
            "publication_year": row["volume_publication_year"],
            "publication_year_end": row["volume_publication_year_end"],
            "responsibility": row["volume_responsibility"],
        },
    )


def _volume_record(row: Row, work: Row | None = None) -> dict:
    effective_metadata = _resolved_metadata_from_book_row(row, work)
    return {
        "id": row["volume_id"],
        "edition_id": row["edition_id"],
        "position": row["volume_position"],
        "volume_number": row["volume_number"],
        "volume_title": row["volume_title"],
        "identifier": row["volume_identifier"],
        "version": row["volume_version"],
        "publication_year": publication_year_display(
            row["volume_publication_year"], row["volume_publication_year_end"]
        ),
        "responsibility": row["volume_responsibility"],
        "effective_metadata": effective_metadata,
    }


def _book_record(row: Row, connection: Connection) -> dict:
    volume = _volume_record(row)
    edition_effective_metadata = resolve_metadata(
        {
            "title": row["title"], "subtitle": row["subtitle"],
            "authors": row["authors"], "scripts": row["scripts"],
        },
        {
            "title": row["edition_title"], "subtitle": row["edition_subtitle"],
            "translated_title": row["translated_title"],
            "translated_subtitle": row["translated_subtitle"],
            "edition_scripts": row["edition_scripts"],
            "identifier": row["identifier"], "version": row["version"],
            "publication_year": row["publication_year"],
            "publication_year_end": row["publication_year_end"],
            "translator": row["translator"],
            "responsibility": row["responsibility"],
        },
        None,
    )
    return {
        "id": row["copy_id"],
        "edition_id": row["edition_id"],
        "volume_id": row["volume_id"],
        "work": {
            "title": row["title"], "subtitle": row["subtitle"],
            "authors": row["authors"], "scripts": row["scripts"],
            "tag_ids": [int(value) for value in (row["tag_ids_csv"] or "").split(",") if value],
            "tag_names": [],
        },
        "edition": {
            "title": row["edition_title"],
            "subtitle": row["edition_subtitle"],
            "work_ids": [int(value) for value in (row["edition_work_ids_csv"] or "").split(",") if value],
            "work_relations": _edition_work_relations(connection, row["edition_id"]),
            "identifier": row["identifier"],
            "translator": row["translator"],
            "responsibility": row["responsibility"],
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
            "publication_year": publication_year_display(
                row["publication_year"], row["publication_year_end"]
            ),
        },
        "volume": volume,
        "edition_effective_metadata": edition_effective_metadata,
        "copy": {
            "volume_id": row["volume_id"],
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


def find_work_candidates_in_database(
    connection: Connection, work: WorkInput
) -> list[Row]:
    rows = connection.execute(
        "SELECT id, title, subtitle, authors, scripts FROM works ORDER BY id"
    ).fetchall()
    return find_work_candidates(rows, work)


def _insert_work(connection: Connection, work: WorkInput) -> int:
    cursor = connection.execute(
        "INSERT INTO works (title, subtitle, authors, scripts) VALUES (?, ?, ?, ?)",
        (work.title, work.subtitle, work.authors, work.scripts),
    )
    work_id = int(cursor.lastrowid)
    _set_work_tags(connection, work_id, work.tag_ids, work.tag_names, True)
    return work_id


def _work_is_safe_to_reuse(
    connection: Connection, candidate: Row, work: WorkInput
) -> bool:
    fields = ("title", "subtitle", "authors", "scripts")
    if any(
        str(candidate[field] or "").strip().casefold()
        != str(getattr(work, field) or "").strip().casefold()
        for field in fields
    ):
        return False
    assigned = _tags_for_work(connection, int(candidate["id"]))
    assigned_ids = {tag["id"] for tag in assigned}
    assigned_names = {str(tag["name"]).strip().casefold() for tag in assigned}
    return (
        set(work.tag_ids).issubset(assigned_ids)
        and {
            name.strip().casefold() for name in work.tag_names if name.strip()
        }.issubset(assigned_names)
    )


def _reuse_or_create_work(connection: Connection, work: WorkInput) -> int:
    candidates = find_work_candidates_in_database(connection, work)
    reusable = next(
        (
            candidate for candidate in candidates
            if _work_is_safe_to_reuse(connection, candidate, work)
        ),
        None,
    )
    if reusable is not None:
        return int(reusable["id"])
    return _insert_work(connection, work)


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


def _resolve_relation_volume_id(
    connection: Connection,
    edition_id: int,
    relation: dict,
    fallback_volume_id: int | None = None,
) -> int | None:
    if relation["relation_type"] == "contained":
        return None
    volume_id = relation.get("volume_id")
    if volume_id is None:
        volume_id = fallback_volume_id
    if volume_id is None:
        raise ValueError("分冊關聯必須引用已存在的冊")
    row = connection.execute(
        "SELECT id FROM volumes WHERE id = ? AND edition_id = ?",
        (volume_id, edition_id),
    ).fetchone()
    if not row:
        raise ValueError("關聯的冊不屬於此版本")
    return int(row["id"])


def _edition_work_relations(connection: Connection, edition_id: int) -> list[dict]:
    return [
        {
            "work_id": row["work_id"],
            "relation_type": row["relation_type"],
            "volume_id": row["volume_id"],
        }
        for row in connection.execute(
            """SELECT work_id, relation_type, volume_id
               FROM edition_works
               WHERE edition_id = ? ORDER BY position""",
            (edition_id,),
        ).fetchall()
    ]


def _edition_work_ids(connection: Connection, edition_id: int) -> list[int]:
    return [
        relation["work_id"]
        for relation in _edition_work_relations(connection, edition_id)
    ]


def _normalize_edition_work_relations(relations: list) -> list[dict]:
    normalized: list[dict] = []
    positions: dict[int, int] = {}
    for relation in relations:
        data = relation.model_dump() if hasattr(relation, "model_dump") else dict(relation)
        work_id = int(data["work_id"])
        relation_type = str(data.get("relation_type") or "contained")
        if relation_type not in {"volume", "contained"}:
            raise ValueError("版本與作品的關聯類型必須是分冊或同冊收錄")
        normalized_relation = {
            "work_id": work_id,
            "relation_type": relation_type,
            "volume_id": (
                int(data["volume_id"])
                if relation_type == "volume" and data.get("volume_id") is not None
                else None
            ),
        }
        if work_id in positions:
            normalized[positions[work_id]] = normalized_relation
        else:
            positions[work_id] = len(normalized)
            normalized.append(normalized_relation)
    return normalized


def _use_structured_relations(edition: EditionInput) -> bool:
    relation_ids = [relation.work_id for relation in edition.work_relations]
    return bool(relation_ids) and (
        not edition.work_ids or relation_ids == edition.work_ids
    )


def _relations_from_input(work_id: int, edition: EditionInput) -> list[dict]:
    if _use_structured_relations(edition):
        relations = _normalize_edition_work_relations([
            {
                **(relation.model_dump() if hasattr(relation, "model_dump") else dict(relation)),
                "work_id": work_id if relation.work_id == 0 else relation.work_id,
            }
            for relation in edition.work_relations
        ])
        if work_id not in {relation["work_id"] for relation in relations}:
            relations.insert(0, {
                "work_id": work_id,
                "relation_type": "contained",
                "volume_id": None,
            })
        return relations
    return _normalize_edition_work_relations([
        {"work_id": related_id, "relation_type": "contained"}
        for related_id in [work_id, *edition.work_ids]
    ])


def _set_edition_work_relations(
    connection: Connection,
    edition_id: int,
    relations: list,
    fallback_volume_ids: list[int] | None = None,
) -> None:
    normalized = _normalize_edition_work_relations(relations)
    if not normalized:
        raise ValueError("版本至少需要關聯一個作品")
    ordered_ids = [relation["work_id"] for relation in normalized]
    placeholders = ",".join("?" for _ in ordered_ids)
    found = connection.execute(
        f"SELECT COUNT(*) FROM works WHERE id IN ({placeholders})", ordered_ids
    ).fetchone()[0]
    if found != len(ordered_ids):
        raise ValueError("版本關聯中包含不存在的作品")
    fallback_ids = iter(fallback_volume_ids or [])
    resolved = []
    for relation in normalized:
        fallback = (
            next(fallback_ids, None)
            if relation["relation_type"] == "volume"
               and relation.get("volume_id") is None
            else None
        )
        resolved.append({
            **relation,
            "volume_id": _resolve_relation_volume_id(
                connection, edition_id, relation, fallback
            ),
        })
    connection.execute("DELETE FROM edition_works WHERE edition_id = ?", (edition_id,))
    connection.executemany(
        """INSERT INTO edition_works
               (edition_id, work_id, position, relation_type, volume_id)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (
                edition_id, relation["work_id"], position,
                relation["relation_type"], relation["volume_id"],
            )
            for position, relation in enumerate(resolved)
        ],
    )


def _set_edition_works(connection: Connection, edition_id: int, work_ids: list[int]) -> None:
    _set_edition_work_relations(
        connection,
        edition_id,
        [{"work_id": work_id, "relation_type": "contained"} for work_id in work_ids],
    )


def _work_edition_relations(connection: Connection, work_id: int) -> list[dict]:
    return [
        {
            "edition_id": row["edition_id"],
            "relation_type": row["relation_type"],
            "volume_id": row["volume_id"],
        }
        for row in connection.execute(
            """SELECT edition_id, relation_type, volume_id
               FROM edition_works
               WHERE work_id = ? ORDER BY edition_id""",
            (work_id,),
        ).fetchall()
    ]


def _set_work_edition_relations(
    connection: Connection, work_id: int, relations: list
) -> None:
    normalized: list[dict] = []
    positions: dict[int, int] = {}
    for relation in relations:
        data = relation.model_dump() if hasattr(relation, "model_dump") else dict(relation)
        edition_id = int(data["edition_id"])
        relation_type = str(data.get("relation_type") or "contained")
        if relation_type not in {"volume", "contained"}:
            raise ValueError("作品與版本的關聯類型必須是分冊或同冊收錄")
        item = {
            "edition_id": edition_id,
            "relation_type": relation_type,
            "volume_id": (
                int(data["volume_id"])
                if relation_type == "volume" and data.get("volume_id") is not None
                else None
            ),
        }
        if edition_id in positions:
            normalized[positions[edition_id]] = item
        else:
            positions[edition_id] = len(normalized)
            normalized.append(item)

    desired_ids = [item["edition_id"] for item in normalized]
    if desired_ids:
        placeholders = ",".join("?" for _ in desired_ids)
        found = connection.execute(
            f"SELECT COUNT(*) FROM editions WHERE id IN ({placeholders})", desired_ids
        ).fetchone()[0]
        if found != len(desired_ids):
            raise ValueError("作品關聯中包含不存在的版本")

    current_ids = {
        row["edition_id"] for row in connection.execute(
            "SELECT edition_id FROM edition_works WHERE work_id = ?", (work_id,)
        ).fetchall()
    }
    for edition_id in current_ids - set(desired_ids):
        link_count = connection.execute(
            "SELECT COUNT(*) FROM edition_works WHERE edition_id = ?", (edition_id,)
        ).fetchone()[0]
        if link_count <= 1:
            raise ValueError("不能移除此關聯：版本至少需要保留一個作品")
        connection.execute(
            "DELETE FROM edition_works WHERE edition_id = ? AND work_id = ?",
            (edition_id, work_id),
        )

    for item in normalized:
        resolved_volume_id = _resolve_relation_volume_id(
            connection, item["edition_id"], item
        )
        existing = connection.execute(
            "SELECT 1 FROM edition_works WHERE edition_id = ? AND work_id = ?",
            (item["edition_id"], work_id),
        ).fetchone()
        if existing:
            connection.execute(
                """UPDATE edition_works
                   SET relation_type = ?, volume_id = ?
                   WHERE edition_id = ? AND work_id = ?""",
                (
                    item["relation_type"], resolved_volume_id,
                    item["edition_id"], work_id,
                ),
            )
            continue
        position = connection.execute(
            """SELECT COALESCE(MAX(position), -1) + 1
               FROM edition_works WHERE edition_id = ?""",
            (item["edition_id"],),
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO edition_works
                   (edition_id, work_id, position, relation_type, volume_id)
               VALUES (?, ?, ?, ?, ?)""",
            (
                item["edition_id"], work_id, position,
                item["relation_type"], resolved_volume_id,
            ),
        )


def find_edition_candidates_in_database(
    connection: Connection, work_id: int, edition: EditionInput
) -> list[Row]:
    rows = connection.execute(
        """SELECT DISTINCT e.*, COALESCE(p.canonical_name, '') AS publisher_canonical
           FROM editions e
           JOIN edition_works ew ON ew.edition_id = e.id
           LEFT JOIN publishers p ON p.id = e.publisher_id
           WHERE ew.work_id = ? ORDER BY e.id""",
        (work_id,),
    ).fetchall()
    return [
        candidate
        for candidate in rows
        if editions_match(candidate, edition)
    ]


def _reuse_or_create_edition(
    connection: Connection, work_id: int, edition: EditionInput
) -> tuple[int, Row | None]:
    if edition.existing_edition_id is not None:
        existing = connection.execute(
            """SELECT e.*, COALESCE(p.canonical_name, '') AS publisher_canonical
               FROM editions e
               JOIN edition_works ew ON ew.edition_id = e.id
               LEFT JOIN publishers p ON p.id = e.publisher_id
               WHERE e.id = ? AND ew.work_id = ?""",
            (edition.existing_edition_id, work_id),
        ).fetchone()
        if not existing:
            raise ValueError("指定的既有版本不存在或未關聯此作品")
        return int(existing["id"]), existing

    publisher_id = _resolve_publisher(
        connection, edition.publisher, edition.publisher_id
    )
    candidate_data = dict(edition.model_dump())
    candidate_data["publisher_id"] = publisher_id
    candidates = find_edition_candidates_in_database(
        connection, work_id, EditionInput.model_validate(candidate_data)
    )
    if candidates and not edition.force_new_edition:
        return int(candidates[0]["id"]), candidates[0]

    year_start, year_end = publication_year_bounds(edition.publication_year)
    cursor = connection.execute(
        """INSERT INTO editions
           (title, subtitle, identifier, translator, responsibility, other_title, other_subtitle,
            translated_title, translated_subtitle, edition_scripts, version, series,
            publisher, publisher_id, publication_year, publication_year_end, force_separate)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            edition.title, edition.subtitle, edition.identifier,
            edition.translator, edition.responsibility, edition.other_title, edition.other_subtitle,
            edition.translated_title, edition.translated_subtitle,
            edition.edition_scripts, edition.version, edition.series,
            edition.publisher, publisher_id, year_start, year_end,
            int(edition.force_new_edition),
        ),
    )
    edition_id = int(cursor.lastrowid)
    return edition_id, None


def _volume_for_reused_edition(
    volume: VolumeInput, edition: EditionInput, existing: Row | None
) -> VolumeInput:
    if existing is None:
        return volume
    updates: dict[str, object] = {}
    incoming_identifier = str(edition.identifier or "").strip()
    existing_identifier = str(existing["identifier"] or "").strip()
    if (
        not volume.identifier
        and incoming_identifier
        and incoming_identifier.casefold() != existing_identifier.casefold()
    ):
        updates["identifier"] = incoming_identifier

    incoming_year = edition.publication_year
    existing_year = publication_year_display(
        existing["publication_year"], existing["publication_year_end"]
    )
    if (
        volume.publication_year in (None, "")
        and incoming_year not in (None, "")
        and str(incoming_year) != str(existing_year)
    ):
        updates["publication_year"] = incoming_year
    return volume.model_copy(update=updates) if updates else volume


def _volume_from_row(row: Row) -> dict:
    effective_metadata = resolve_metadata(
        {
            "title": row["work_title"],
            "subtitle": row["work_subtitle"],
            "authors": row["work_authors"],
            "scripts": row["work_scripts"],
        },
        {
            "title": row["edition_title"],
            "subtitle": row["edition_subtitle"],
            "translated_title": row["translated_title"],
            "translated_subtitle": row["translated_subtitle"],
            "edition_scripts": row["edition_scripts"],
            "identifier": row["edition_identifier"],
            "version": row["edition_version"],
            "publication_year": row["edition_publication_year"],
            "publication_year_end": row["edition_publication_year_end"],
            "translator": row["edition_translator"],
            "responsibility": row["edition_responsibility"],
        },
        row,
    )
    return {
        "id": row["id"],
        "edition_id": row["edition_id"],
        "position": row["position"],
        "volume_number": row["volume_number"],
        "volume_title": row["volume_title"],
        "identifier": row["identifier"],
        "version": row["version"],
        "publication_year": publication_year_display(
            row["publication_year"], row["publication_year_end"]
        ),
        "responsibility": row["responsibility"],
        "effective_metadata": effective_metadata,
    }

def _volume_input_matches(row: Row, volume: VolumeInput) -> bool:
    incoming_year = publication_year_bounds(volume.publication_year)
    comparisons = (
        (row["identifier"], volume.identifier),
        (row["version"], volume.version),
        (row["responsibility"], volume.responsibility),
    )
    for current, incoming in comparisons:
        if str(incoming or "").strip() and (
            str(current or "").strip().casefold()
            != str(incoming or "").strip().casefold()
        ):
            return False
    if volume.publication_year not in (None, "") and (
        row["publication_year"], row["publication_year_end"]
    ) != incoming_year:
        return False
    return True


def _insert_volume(
    connection: Connection, edition_id: int, volume: VolumeInput
) -> int:
    position = volume.position
    if position is None:
        position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM volumes WHERE edition_id = ?",
            (edition_id,),
        ).fetchone()[0]
    elif connection.execute(
        "SELECT 1 FROM volumes WHERE edition_id = ? AND position = ?",
        (edition_id, position),
    ).fetchone():
        raise ValueError("此版本中已有相同的冊排序位置")
    year_start, year_end = publication_year_bounds(volume.publication_year)
    cursor = connection.execute(
        """INSERT INTO volumes
               (edition_id, position, volume_number, volume_title, identifier,
                version, publication_year, publication_year_end, responsibility)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            edition_id, position, volume.volume_number, volume.volume_title,
            volume.identifier, volume.version, year_start, year_end,
            volume.responsibility,
        ),
    )
    return int(cursor.lastrowid)


def _find_or_create_volume(
    connection: Connection, edition_id: int, volume: VolumeInput
) -> int:
    if volume.id is not None:
        row = connection.execute(
            "SELECT id FROM volumes WHERE id = ? AND edition_id = ?",
            (volume.id, edition_id),
        ).fetchone()
        if not row:
            raise ValueError("此冊不存在於指定版本")
        return int(row["id"])

    rows = connection.execute(
        """SELECT * FROM volumes
           WHERE edition_id = ? AND volume_number = ? COLLATE NOCASE
             AND volume_title = ? COLLATE NOCASE
           ORDER BY position, id""",
        (edition_id, volume.volume_number, volume.volume_title),
    ).fetchall()
    for row in rows:
        if _volume_input_matches(row, volume):
            return int(row["id"])

    return _insert_volume(connection, edition_id, volume)
def _update_volume_row(
    connection: Connection, volume_id: int, volume: VolumeInput
) -> None:
    current = connection.execute(
        "SELECT edition_id FROM volumes WHERE id = ?", (volume_id,)
    ).fetchone()
    if not current:
        raise ValueError("冊不存在")
    year_start, year_end = publication_year_bounds(volume.publication_year)
    position = volume.position
    if position is None:
        position = connection.execute(
            "SELECT position FROM volumes WHERE id = ?", (volume_id,)
        ).fetchone()[0]
    conflict = connection.execute(
        """SELECT 1 FROM volumes
           WHERE edition_id = ? AND position = ? AND id <> ?""",
        (current["edition_id"], position, volume_id),
    ).fetchone()
    if conflict:
        raise ValueError("此版本中已有相同的冊排序位置")
    connection.execute(
        """UPDATE volumes SET position = ?, volume_number = ?, volume_title = ?,
               identifier = ?, version = ?, publication_year = ?,
               publication_year_end = ?, responsibility = ? WHERE id = ?""",
        (
            position, volume.volume_number, volume.volume_title, volume.identifier,
            volume.version, year_start, year_end, volume.responsibility, volume_id,
        ),
    )


def _insert_copy(connection: Connection, volume_id: int, copy: CopyInput) -> int:
    cursor = connection.execute(
        """INSERT INTO copies
               (volume_id, acquisition_date, location, reading_record)
           VALUES (?, ?, ?, ?)""",
        (
            volume_id,
            copy.acquisition_date.isoformat() if copy.acquisition_date else None,
            copy.location,
            copy.reading_record,
        ),
    )
    return int(cursor.lastrowid)


def create_book(book: BookInput, path: Path | None = None) -> dict:
    with transaction(path) as connection:
        work_id = _reuse_or_create_work(connection, book.work)
        edition_id, existing_edition = _reuse_or_create_edition(
            connection, work_id, book.edition
        )
        volume_input = _volume_for_reused_edition(
            book.volume, book.edition, existing_edition
        )
        volume_id = _find_or_create_volume(connection, edition_id, volume_input)
        if existing_edition is None:
            _set_edition_work_relations(
                connection, edition_id, _relations_from_input(work_id, book.edition),
                [volume_id],
            )
        copy_id = _insert_copy(connection, volume_id, book.copy_)
    record = get_book(copy_id, path)
    assert record is not None
    return record


def create_books_batch(batch: BookBatchInput, path: Path | None = None) -> list[dict]:
    copy_ids: list[int] = []
    with transaction(path) as connection:
        work_id = _reuse_or_create_work(connection, batch.work)
        edition_id, existing_edition = _reuse_or_create_edition(
            connection, work_id, batch.edition
        )
        seen: set[tuple[str, str]] = set()
        created_volume_ids: list[int] = []
        for index, volume_number in enumerate(batch.volume_numbers):
            volume_title = (
                batch.volume_titles[index] if index < len(batch.volume_titles) else ""
            )
            volume_key = (volume_number.casefold(), volume_title.casefold())
            if volume_key in seen:
                continue
            seen.add(volume_key)
            volume_data = batch.volume.model_copy(update={
                "id": None,
                "position": None,
                "volume_number": volume_number,
                "volume_title": volume_title,
            })
            volume_data = _volume_for_reused_edition(
                volume_data, batch.edition, existing_edition
            )
            volume_id = _find_or_create_volume(connection, edition_id, volume_data)
            created_volume_ids.append(volume_id)
            copy_ids.append(_insert_copy(connection, volume_id, batch.copy_))
        if existing_edition is None:
            _set_edition_work_relations(
                connection, edition_id, _relations_from_input(work_id, batch.edition),
                created_volume_ids,
            )
    return [
        record for copy_id in copy_ids
        if (record := get_book(copy_id, path)) is not None
    ]


def get_book(copy_id: int, path: Path | None = None) -> dict | None:
    connection = connect(path)
    try:
        row = connection.execute(SELECT_BOOK + " WHERE c.id = ?", (copy_id,)).fetchone()
        return _book_record(row, connection) if row else None
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
                   OR e.title LIKE ? COLLATE NOCASE OR e.subtitle LIKE ? COLLATE NOCASE
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
                   OR v.identifier LIKE ? COLLATE NOCASE
                   OR v.volume_number LIKE ? COLLATE NOCASE OR v.volume_title LIKE ? COLLATE NOCASE
                   OR c.acquisition_date LIKE ? COLLATE NOCASE
                   OR c.location LIKE ? COLLATE NOCASE OR c.reading_record LIKE ? COLLATE NOCASE
                   OR EXISTS (
                       SELECT 1 FROM edition_works search_ew
                       JOIN works related_w ON related_w.id = search_ew.work_id
                       WHERE search_ew.edition_id = e.id
                         AND (related_w.title LIKE ? COLLATE NOCASE
                              OR related_w.subtitle LIKE ? COLLATE NOCASE
                              OR related_w.authors LIKE ? COLLATE NOCASE)
                   )
                   OR EXISTS (SELECT 1 FROM work_tags wt JOIN tags t ON t.id = wt.tag_id
                              WHERE wt.work_id = w.id AND t.name LIKE ? COLLATE NOCASE)
            """
            parameters = (pattern,) * 29
        sql += " ORDER BY w.title COLLATE NOCASE, e.publication_year IS NULL, e.publication_year, e.id, c.id"
        return [_book_record(row, connection) for row in connection.execute(sql, parameters).fetchall()]
    finally:
        connection.close()


def list_editions(query: str = "", path: Path | None = None) -> list[dict]:
    connection = connect(path)
    try:
        sql = """
            SELECT e.id, e.title, e.subtitle, e.translated_title,
                   e.translated_subtitle, e.identifier, e.publisher,
                   COALESCE(p.canonical_name, '') AS publisher_canonical,
                   e.publication_year, e.publication_year_end,
                   e.version, e.series, e.edition_scripts,
                   COUNT(DISTINCT v.id) AS volume_count,
                   COUNT(DISTINCT c.id) AS copy_count
            FROM editions e
            LEFT JOIN publishers p ON p.id = e.publisher_id
            LEFT JOIN volumes v ON v.edition_id = e.id
            LEFT JOIN copies c ON c.volume_id = v.id
        """
        parameters: tuple[str, ...] = ()
        if query.strip():
            pattern = f"%{query.strip()}%"
            sql += """
                WHERE e.title LIKE ? COLLATE NOCASE
                   OR e.subtitle LIKE ? COLLATE NOCASE
                   OR e.translated_title LIKE ? COLLATE NOCASE
                   OR e.translated_subtitle LIKE ? COLLATE NOCASE
                   OR e.identifier LIKE ? COLLATE NOCASE
                   OR v.identifier LIKE ? COLLATE NOCASE
                   OR e.publisher LIKE ? COLLATE NOCASE
                   OR p.canonical_name LIKE ? COLLATE NOCASE
                   OR CAST(e.publication_year AS TEXT) LIKE ? COLLATE NOCASE
                   OR CAST(e.publication_year_end AS TEXT) LIKE ? COLLATE NOCASE
                   OR e.version LIKE ? COLLATE NOCASE
                   OR e.series LIKE ? COLLATE NOCASE
                   OR EXISTS (
                       SELECT 1 FROM edition_works ew
                       JOIN works w ON w.id = ew.work_id
                       WHERE ew.edition_id = e.id
                         AND (w.title LIKE ? COLLATE NOCASE
                              OR w.subtitle LIKE ? COLLATE NOCASE
                              OR w.authors LIKE ? COLLATE NOCASE)
                   )
            """
            parameters = (pattern,) * 15
        sql += """
            GROUP BY e.id, e.title, e.subtitle, e.translated_title,
                     e.translated_subtitle, e.identifier, e.publisher,
                     p.canonical_name, e.publication_year, e.publication_year_end,
                     e.version,
                     e.series, e.edition_scripts
            ORDER BY COALESCE(NULLIF(e.title, ''), NULLIF(e.translated_title, ''), e.id)
                     COLLATE NOCASE, e.id
        """
        records = [dict(row) for row in connection.execute(sql, parameters).fetchall()]
        for record in records:
            record["publication_year"] = publication_year_display(
                record["publication_year"], record.pop("publication_year_end")
            )
            record["work_relations"] = _edition_work_relations(connection, record["id"])
            record["work_ids"] = [
                relation["work_id"] for relation in record["work_relations"]
            ]
            primary_work = connection.execute(
                """SELECT w.title, w.subtitle, w.authors, w.scripts
                   FROM works w
                   JOIN edition_works ew ON ew.work_id = w.id
                   WHERE ew.edition_id = ? ORDER BY ew.position LIMIT 1""",
                (record["id"],),
            ).fetchone()
            record["effective_metadata"] = resolve_metadata(
                primary_work, record, None
            )
        return records
    finally:
        connection.close()


def create_work_record(work: WorkInput, path: Path | None = None) -> dict:
    with transaction(path) as connection:
        work_id = _insert_work(connection, work)
        if work.edition_relations is not None:
            _set_work_edition_relations(connection, work_id, work.edition_relations)
    record = get_work(work_id, path)
    assert record is not None
    return record


def list_works(query: str = "", path: Path | None = None) -> list[dict]:
    connection = connect(path)
    try:
        sql = """
            SELECT w.id, w.title, w.subtitle, w.authors, w.scripts,
                   COUNT(DISTINCT e.id) AS edition_count,
                   COUNT(DISTINCT v.id) AS volume_count,
                   COUNT(DISTINCT c.id) AS copy_count
            FROM works w
            LEFT JOIN edition_works ew ON ew.work_id = w.id
            LEFT JOIN editions e ON e.id = ew.edition_id
            LEFT JOIN volumes v ON v.edition_id = e.id
            LEFT JOIN copies c ON c.volume_id = v.id
        """
        parameters: tuple[str, ...] = ()
        if query.strip():
            pattern = f"%{query.strip()}%"
            sql += """
                WHERE w.title LIKE ? COLLATE NOCASE OR w.authors LIKE ? COLLATE NOCASE
                   OR w.subtitle LIKE ? COLLATE NOCASE OR w.scripts LIKE ? COLLATE NOCASE
                   OR e.title LIKE ? COLLATE NOCASE OR e.subtitle LIKE ? COLLATE NOCASE
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
                   OR v.identifier LIKE ? COLLATE NOCASE
                   OR v.volume_number LIKE ? COLLATE NOCASE OR v.volume_title LIKE ? COLLATE NOCASE
                   OR c.acquisition_date LIKE ? COLLATE NOCASE
                   OR c.location LIKE ? COLLATE NOCASE OR c.reading_record LIKE ? COLLATE NOCASE
                   OR EXISTS (
                       SELECT 1 FROM edition_works search_ew
                       JOIN works related_w ON related_w.id = search_ew.work_id
                       WHERE search_ew.edition_id = e.id
                         AND (related_w.title LIKE ? COLLATE NOCASE
                              OR related_w.subtitle LIKE ? COLLATE NOCASE
                              OR related_w.authors LIKE ? COLLATE NOCASE)
                   )
                   OR EXISTS (SELECT 1 FROM work_tags wt JOIN tags t ON t.id = wt.tag_id
                              WHERE wt.work_id = w.id AND t.name LIKE ? COLLATE NOCASE)
            """
            parameters = (pattern,) * 29
        sql += " GROUP BY w.id, w.title, w.subtitle, w.authors, w.scripts ORDER BY w.title COLLATE NOCASE, w.id"
        records = [dict(row) for row in connection.execute(sql, parameters).fetchall()]
        for record in records:
            record["tags"] = _tags_for_work(connection, record["id"])
            record["publishers"] = [row[0] for row in connection.execute(
                """SELECT DISTINCT COALESCE(p.canonical_name, e.publisher) AS value
                   FROM editions e
                   JOIN edition_works ew ON ew.edition_id = e.id
                   LEFT JOIN publishers p ON p.id = e.publisher_id
                   WHERE ew.work_id = ? AND COALESCE(p.canonical_name, e.publisher) <> '' ORDER BY value""",
                (record["id"],),
            ).fetchall()]
            record["locations"] = [row[0] for row in connection.execute(
                """SELECT DISTINCT c.location FROM copies c
                   JOIN volumes v ON v.id = c.volume_id
                   JOIN editions e ON e.id = v.edition_id
                   JOIN edition_works ew ON ew.edition_id = e.id
                   WHERE ew.work_id = ? AND c.location <> '' ORDER BY c.location""",
                (record["id"],),
            ).fetchall()]
            record["years"] = [row for row in connection.execute(
                """SELECT DISTINCT e.publication_year, e.publication_year_end FROM editions e
                   JOIN edition_works ew ON ew.edition_id = e.id
                   WHERE ew.work_id = ? AND e.publication_year IS NOT NULL
                   ORDER BY e.publication_year""",
                (record["id"],),
            ).fetchall()]
            record["years"] = [
                publication_year_display(row[0], row[1]) for row in record["years"]
            ]
            script_values: list[str] = []
            edition_rows = connection.execute(
                """SELECT e.edition_scripts FROM editions e
                   JOIN edition_works ew ON ew.edition_id = e.id
                   WHERE ew.work_id = ? ORDER BY e.id""",
                (record["id"],),
            ).fetchall()
            if not edition_rows:
                edition_rows = [{"edition_scripts": ""}]
            for edition_row in edition_rows:
                resolved = resolve_metadata(
                    record, edition_row, None
                )["scripts"]["value"]
                for value in str(resolved or "").split(";"):
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
            """SELECT e.id AS edition_id, e.title AS edition_title, e.subtitle AS edition_subtitle,
                      e.identifier, e.translator, e.responsibility,
                      e.other_title, e.other_subtitle,
                      e.translated_title, e.translated_subtitle, e.edition_scripts,
                      e.version, e.series, e.publisher, e.publisher_id,
                      COALESCE(p.canonical_name, '') AS publisher_canonical,
                      e.publication_year, e.publication_year_end,
                      (SELECT GROUP_CONCAT(work_id) FROM (
                          SELECT work_id FROM edition_works WHERE edition_id = e.id ORDER BY position
                      )) AS edition_work_ids_csv,
                      v.id AS volume_id, v.position AS volume_position,
                      v.volume_number, v.volume_title,
                      v.identifier AS volume_identifier, v.version AS volume_version,
                      v.publication_year AS volume_publication_year,
                      v.publication_year_end AS volume_publication_year_end,
                      v.responsibility AS volume_responsibility,
                      c.id AS copy_id, c.acquisition_date,
                      c.location, c.reading_record
               FROM editions e
               JOIN edition_works ew ON ew.edition_id = e.id
               JOIN volumes v ON v.edition_id = e.id
               LEFT JOIN copies c ON c.volume_id = v.id
               LEFT JOIN publishers p ON p.id = e.publisher_id
               WHERE ew.work_id = ?
               ORDER BY e.publication_year IS NULL, e.publication_year, e.id,
                        v.position, v.id, c.id""",
            (work_id,),
        ).fetchall()
        editions: list[dict] = []
        by_edition: dict[int, dict] = {}
        volume_groups: dict[int, dict] = {}
        for row in rows:
            edition_id = row["edition_id"]
            if edition_id not in by_edition:
                edition_data = {
                        "title": row["edition_title"], "subtitle": row["edition_subtitle"],
                        "work_ids": [int(value) for value in (row["edition_work_ids_csv"] or "").split(",") if value],
                        "work_relations": _edition_work_relations(connection, edition_id),
                        "identifier": row["identifier"], "translator": row["translator"],
                        "responsibility": row["responsibility"],
                        "other_title": row["other_title"],
                        "other_subtitle": row["other_subtitle"],
                        "translated_title": row["translated_title"],
                        "translated_subtitle": row["translated_subtitle"],
                        "edition_scripts": row["edition_scripts"],
                        "version": row["version"], "series": row["series"],
                        "publisher": row["publisher"],
                        "publisher_id": row["publisher_id"],
                        "publisher_canonical": row["publisher_canonical"],
                        "publication_year": publication_year_display(
                            row["publication_year"], row["publication_year_end"]
                        ),
                    }
                group = {
                    "id": edition_id,
                    "edition": edition_data,
                    "effective_metadata": resolve_metadata(work, edition_data, None),
                    "volumes": [],
                }
                by_edition[edition_id] = group
                editions.append(group)
            group = by_edition[edition_id]
            volume_id = row["volume_id"]
            if volume_id not in volume_groups:
                volume_record = _volume_record(row, work)
                volume_group = {
                    "id": volume_id,
                    "volume": volume_record,
                    "copies": [],
                }
                volume_groups[volume_id] = volume_group
                group["volumes"].append(volume_group)
            if row["copy_id"] is None:
                continue
            summary = {
                "id": row["copy_id"],
                "volume_id": volume_id,
                "acquisition_date": row["acquisition_date"],
                "location": row["location"],
                "reading_record": row["reading_record"],
            }
            volume_groups[volume_id]["copies"].append(summary)
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


def update_book(
    copy_id: int,
    book: BookInput,
    path: Path | None = None,
    *,
    overwrite_hierarchy: bool = False,
) -> dict | None:
    with transaction(path) as connection:
        old = connection.execute(
            """SELECT c.volume_id, v.edition_id
               FROM copies c
               JOIN volumes v ON v.id = c.volume_id
               WHERE c.id = ?""",
            (copy_id,),
        ).fetchone()
        if not old:
            return None
        work_id = _reuse_or_create_work(connection, book.work)
        edition_id, existing_edition = _reuse_or_create_edition(
            connection, work_id, book.edition
        )
        if overwrite_hierarchy:
            connection.execute(
                "UPDATE works SET title = ?, subtitle = ?, authors = ?, scripts = ? WHERE id = ?",
                (book.work.title, book.work.subtitle, book.work.authors, book.work.scripts, work_id),
            )
            _set_work_tags(
                connection, work_id, book.work.tag_ids, book.work.tag_names, True
            )
            publisher_id = _resolve_publisher(
                connection, book.edition.publisher, book.edition.publisher_id
            )
            year_start, year_end = publication_year_bounds(book.edition.publication_year)
            connection.execute(
                """UPDATE editions SET title = ?, subtitle = ?, identifier = ?, translator = ?,
                   responsibility = ?,
                   other_title = ?, other_subtitle = ?, translated_title = ?, translated_subtitle = ?,
                   edition_scripts = ?, version = ?, series = ?, publisher = ?, publisher_id = ?,
                   publication_year = ?, publication_year_end = ? WHERE id = ?""",
                (
                    book.edition.title, book.edition.subtitle, book.edition.identifier,
                    book.edition.translator, book.edition.responsibility, book.edition.other_title,
                    book.edition.other_subtitle, book.edition.translated_title,
                    book.edition.translated_subtitle, book.edition.edition_scripts,
                    book.edition.version, book.edition.series, book.edition.publisher,
                    publisher_id, year_start, year_end, edition_id,
                ),
            )
            if existing_edition is not None:
                _set_edition_work_relations(
                    connection, edition_id, _relations_from_input(work_id, book.edition)
                )

        requested_volume = (
            book.volume if overwrite_hierarchy else _volume_for_reused_edition(
                book.volume, book.edition, existing_edition
            )
        )
        if requested_volume.id is not None:
            belongs = connection.execute(
                "SELECT 1 FROM volumes WHERE id = ? AND edition_id = ?",
                (requested_volume.id, edition_id),
            ).fetchone()
            volume_id = (
                int(requested_volume.id)
                if belongs else _find_or_create_volume(
                    connection, edition_id,
                    requested_volume.model_copy(update={"id": None, "position": None}),
                )
            )
        else:
            volume_id = _find_or_create_volume(connection, edition_id, requested_volume)
        if overwrite_hierarchy:
            _update_volume_row(
                connection, volume_id,
                requested_volume.model_copy(update={"id": volume_id}),
            )
        if existing_edition is None:
            _set_edition_work_relations(
                connection, edition_id, _relations_from_input(work_id, book.edition),
                [volume_id],
            )
        connection.execute(
            """UPDATE copies SET volume_id = ?, acquisition_date = ?,
               location = ?, reading_record = ? WHERE id = ?""",
            (
                volume_id,
                book.copy_.acquisition_date.isoformat() if book.copy_.acquisition_date else None,
                book.copy_.location, book.copy_.reading_record, copy_id,
            ),
        )
    return get_book(copy_id, path)


def update_work_details(
    work_id: int, work: WorkInput, path: Path | None = None
) -> dict | None:
    with transaction(path) as connection:
        exists = connection.execute(
            "SELECT id FROM works WHERE id = ?", (work_id,)
        ).fetchone()
        if not exists:
            return None
        connection.execute(
            """UPDATE works SET title = ?, subtitle = ?, authors = ?, scripts = ?
               WHERE id = ?""",
            (work.title, work.subtitle, work.authors, work.scripts, work_id),
        )
        _set_work_tags(connection, work_id, work.tag_ids, work.tag_names, True)
        if work.edition_relations is not None:
            _set_work_edition_relations(
                connection, work_id, list(work.edition_relations)
            )
    return get_work(work_id, path)

def update_edition_details(
    edition_id: int, edition: EditionInput, path: Path | None = None
) -> dict | None:
    with transaction(path) as connection:
        current = connection.execute(
            "SELECT id FROM editions WHERE id = ?", (edition_id,)
        ).fetchone()
        if not current:
            return None
        publisher_id = _resolve_publisher(
            connection, edition.publisher, edition.publisher_id
        )
        year_start, year_end = publication_year_bounds(edition.publication_year)
        connection.execute(
            """UPDATE editions SET title = ?, subtitle = ?, identifier = ?, translator = ?,
               responsibility = ?,
               other_title = ?, other_subtitle = ?, translated_title = ?, translated_subtitle = ?,
               edition_scripts = ?, version = ?, series = ?, publisher = ?, publisher_id = ?,
               publication_year = ?, publication_year_end = ? WHERE id = ?""",
            (
                edition.title, edition.subtitle, edition.identifier, edition.translator,
                edition.responsibility,
                edition.other_title, edition.other_subtitle, edition.translated_title,
                edition.translated_subtitle, edition.edition_scripts, edition.version,
                edition.series, edition.publisher, publisher_id, year_start, year_end,
                edition_id,
            ),
        )
        if _use_structured_relations(edition):
            _set_edition_work_relations(
                connection, edition_id, edition.work_relations
            )
        elif edition.work_ids:
            _set_edition_works(connection, edition_id, edition.work_ids)
        result_work_ids = _edition_work_ids(connection, edition_id)
    return get_work(result_work_ids[0], path) if result_work_ids else None

def get_volume(volume_id: int, path: Path | None = None) -> dict | None:
    connection = connect(path)
    try:
        row = connection.execute(
            """SELECT v.*,
                      e.title AS edition_title, e.subtitle AS edition_subtitle,
                      e.translated_title, e.translated_subtitle,
                      e.edition_scripts, e.identifier AS edition_identifier,
                      e.version AS edition_version,
                      e.publication_year AS edition_publication_year,
                      e.publication_year_end AS edition_publication_year_end,
                      e.translator AS edition_translator,
                      e.responsibility AS edition_responsibility,
                      w.title AS work_title, w.subtitle AS work_subtitle,
                      w.authors AS work_authors, w.scripts AS work_scripts
               FROM volumes v
               JOIN editions e ON e.id = v.edition_id
               JOIN edition_works ew ON ew.edition_id = e.id
                 AND ew.position = (
                     SELECT MIN(ew_position.position)
                     FROM edition_works ew_position
                     WHERE ew_position.edition_id = e.id
                 )
               JOIN works w ON w.id = ew.work_id
               WHERE v.id = ?""",
            (volume_id,),
        ).fetchone()
        return _volume_from_row(row) if row else None
    finally:
        connection.close()


def create_volume_record(
    edition_id: int, volume: VolumeInput, path: Path | None = None
) -> dict:
    with transaction(path) as connection:
        if not connection.execute(
            "SELECT 1 FROM editions WHERE id = ?", (edition_id,)
        ).fetchone():
            raise ValueError("版本不存在")
        volume_id = _insert_volume(connection, edition_id, volume)
    record = get_volume(volume_id, path)
    assert record is not None
    return record


def update_volume_details(
    volume_id: int, volume: VolumeInput, path: Path | None = None
) -> dict | None:
    with transaction(path) as connection:
        if not connection.execute(
            "SELECT 1 FROM volumes WHERE id = ?", (volume_id,)
        ).fetchone():
            return None
        _update_volume_row(
            connection, volume_id, volume.model_copy(update={"id": volume_id})
        )
    return get_volume(volume_id, path)


def get_edition(edition_id: int, path: Path | None = None) -> dict | None:
    connection = connect(path)
    try:
        current = connection.execute(
            """SELECT ew.work_id FROM edition_works ew
               WHERE ew.edition_id = ? ORDER BY ew.position LIMIT 1""",
            (edition_id,),
        ).fetchone()
        if not current:
            return None
        work_rows = connection.execute(
            """SELECT w.id, w.title, w.subtitle, w.authors, w.scripts
               FROM works w JOIN edition_works ew ON ew.work_id = w.id
               WHERE ew.edition_id = ? ORDER BY ew.position""",
            (edition_id,),
        ).fetchall()
    finally:
        connection.close()
    detail = get_work(int(current["work_id"]), path)
    if detail is None:
        return None
    group = next(
        (item for item in detail["editions"] if item["id"] == edition_id), None
    )
    if group is None:
        return None
    return {
        **group,
        "works": [
            {
                "id": row["id"], "title": row["title"],
                "subtitle": row["subtitle"], "authors": row["authors"],
                "scripts": row["scripts"],
            }
            for row in work_rows
        ],
    }


def get_volume_detail(volume_id: int, path: Path | None = None) -> dict | None:
    volume = get_volume(volume_id, path)
    if volume is None:
        return None
    connection = connect(path)
    try:
        copies = [
            {
                "id": row["id"],
                "volume_id": volume_id,
                "edition_id": volume["edition_id"],
                "acquisition_date": row["acquisition_date"],
                "location": row["location"],
                "reading_record": row["reading_record"],
                "effective_metadata": volume["effective_metadata"],
            }
            for row in connection.execute(
                """SELECT id, acquisition_date, location, reading_record
                   FROM copies WHERE volume_id = ? ORDER BY id""",
                (volume_id,),
            ).fetchall()
        ]
    finally:
        connection.close()
    return {"id": volume_id, "volume": volume, "copies": copies}


def get_copy_details(copy_id: int, path: Path | None = None) -> dict | None:
    record = get_book(copy_id, path)
    if record is None:
        return None
    return {
        "id": record["id"],
        "volume_id": record["volume_id"],
        "edition_id": record["edition_id"],
        "acquisition_date": record["copy"]["acquisition_date"],
        "location": record["copy"]["location"],
        "reading_record": record["copy"]["reading_record"],
        "effective_metadata": record["volume"]["effective_metadata"],
    }


def create_copy_for_volume(
    volume_id: int, copy: CopyInput, path: Path | None = None
) -> dict:
    with transaction(path) as connection:
        if not connection.execute(
            "SELECT 1 FROM volumes WHERE id = ?", (volume_id,)
        ).fetchone():
            raise ValueError("冊不存在")
        copy_id = _insert_copy(connection, volume_id, copy)
    record = get_copy_details(copy_id, path)
    assert record is not None
    return record


def update_copy_details(
    copy_id: int, copy: CopyUpdateInput, path: Path | None = None
) -> dict | None:
    with transaction(path) as connection:
        current = connection.execute(
            "SELECT volume_id FROM copies WHERE id = ?", (copy_id,)
        ).fetchone()
        if not current:
            return None
        volume_id = copy.volume_id or current["volume_id"]
        if not connection.execute(
            "SELECT 1 FROM volumes WHERE id = ?", (volume_id,)
        ).fetchone():
            raise ValueError("指定的冊不存在")
        connection.execute(
            """UPDATE copies SET volume_id = ?, acquisition_date = ?,
               location = ?, reading_record = ? WHERE id = ?""",
            (
                volume_id,
                copy.acquisition_date.isoformat() if copy.acquisition_date else None,
                copy.location, copy.reading_record, copy_id,
            ),
        )
    return get_copy_details(copy_id, path)


def move_edition_identifier_to_volume(
    edition_id: int, volume_id: int, path: Path | None = None
) -> dict | None:
    with transaction(path) as connection:
        edition = connection.execute(
            "SELECT identifier FROM editions WHERE id = ?", (edition_id,)
        ).fetchone()
        if not edition:
            return None
        volume = connection.execute(
            "SELECT identifier FROM volumes WHERE id = ? AND edition_id = ?",
            (volume_id, edition_id),
        ).fetchone()
        if not volume:
            raise ValueError("指定的冊不屬於此版本")
        edition_identifier = str(edition["identifier"] or "").strip()
        volume_identifier = str(volume["identifier"] or "").strip()
        if not edition_identifier:
            raise ValueError("版本沒有可下沉的識別號")
        if volume_identifier and (
            volume_identifier.casefold() != edition_identifier.casefold()
        ):
            raise ValueError("冊已有不同識別號，請先明確解決衝突")
        connection.execute(
            "UPDATE volumes SET identifier = ? WHERE id = ?",
            (edition_identifier, volume_id),
        )
        connection.execute(
            "UPDATE editions SET identifier = '' WHERE id = ?", (edition_id,)
        )
    return get_edition(edition_id, path)

def delete_work(work_id: int, path: Path | None = None) -> bool:
    with transaction(path) as connection:
        if not connection.execute(
            "SELECT 1 FROM works WHERE id = ?", (work_id,)
        ).fetchone():
            return False
        edition_ids = [
            int(row["edition_id"])
            for row in connection.execute(
                "SELECT edition_id FROM edition_works WHERE work_id = ?",
                (work_id,),
            ).fetchall()
        ]
        for edition_id in edition_ids:
            link_count = int(connection.execute(
                "SELECT COUNT(*) FROM edition_works WHERE edition_id = ?",
                (edition_id,),
            ).fetchone()[0])
            if link_count == 1:
                connection.execute("DELETE FROM editions WHERE id = ?", (edition_id,))
            else:
                connection.execute(
                    "DELETE FROM edition_works WHERE edition_id = ? AND work_id = ?",
                    (edition_id, work_id),
                )
        connection.execute("DELETE FROM works WHERE id = ?", (work_id,))
        return True


def delete_edition(edition_id: int, path: Path | None = None) -> dict | None:
    with transaction(path) as connection:
        if not connection.execute(
            "SELECT 1 FROM editions WHERE id = ?", (edition_id,)
        ).fetchone():
            return None
        work_ids = _edition_work_ids(connection, edition_id)
        primary_work_id = work_ids[0] if work_ids else None
        connection.execute("DELETE FROM editions WHERE id = ?", (edition_id,))
        deleted_work_ids = []
        for work_id in work_ids:
            if connection.execute(
                """DELETE FROM works WHERE id = ?
                   AND NOT EXISTS (SELECT 1 FROM edition_works WHERE work_id = ?)""",
                (work_id, work_id),
            ).rowcount:
                deleted_work_ids.append(work_id)
        return {
            "work_id": primary_work_id,
            "work_deleted": primary_work_id in deleted_work_ids,
            "deleted_work_ids": deleted_work_ids,
        }



def delete_volume(volume_id: int, path: Path | None = None) -> dict | None:
    with transaction(path) as connection:
        current = connection.execute(
            "SELECT edition_id FROM volumes WHERE id = ?", (volume_id,)
        ).fetchone()
        if not current:
            return None
        relation = connection.execute(
            "SELECT 1 FROM edition_works WHERE volume_id = ? LIMIT 1",
            (volume_id,),
        ).fetchone()
        if relation:
            raise ValueError(
                "此冊仍由版本與作品的分冊關聯引用，請先調整進階結構"
            )
        copy_count = connection.execute(
            "SELECT COUNT(*) FROM copies WHERE volume_id = ?", (volume_id,)
        ).fetchone()[0]
        connection.execute("DELETE FROM volumes WHERE id = ?", (volume_id,))
        return {
            "edition_id": current["edition_id"],
            "deleted_copy_count": copy_count,
            "edition_retained": True,
        }

def delete_copy(copy_id: int, path: Path | None = None) -> dict | None:
    with transaction(path) as connection:
        current = connection.execute(
            """SELECT c.volume_id, v.edition_id,
                      (SELECT ew.work_id FROM edition_works ew
                       WHERE ew.edition_id = v.edition_id
                       ORDER BY ew.position LIMIT 1) AS work_id
               FROM copies c
               JOIN volumes v ON v.id = c.volume_id
               WHERE c.id = ?""",
            (copy_id,),
        ).fetchone()
        if not current:
            return None
        connection.execute("DELETE FROM copies WHERE id = ?", (copy_id,))
        remaining = connection.execute(
            "SELECT COUNT(*) FROM copies WHERE volume_id = ?", (current["volume_id"],)
        ).fetchone()[0]
        return {
            "work_id": current["work_id"],
            "edition_id": current["edition_id"],
            "volume_id": current["volume_id"],
            "volume_retained": True,
            "volume_copy_count": remaining,
            "edition_deleted": False,
            "work_deleted": False,
            "deleted_work_ids": [],
        }
