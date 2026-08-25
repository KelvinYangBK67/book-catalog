from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .edition_matching import find_matching_edition


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
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(path: Path | None = None) -> None:
    with transaction(path) as connection:
        connection.executescript(
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
                work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
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
                CHECK (publication_year_end IS NULL OR publication_year_end BETWEEN 0 AND 9999)
            );

            CREATE TABLE IF NOT EXISTS edition_works (
                edition_id INTEGER NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
                work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                position INTEGER NOT NULL DEFAULT 0,
                relation_type TEXT NOT NULL DEFAULT 'contained'
                    CHECK (relation_type IN ('volume', 'contained')),
                volume_number TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (edition_id, work_id),
                UNIQUE (edition_id, position)
            );

            CREATE TABLE IF NOT EXISTS copies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edition_id INTEGER NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
                volume_number TEXT NOT NULL DEFAULT '',
                volume_title TEXT NOT NULL DEFAULT '',
                identifier TEXT NOT NULL DEFAULT '',
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
            CREATE INDEX IF NOT EXISTS idx_edition_works_work ON edition_works(work_id, position);
            CREATE INDEX IF NOT EXISTS idx_editions_publisher ON editions(publisher);
            CREATE INDEX IF NOT EXISTS idx_publisher_aliases_publisher ON publisher_aliases(publisher_id);
            CREATE INDEX IF NOT EXISTS idx_copies_location ON copies(location);
            CREATE INDEX IF NOT EXISTS idx_tags_parent ON tags(parent_id);
            CREATE INDEX IF NOT EXISTS idx_work_tags_tag ON work_tags(tag_id);
            """
        )
        work_columns = {row["name"] for row in connection.execute("PRAGMA table_info(works)")}
        if "subtitle" not in work_columns:
            connection.execute("ALTER TABLE works ADD COLUMN subtitle TEXT NOT NULL DEFAULT ''")
        if "scripts" not in work_columns:
            connection.execute("ALTER TABLE works ADD COLUMN scripts TEXT NOT NULL DEFAULT ''")
        if "language" in work_columns:
            connection.execute("UPDATE works SET scripts = language WHERE scripts = ''")

        edition_columns = {row["name"] for row in connection.execute("PRAGMA table_info(editions)")}
        if "title" not in edition_columns:
            connection.execute("ALTER TABLE editions ADD COLUMN title TEXT NOT NULL DEFAULT ''")
        if "subtitle" not in edition_columns:
            connection.execute("ALTER TABLE editions ADD COLUMN subtitle TEXT NOT NULL DEFAULT ''")
        if "version" not in edition_columns:
            connection.execute("ALTER TABLE editions ADD COLUMN version TEXT NOT NULL DEFAULT ''")
        if "identifier" not in edition_columns:
            connection.execute("ALTER TABLE editions ADD COLUMN identifier TEXT NOT NULL DEFAULT ''")
        if "isbn" in edition_columns:
            connection.execute("UPDATE editions SET identifier = isbn WHERE identifier = ''")
        if "other_title" not in edition_columns:
            connection.execute("ALTER TABLE editions ADD COLUMN other_title TEXT NOT NULL DEFAULT ''")
        if "other_subtitle" not in edition_columns:
            connection.execute("ALTER TABLE editions ADD COLUMN other_subtitle TEXT NOT NULL DEFAULT ''")
        if "edition_scripts" not in edition_columns:
            connection.execute("ALTER TABLE editions ADD COLUMN edition_scripts TEXT NOT NULL DEFAULT ''")
        if "translation_script" in edition_columns:
            connection.execute(
                "UPDATE editions SET edition_scripts = translation_script WHERE edition_scripts = ''"
            )
        if "translation_language" in edition_columns:
            connection.execute(
                "UPDATE editions SET edition_scripts = translation_language WHERE edition_scripts = ''"
            )
        if "publisher_id" not in edition_columns:
            connection.execute("ALTER TABLE editions ADD COLUMN publisher_id INTEGER REFERENCES publishers(id) ON DELETE SET NULL")
        if "publication_year_end" not in edition_columns:
            connection.execute("ALTER TABLE editions ADD COLUMN publication_year_end INTEGER")
        if "force_separate" not in edition_columns:
            connection.execute("ALTER TABLE editions ADD COLUMN force_separate INTEGER NOT NULL DEFAULT 0")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_editions_identifier ON editions(identifier)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_editions_publisher_id ON editions(publisher_id)")

        copy_columns = {row["name"] for row in connection.execute("PRAGMA table_info(copies)")}
        if "volume_number" not in copy_columns:
            connection.execute("ALTER TABLE copies ADD COLUMN volume_number TEXT NOT NULL DEFAULT ''")
        if "volume_title" not in copy_columns:
            connection.execute("ALTER TABLE copies ADD COLUMN volume_title TEXT NOT NULL DEFAULT ''")
        if "identifier" not in copy_columns:
            connection.execute("ALTER TABLE copies ADD COLUMN identifier TEXT NOT NULL DEFAULT ''")
        if "volume" in copy_columns:
            connection.execute("UPDATE copies SET volume_number = volume WHERE volume_number = ''")
        if "volume" in edition_columns:
            connection.execute(
                """UPDATE copies SET volume_number = COALESCE(
                       (SELECT e.volume FROM editions e WHERE e.id = copies.edition_id), '')
                   WHERE volume_number = ''"""
            )
            connection.execute("ALTER TABLE editions DROP COLUMN volume")
        if "isbn" in edition_columns:
            connection.execute("DROP INDEX IF EXISTS idx_editions_isbn")
            connection.execute("ALTER TABLE editions DROP COLUMN isbn")
        if "translation_language" in edition_columns:
            connection.execute("ALTER TABLE editions DROP COLUMN translation_language")
        if "language" in work_columns:
            connection.execute("ALTER TABLE works DROP COLUMN language")

        edition_columns = {row['name'] for row in connection.execute('PRAGMA table_info(editions)')}
        if 'series' not in edition_columns:
            connection.execute('ALTER TABLE editions ADD COLUMN series TEXT NOT NULL DEFAULT \'\'')

        edition_work_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(edition_works)")
        }
        if "relation_type" not in edition_work_columns:
            connection.execute(
                "ALTER TABLE edition_works ADD COLUMN relation_type TEXT NOT NULL DEFAULT 'contained' "
                "CHECK (relation_type IN ('volume', 'contained'))"
            )
        if "volume_number" not in edition_work_columns:
            connection.execute(
                "ALTER TABLE edition_works ADD COLUMN volume_number TEXT NOT NULL DEFAULT ''"
            )

        connection.execute(
            """INSERT OR IGNORE INTO edition_works (edition_id, work_id, position)
               SELECT id, work_id, 0 FROM editions"""
        )

        works = connection.execute(
            "SELECT id, title, subtitle, authors, scripts FROM works ORDER BY id"
        ).fetchall()
        canonical_works: dict[tuple[str, str], int] = {}
        for work in works:
            key = (work["title"].strip().casefold(), work["authors"].strip().casefold())
            canonical_id = canonical_works.get(key)
            if canonical_id is None:
                canonical_works[key] = work["id"]
                connection.execute(
                    "UPDATE works SET title = ?, subtitle = ?, authors = ?, scripts = ? WHERE id = ?",
                    (
                        work["title"].strip(), work["subtitle"].strip(),
                        work["authors"].strip(), work["scripts"].strip(), work["id"],
                    ),
                )
                continue
            connection.execute(
                """UPDATE works SET
                       subtitle = CASE WHEN subtitle = '' THEN ? ELSE subtitle END,
                       scripts = CASE WHEN scripts = '' THEN ? ELSE scripts END
                   WHERE id = ?""",
                (work["subtitle"].strip(), work["scripts"].strip(), canonical_id),
            )
            for link in connection.execute(
                "SELECT edition_id FROM edition_works WHERE work_id = ? ORDER BY edition_id",
                (work["id"],),
            ).fetchall():
                existing_link = connection.execute(
                    "SELECT 1 FROM edition_works WHERE edition_id = ? AND work_id = ?",
                    (link["edition_id"], canonical_id),
                ).fetchone()
                if existing_link:
                    connection.execute(
                        "DELETE FROM edition_works WHERE edition_id = ? AND work_id = ?",
                        (link["edition_id"], work["id"]),
                    )
                else:
                    connection.execute(
                        "UPDATE edition_works SET work_id = ? WHERE edition_id = ? AND work_id = ?",
                        (canonical_id, link["edition_id"], work["id"]),
                    )
            connection.execute(
                "UPDATE editions SET work_id = ? WHERE work_id = ?",
                (canonical_id, work["id"]),
            )
            connection.execute(
                "INSERT OR IGNORE INTO work_tags (work_id, tag_id) SELECT ?, tag_id FROM work_tags WHERE work_id = ?",
                (canonical_id, work["id"]),
            )
            connection.execute("DELETE FROM works WHERE id = ?", (work["id"],))

        editions = connection.execute(
            """SELECT id, work_id, title, subtitle, identifier, translator, other_title, other_subtitle,
                      translated_title, translated_subtitle, edition_scripts, version, series, publisher, publisher_id,
                      publication_year, publication_year_end, force_separate
               FROM editions ORDER BY id"""
        ).fetchall()
        canonical_editions: dict[int, list[sqlite3.Row]] = {}
        for edition in editions:
            candidates = canonical_editions.setdefault(edition["work_id"], [])
            canonical = find_matching_edition(candidates, edition)
            if canonical is None:
                candidates.append(edition)
                continue
            canonical_id = canonical["id"]
            identifiers: list[str] = []
            seen_identifiers: set[str] = set()
            for raw_identifier in (canonical["identifier"], edition["identifier"]):
                for identifier in str(raw_identifier or "").split(";"):
                    identifier = identifier.strip()
                    key = identifier.casefold()
                    if identifier and key not in seen_identifiers:
                        seen_identifiers.add(key)
                        identifiers.append(identifier)
            years = [
                year for year in (
                    canonical["publication_year"], canonical["publication_year_end"],
                    edition["publication_year"], edition["publication_year_end"],
                )
                if year is not None
            ]
            merged_year_start = min(years) if years else None
            merged_year_end = max(years) if years else None
            connection.execute(
                """UPDATE editions SET
                       title = CASE WHEN title = '' THEN ? ELSE title END,
                       subtitle = CASE WHEN subtitle = '' THEN ? ELSE subtitle END,
                       identifier = ?,
                       translator = CASE WHEN translator = '' THEN ? ELSE translator END,
                       other_title = CASE WHEN other_title = '' THEN ? ELSE other_title END,
                       other_subtitle = CASE WHEN other_subtitle = '' THEN ? ELSE other_subtitle END,
                       translated_title = CASE WHEN translated_title = '' THEN ? ELSE translated_title END,
                       translated_subtitle = CASE WHEN translated_subtitle = '' THEN ? ELSE translated_subtitle END,
                       edition_scripts = CASE WHEN edition_scripts = '' THEN ? ELSE edition_scripts END,
                       series = CASE WHEN series = '' THEN ? ELSE series END,
                       publisher = CASE WHEN publisher = '' THEN ? ELSE publisher END,
                       publisher_id = COALESCE(publisher_id, ?),
                       publication_year = ?,
                       publication_year_end = ?
                   WHERE id = ?""",
                (
                    edition["title"], edition["subtitle"],
                    "; ".join(identifiers), edition["translator"], edition["other_title"], edition["other_subtitle"],
                    edition["translated_title"], edition["translated_subtitle"],
                    edition["edition_scripts"], edition["series"],
                    edition["publisher"], edition["publisher_id"],
                    merged_year_start, merged_year_end, canonical_id,
                ),
            )
            for link in connection.execute(
                """SELECT work_id, relation_type, volume_number
                   FROM edition_works WHERE edition_id = ? ORDER BY position""",
                (edition["id"],),
            ).fetchall():
                if connection.execute(
                    "SELECT 1 FROM edition_works WHERE edition_id = ? AND work_id = ?",
                    (canonical_id, link["work_id"]),
                ).fetchone():
                    continue
                position = connection.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM edition_works WHERE edition_id = ?",
                    (canonical_id,),
                ).fetchone()[0]
                connection.execute(
                    """INSERT INTO edition_works
                           (edition_id, work_id, position, relation_type, volume_number)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        canonical_id, link["work_id"], position,
                        link["relation_type"], link["volume_number"],
                    ),
                )
            connection.execute(
                "UPDATE copies SET edition_id = ? WHERE edition_id = ?",
                (canonical_id, edition["id"]),
            )
            connection.execute("DELETE FROM editions WHERE id = ?", (edition["id"],))
