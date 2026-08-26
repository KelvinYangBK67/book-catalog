from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any


MIGRATION_NAME = "work-edition-volume-copy-v1"
CLEANUP_MIGRATION_NAME = "remove-legacy-three-layer-columns-v2"


def execute_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute SQL statement-by-statement inside the caller transaction."""
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            if sql:
                connection.execute(sql)
            statement = ""
    if statement.strip():
        raise ValueError("Incomplete SQL statement in migration script")


@dataclass
class VolumeMigrationReport:
    migration: str = MIGRATION_NAME
    migrated_copies: int = 0
    created_volumes: int = 0
    shared_volume_groups: int = 0
    identifier_conflicts: list[dict[str, Any]] = field(default_factory=list)
    ambiguous_relations: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _key(value: object) -> str:
    return str(value or "").strip().casefold()


def _merge_values(values: list[object]) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for value in str(raw or "").split(";"):
            value = value.strip()
            normalized = value.casefold()
            if value and normalized not in seen:
                seen.add(normalized)
                output.append(value)
    return "; ".join(output)


def _next_position(connection: sqlite3.Connection, edition_id: int) -> int:
    return int(connection.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM volumes WHERE edition_id = ?",
        (edition_id,),
    ).fetchone()[0])


def _create_volume(
    connection: sqlite3.Connection,
    edition_id: int,
    position: int,
    *,
    volume_number: str = "",
    volume_title: str = "",
    identifier: str = "",
) -> int:
    cursor = connection.execute(
        """INSERT INTO volumes
               (edition_id, position, volume_number, volume_title, identifier,
                version, publication_year, publication_year_end, responsibility)
           VALUES (?, ?, ?, ?, ?, '', NULL, NULL, '')""",
        (edition_id, position, volume_number, volume_title, identifier),
    )
    return int(cursor.lastrowid)


def _create_volume_schema(connection: sqlite3.Connection) -> None:
    execute_script(
        connection,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            report_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS volumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edition_id INTEGER NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            volume_number TEXT NOT NULL DEFAULT '',
            volume_title TEXT NOT NULL DEFAULT '',
            identifier TEXT NOT NULL DEFAULT '',
            version TEXT NOT NULL DEFAULT '',
            publication_year INTEGER,
            publication_year_end INTEGER,
            responsibility TEXT NOT NULL DEFAULT '',
            UNIQUE (edition_id, position),
            CHECK (position >= 0),
            CHECK (publication_year IS NULL OR publication_year BETWEEN 0 AND 9999),
            CHECK (publication_year_end IS NULL OR publication_year_end BETWEEN 0 AND 9999)
        );

        CREATE INDEX IF NOT EXISTS idx_volumes_edition
            ON volumes(edition_id, position);
        CREATE INDEX IF NOT EXISTS idx_volumes_identifier
            ON volumes(identifier);
        """
    )


def prepare_legacy_schema(connection: sqlite3.Connection) -> None:
    """Normalize known legacy columns for the versioned four-layer migration."""
    work_columns = {row["name"] for row in connection.execute("PRAGMA table_info(works)")}
    if "subtitle" not in work_columns:
        connection.execute("ALTER TABLE works ADD COLUMN subtitle TEXT NOT NULL DEFAULT ''")
    if "scripts" not in work_columns:
        connection.execute("ALTER TABLE works ADD COLUMN scripts TEXT NOT NULL DEFAULT ''")
    if "language" in work_columns:
        connection.execute("UPDATE works SET scripts = language WHERE scripts = ''")

    edition_columns = {row["name"] for row in connection.execute("PRAGMA table_info(editions)")}
    text_columns = {
        "title": "", "subtitle": "", "version": "", "identifier": "",
        "other_title": "", "other_subtitle": "", "edition_scripts": "",
        "series": "",
    }
    for name in text_columns:
        if name not in edition_columns:
            connection.execute(
                f"ALTER TABLE editions ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"
            )
    edition_columns = {row["name"] for row in connection.execute("PRAGMA table_info(editions)")}
    if "isbn" in edition_columns:
        connection.execute("UPDATE editions SET identifier = isbn WHERE identifier = ''")
    if "translation_script" in edition_columns:
        connection.execute(
            "UPDATE editions SET edition_scripts = translation_script WHERE edition_scripts = ''"
        )
    if "translation_language" in edition_columns:
        connection.execute(
            "UPDATE editions SET edition_scripts = translation_language WHERE edition_scripts = ''"
        )
    if "publisher_id" not in edition_columns:
        connection.execute(
            "ALTER TABLE editions ADD COLUMN publisher_id INTEGER REFERENCES publishers(id) ON DELETE SET NULL"
        )
    if "publication_year_end" not in edition_columns:
        connection.execute("ALTER TABLE editions ADD COLUMN publication_year_end INTEGER")
    if "force_separate" not in edition_columns:
        connection.execute(
            "ALTER TABLE editions ADD COLUMN force_separate INTEGER NOT NULL DEFAULT 0"
        )

    copy_columns = {row["name"] for row in connection.execute("PRAGMA table_info(copies)")}
    if "edition_id" in copy_columns:
        if "volume_number" not in copy_columns:
            connection.execute(
                "ALTER TABLE copies ADD COLUMN volume_number TEXT NOT NULL DEFAULT ''"
            )
        if "volume_title" not in copy_columns:
            connection.execute(
                "ALTER TABLE copies ADD COLUMN volume_title TEXT NOT NULL DEFAULT ''"
            )
        if "identifier" not in copy_columns:
            connection.execute(
                "ALTER TABLE copies ADD COLUMN identifier TEXT NOT NULL DEFAULT ''"
            )
        copy_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(copies)")
        }
        if "volume" in copy_columns:
            connection.execute(
                "UPDATE copies SET volume_number = volume WHERE volume_number = ''"
            )
        if "volume" in edition_columns:
            connection.execute(
                """UPDATE copies SET volume_number = COALESCE(
                       (SELECT e.volume FROM editions e WHERE e.id = copies.edition_id), '')
                   WHERE volume_number = ''"""
            )

    relation_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(edition_works)")
    }
    if "relation_type" not in relation_columns:
        connection.execute(
            "ALTER TABLE edition_works ADD COLUMN relation_type TEXT NOT NULL DEFAULT 'contained' "
            "CHECK (relation_type IN ('volume', 'contained'))"
        )
    if "volume_id" not in relation_columns and "volume_number" not in relation_columns:
        connection.execute(
            "ALTER TABLE edition_works ADD COLUMN volume_number TEXT NOT NULL DEFAULT ''"
        )

    current_edition_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(editions)")
    }
    if "work_id" in current_edition_columns:
        if "volume_id" in {
            row["name"] for row in connection.execute("PRAGMA table_info(edition_works)")
        }:
            connection.execute(
                """INSERT OR IGNORE INTO edition_works
                       (edition_id, work_id, position, relation_type, volume_id)
                   SELECT id, work_id, 0, 'contained', NULL FROM editions"""
            )
        else:
            connection.execute(
                """INSERT OR IGNORE INTO edition_works
                       (edition_id, work_id, position, relation_type, volume_number)
                   SELECT id, work_id, 0, 'contained', '' FROM editions"""
            )



def _stored_report(connection: sqlite3.Connection) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT report_json FROM schema_migrations WHERE name = ?", (MIGRATION_NAME,)
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["report_json"])
    except (TypeError, json.JSONDecodeError):
        return {"migration": MIGRATION_NAME}


def migrate_volume_model(connection: sqlite3.Connection) -> dict[str, Any]:
    """Migrate the legacy Edition -> Copy layout inside the caller's transaction."""
    _create_volume_schema(connection)
    copy_columns = _columns(connection, "copies")
    relation_columns = _columns(connection, "edition_works")
    already_modern = (
        "volume_id" in copy_columns
        and "edition_id" not in copy_columns
        and "volume_id" in relation_columns
        and "volume_number" not in relation_columns
    )
    if already_modern:
        stored = _stored_report(connection)
        if stored is not None:
            return stored
        report = VolumeMigrationReport().as_dict()
        connection.execute(
            """INSERT INTO schema_migrations (name, report_json)
               VALUES (?, ?)""",
            (MIGRATION_NAME, json.dumps(report, ensure_ascii=False, sort_keys=True)),
        )
        return report

    report = VolumeMigrationReport()
    connection.execute("PRAGMA defer_foreign_keys = ON")

    legacy_copies = connection.execute(
        """SELECT id, edition_id,
                  COALESCE(volume_number, '') AS volume_number,
                  COALESCE(volume_title, '') AS volume_title,
                  COALESCE(identifier, '') AS identifier,
                  acquisition_date, location, reading_record
           FROM copies ORDER BY edition_id, id"""
    ).fetchall()

    copy_groups: dict[tuple[int, str, str], list[sqlite3.Row]] = {}
    for copy in legacy_copies:
        key = (
            int(copy["edition_id"]),
            _key(copy["volume_number"]),
            _key(copy["volume_title"]),
        )
        copy_groups.setdefault(key, []).append(copy)

    copy_volume_ids: dict[int, int] = {}
    volume_ids_by_edition_number: dict[tuple[int, str], list[int]] = {}
    for (edition_id, _, _), copies in copy_groups.items():
        identifiers = _merge_values([copy["identifier"] for copy in copies])
        distinct_identifiers = {
            _key(copy["identifier"]) for copy in copies if _key(copy["identifier"])
        }
        if len(copies) > 1:
            report.shared_volume_groups += 1
        if len(distinct_identifiers) > 1:
            report.identifier_conflicts.append({
                "edition_id": edition_id,
                "copy_ids": [copy["id"] for copy in copies],
                "identifiers": [
                    value for value in identifiers.split("; ") if value
                ],
                "resolution": "preserved as multiple Volume identifiers",
            })
        representative = copies[0]
        volume_id = _create_volume(
            connection,
            edition_id,
            _next_position(connection, edition_id),
            volume_number=str(representative["volume_number"] or "").strip(),
            volume_title=str(representative["volume_title"] or "").strip(),
            identifier=identifiers,
        )
        report.created_volumes += 1
        volume_ids_by_edition_number.setdefault(
            (edition_id, _key(representative["volume_number"])), []
        ).append(volume_id)
        for copy in copies:
            copy_volume_ids[int(copy["id"])] = volume_id

    for edition in connection.execute("SELECT id FROM editions ORDER BY id").fetchall():
        has_volume = connection.execute(
            "SELECT 1 FROM volumes WHERE edition_id = ? LIMIT 1", (edition["id"],)
        ).fetchone()
        if not has_volume:
            _create_volume(connection, edition["id"], 0)
            report.created_volumes += 1

    execute_script(
        connection,
        """
        DROP TABLE IF EXISTS copies_volume_migration;
        CREATE TABLE copies_volume_migration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            volume_id INTEGER NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
            acquisition_date TEXT,
            location TEXT NOT NULL DEFAULT '',
            reading_record TEXT NOT NULL DEFAULT ''
        );
        """
    )
    connection.executemany(
        """INSERT INTO copies_volume_migration
               (id, volume_id, acquisition_date, location, reading_record)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (
                copy["id"], copy_volume_ids[int(copy["id"])],
                copy["acquisition_date"], copy["location"], copy["reading_record"],
            )
            for copy in legacy_copies
        ],
    )
    report.migrated_copies = len(legacy_copies)
    connection.execute("DROP TABLE copies")
    connection.execute("ALTER TABLE copies_volume_migration RENAME TO copies")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_copies_volume ON copies(volume_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_copies_location ON copies(location)")

    legacy_relations = connection.execute(
        """SELECT edition_id, work_id, position, relation_type,
                  COALESCE(volume_number, '') AS volume_number
           FROM edition_works ORDER BY edition_id, position"""
    ).fetchall()
    execute_script(
        connection,
        """
        DROP TABLE IF EXISTS edition_works_volume_migration;
        CREATE TABLE edition_works_volume_migration (
            edition_id INTEGER NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
            work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
            position INTEGER NOT NULL DEFAULT 0,
            relation_type TEXT NOT NULL DEFAULT 'contained'
                CHECK (relation_type IN ('volume', 'contained')),
            volume_id INTEGER REFERENCES volumes(id) ON DELETE RESTRICT,
            PRIMARY KEY (edition_id, work_id),
            UNIQUE (edition_id, position),
            CHECK (position >= 0),
            CHECK (
                (relation_type = 'volume' AND volume_id IS NOT NULL)
                OR (relation_type = 'contained' AND volume_id IS NULL)
            )
        );
        """
    )
    relation_values: list[tuple[int, int, int, str, int | None]] = []
    for relation in legacy_relations:
        relation_type = str(relation["relation_type"] or "contained")
        volume_id: int | None = None
        if relation_type == "volume":
            candidates = volume_ids_by_edition_number.get(
                (int(relation["edition_id"]), _key(relation["volume_number"])), []
            )
            if len(candidates) == 1:
                volume_id = candidates[0]
            else:
                volume_id = _create_volume(
                    connection,
                    int(relation["edition_id"]),
                    _next_position(connection, int(relation["edition_id"])),
                    volume_number=str(relation["volume_number"] or "").strip(),
                )
                report.created_volumes += 1
                if len(candidates) > 1:
                    report.ambiguous_relations.append({
                        "edition_id": relation["edition_id"],
                        "work_id": relation["work_id"],
                        "legacy_volume_number": relation["volume_number"],
                        "candidate_volume_ids": candidates,
                        "resolution": "created a relation-only Volume rather than guessing",
                    })
        relation_values.append((
            relation["edition_id"], relation["work_id"], relation["position"],
            relation_type, volume_id,
        ))
    connection.executemany(
        """INSERT INTO edition_works_volume_migration
               (edition_id, work_id, position, relation_type, volume_id)
           VALUES (?, ?, ?, ?, ?)""",
        relation_values,
    )
    connection.execute("DROP TABLE edition_works")
    connection.execute(
        "ALTER TABLE edition_works_volume_migration RENAME TO edition_works"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_edition_works_work ON edition_works(work_id, position)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_edition_works_volume ON edition_works(volume_id)"
    )

    report_json = json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True)
    connection.execute(
        """INSERT OR REPLACE INTO schema_migrations (name, report_json)
           VALUES (?, ?)""",
        (MIGRATION_NAME, report_json),
    )
    return report.as_dict()

def cleanup_legacy_schema(connection: sqlite3.Connection) -> dict[str, Any]:
    """Remove migrated three-layer columns; legacy readers live in adapters."""
    _create_volume_schema(connection)
    stored = connection.execute(
        "SELECT report_json FROM schema_migrations WHERE name = ?",
        (CLEANUP_MIGRATION_NAME,),
    ).fetchone()
    if stored:
        try:
            return json.loads(stored["report_json"])
        except (TypeError, json.JSONDecodeError):
            return {"migration": CLEANUP_MIGRATION_NAME}

    removed: dict[str, list[str]] = {"works": [], "editions": []}
    if "work_id" in _columns(connection, "editions"):
        connection.execute(
            """INSERT OR IGNORE INTO edition_works
                   (edition_id, work_id, position, relation_type, volume_id)
               SELECT id, work_id, 0, 'contained', NULL FROM editions"""
        )
        connection.execute("ALTER TABLE editions DROP COLUMN work_id")
        removed["editions"].append("work_id")

    for column in (
        "volume", "isbn", "translation_language", "translation_script"
    ):
        if column in _columns(connection, "editions"):
            if column == "isbn":
                connection.execute("DROP INDEX IF EXISTS idx_editions_isbn")
            connection.execute(f"ALTER TABLE editions DROP COLUMN {column}")
            removed["editions"].append(column)

    if "language" in _columns(connection, "works"):
        connection.execute("ALTER TABLE works DROP COLUMN language")
        removed["works"].append("language")

    report = {"migration": CLEANUP_MIGRATION_NAME, "removed_columns": removed}
    connection.execute(
        """INSERT INTO schema_migrations (name, report_json)
           VALUES (?, ?)""",
        (CLEANUP_MIGRATION_NAME, json.dumps(report, ensure_ascii=False, sort_keys=True)),
    )
    return report


def ensure_integrity_guards(connection: sqlite3.Connection) -> None:
    """Install cross-table invariants that SQLite CHECK cannot express."""
    execute_script(
        connection,
        """
        CREATE TRIGGER IF NOT EXISTS trg_edition_works_volume_same_edition_insert
        BEFORE INSERT ON edition_works
        WHEN NEW.relation_type = 'volume'
         AND NOT EXISTS (
             SELECT 1 FROM volumes v
             WHERE v.id = NEW.volume_id AND v.edition_id = NEW.edition_id
         )
        BEGIN
            SELECT RAISE(ABORT, 'edition_works volume must belong to the same edition');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_edition_works_volume_same_edition_update
        BEFORE UPDATE OF edition_id, relation_type, volume_id ON edition_works
        WHEN NEW.relation_type = 'volume'
         AND NOT EXISTS (
             SELECT 1 FROM volumes v
             WHERE v.id = NEW.volume_id AND v.edition_id = NEW.edition_id
         )
        BEGIN
            SELECT RAISE(ABORT, 'edition_works volume must belong to the same edition');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_volume_edition_relation_guard
        BEFORE UPDATE OF edition_id ON volumes
        WHEN EXISTS (
            SELECT 1 FROM edition_works ew
            WHERE ew.volume_id = OLD.id AND ew.edition_id <> NEW.edition_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'linked volume cannot move to another edition');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_edition_works_position_insert
        BEFORE INSERT ON edition_works
        WHEN NEW.position < 0
        BEGIN
            SELECT RAISE(ABORT, 'edition_works position must be nonnegative');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_edition_works_position_update
        BEFORE UPDATE OF position ON edition_works
        WHEN NEW.position < 0
        BEGIN
            SELECT RAISE(ABORT, 'edition_works position must be nonnegative');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_volumes_position_insert
        BEFORE INSERT ON volumes
        WHEN NEW.position < 0
        BEGIN
            SELECT RAISE(ABORT, 'volume position must be nonnegative');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_volumes_position_update
        BEFORE UPDATE OF position ON volumes
        WHEN NEW.position < 0
        BEGIN
            SELECT RAISE(ABORT, 'volume position must be nonnegative');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_editions_year_order_insert
        BEFORE INSERT ON editions
        WHEN NEW.publication_year IS NOT NULL
         AND NEW.publication_year_end IS NOT NULL
         AND NEW.publication_year_end < NEW.publication_year
        BEGIN
            SELECT RAISE(ABORT, 'edition publication year range is reversed');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_editions_year_order_update
        BEFORE UPDATE OF publication_year, publication_year_end ON editions
        WHEN NEW.publication_year IS NOT NULL
         AND NEW.publication_year_end IS NOT NULL
         AND NEW.publication_year_end < NEW.publication_year
        BEGIN
            SELECT RAISE(ABORT, 'edition publication year range is reversed');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_volumes_year_order_insert
        BEFORE INSERT ON volumes
        WHEN NEW.publication_year IS NOT NULL
         AND NEW.publication_year_end IS NOT NULL
         AND NEW.publication_year_end < NEW.publication_year
        BEGIN
            SELECT RAISE(ABORT, 'volume publication year range is reversed');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_volumes_year_order_update
        BEFORE UPDATE OF publication_year, publication_year_end ON volumes
        WHEN NEW.publication_year IS NOT NULL
         AND NEW.publication_year_end IS NOT NULL
         AND NEW.publication_year_end < NEW.publication_year
        BEGIN
            SELECT RAISE(ABORT, 'volume publication year range is reversed');
        END;
        """,
    )
