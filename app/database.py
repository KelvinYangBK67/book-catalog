from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .migrations import (
    cleanup_legacy_schema, ensure_integrity_guards, execute_script,
    migrate_volume_model, prepare_legacy_schema,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "library.db"


def database_path() -> Path:
    configured = os.getenv("LIBRARY_DATABASE")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DATABASE


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def transaction(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(path: Path | None = None) -> dict[str, Any]:
    """Create current tables and apply versioned structural migrations atomically."""
    with transaction(path) as connection:
        execute_script(
            connection,
            """
            CREATE TABLE IF NOT EXISTS works (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subtitle TEXT NOT NULL DEFAULT '',
                authors TEXT NOT NULL DEFAULT '',
                scripts TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS publishers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT NOT NULL COLLATE NOCASE UNIQUE
            );

            CREATE TABLE IF NOT EXISTS publisher_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publisher_id INTEGER NOT NULL REFERENCES publishers(id) ON DELETE CASCADE,
                alias TEXT NOT NULL COLLATE NOCASE UNIQUE
            );

            CREATE TABLE IF NOT EXISTS editions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '',
                subtitle TEXT NOT NULL DEFAULT '',
                identifier TEXT NOT NULL DEFAULT '',
                translator TEXT NOT NULL DEFAULT '',
                other_title TEXT NOT NULL DEFAULT '',
                other_subtitle TEXT NOT NULL DEFAULT '',
                translated_title TEXT NOT NULL DEFAULT '',
                translated_subtitle TEXT NOT NULL DEFAULT '',
                edition_scripts TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL DEFAULT '',
                series TEXT NOT NULL DEFAULT '',
                publisher TEXT NOT NULL DEFAULT '',
                publisher_id INTEGER REFERENCES publishers(id) ON DELETE SET NULL,
                publication_year INTEGER,
                publication_year_end INTEGER,
                force_separate INTEGER NOT NULL DEFAULT 0,
                CHECK (publication_year IS NULL OR publication_year BETWEEN 0 AND 9999),
                CHECK (publication_year_end IS NULL OR publication_year_end BETWEEN 0 AND 9999),
                CHECK (publication_year_end IS NULL OR publication_year IS NULL
                       OR publication_year_end >= publication_year)
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
                CHECK (publication_year_end IS NULL OR publication_year_end BETWEEN 0 AND 9999),
                CHECK (publication_year_end IS NULL OR publication_year IS NULL
                       OR publication_year_end >= publication_year)
            );

            CREATE TABLE IF NOT EXISTS edition_works (
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

            CREATE TABLE IF NOT EXISTS copies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                volume_id INTEGER NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
                acquisition_date TEXT,
                location TEXT NOT NULL DEFAULT '',
                reading_record TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                parent_id INTEGER REFERENCES tags(id) ON DELETE RESTRICT,
                UNIQUE(parent_id, name)
            );

            CREATE TABLE IF NOT EXISTS work_tags (
                work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY (work_id, tag_id)
            );

            CREATE INDEX IF NOT EXISTS idx_works_title ON works(title);
            CREATE INDEX IF NOT EXISTS idx_editions_identifier ON editions(identifier);
            CREATE INDEX IF NOT EXISTS idx_editions_publisher ON editions(publisher);
            CREATE INDEX IF NOT EXISTS idx_editions_publisher_id ON editions(publisher_id);
            CREATE INDEX IF NOT EXISTS idx_volumes_edition ON volumes(edition_id, position);
            CREATE INDEX IF NOT EXISTS idx_volumes_identifier ON volumes(identifier);
            CREATE INDEX IF NOT EXISTS idx_edition_works_work ON edition_works(work_id, position);
            CREATE INDEX IF NOT EXISTS idx_publisher_aliases_publisher ON publisher_aliases(publisher_id);
            CREATE INDEX IF NOT EXISTS idx_copies_location ON copies(location);
            CREATE INDEX IF NOT EXISTS idx_tags_parent ON tags(parent_id);
            CREATE INDEX IF NOT EXISTS idx_work_tags_tag ON work_tags(tag_id);
            """
        )

        prepare_legacy_schema(connection)

        report = migrate_volume_model(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_edition_works_volume ON edition_works(volume_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_copies_volume ON copies(volume_id)"
        )

        cleanup_legacy_schema(connection)
        ensure_integrity_guards(connection)

        return report
