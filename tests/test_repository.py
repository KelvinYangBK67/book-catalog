from __future__ import annotations

import tempfile
import unittest
import sqlite3
from datetime import date
from pathlib import Path

from app.database import connect, initialize
from app.repository import (
    create_book, create_books_batch, create_copy_for_volume, create_tag,
    create_volume_record, create_work_record, delete_copy, delete_edition, delete_publisher, delete_volume,
    delete_tag, delete_work, get_book, get_work, list_books, list_editions, list_publishers,
    list_tag_violations, list_tags, list_works, move_edition_identifier_to_volume,
    normalize_publisher, update_book,
    update_copy_details, update_edition_details, update_tag, update_volume_details,
    update_work_details,
)
from app.schemas import (
    BookBatchInput, BookInput, CopyInput, CopyUpdateInput, EditionInput,
    PublisherNormalizationInput, TagInput, VolumeInput, WorkInput,
)


def sample_book(title: str = "百年孤寂") -> BookInput:
    return BookInput(
        work=WorkInput(
            title=title, subtitle="一部家族史",
            authors="加夫列尔·加西亚·马尔克斯", scripts="西班牙文、中文",
        ),
        edition=EditionInput(
            identifier="9789571375883", translator="葉淑吟", translated_title=title,
            edition_scripts="中文", publisher="皇冠",
            publication_year=2018,
        ),
        volume=VolumeInput(volume_number="1.2.3"),
        copy=CopyInput(acquisition_date=date(2024, 1, 3), location="書房 A 架", reading_record="已讀"),
    )


class DatabaseMigrationTests(unittest.TestCase):
    def create_legacy_database(self, path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE works (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subtitle TEXT NOT NULL DEFAULT '',
                authors TEXT NOT NULL DEFAULT '',
                scripts TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE editions (
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
                publisher_id INTEGER,
                publication_year INTEGER,
                publication_year_end INTEGER,
                force_separate INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE edition_works (
                edition_id INTEGER NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
                work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                position INTEGER NOT NULL DEFAULT 0,
                relation_type TEXT NOT NULL DEFAULT 'contained',
                volume_number TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (edition_id, work_id),
                UNIQUE (edition_id, position)
            );
            CREATE TABLE copies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edition_id INTEGER NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
                volume_number TEXT NOT NULL DEFAULT '',
                volume_title TEXT NOT NULL DEFAULT '',
                identifier TEXT NOT NULL DEFAULT '',
                acquisition_date TEXT,
                location TEXT NOT NULL DEFAULT '',
                reading_record TEXT NOT NULL DEFAULT ''
            );
            """
        )
        return connection

    def add_legacy_edition(self, connection: sqlite3.Connection) -> tuple[int, int]:
        connection.execute(
            "INSERT INTO works (title, authors) VALUES ('Legacy Work', 'Author')"
        )
        work_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            "INSERT INTO editions (work_id, identifier) VALUES (?, 'ISBN SET')",
            (work_id,),
        )
        edition_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """INSERT INTO edition_works
                   (edition_id, work_id, position, relation_type, volume_number)
               VALUES (?, ?, 0, 'contained', '')""",
            (edition_id, work_id),
        )
        return work_id, edition_id

    def test_legacy_copy_becomes_implicit_volume_plus_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            connection = self.create_legacy_database(path)
            _, edition_id = self.add_legacy_edition(connection)
            connection.execute(
                """INSERT INTO copies
                       (edition_id, acquisition_date, location, reading_record)
                   VALUES (?, '2024-01-01', 'Shelf', 'Read')""",
                (edition_id,),
            )
            connection.commit()
            connection.close()

            report = initialize(path)
            connection = connect(path)
            try:
                copy_columns = {
                    row["name"] for row in connection.execute("PRAGMA table_info(copies)")
                }
                volume = connection.execute("SELECT * FROM volumes").fetchone()
                copy = connection.execute("SELECT * FROM copies").fetchone()
            finally:
                connection.close()

            self.assertEqual(report["migrated_copies"], 1)
            self.assertEqual(
                copy_columns,
                {"id", "volume_id", "acquisition_date", "location", "reading_record"},
            )
            self.assertEqual(volume["edition_id"], edition_id)
            self.assertEqual((volume["volume_number"], volume["volume_title"]), ("", ""))
            self.assertEqual(copy["volume_id"], volume["id"])
            self.assertEqual(copy["location"], "Shelf")

    def test_legacy_same_volume_copies_share_one_volume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shared.db"
            connection = self.create_legacy_database(path)
            _, edition_id = self.add_legacy_edition(connection)
            connection.executemany(
                """INSERT INTO copies
                       (edition_id, volume_number, volume_title, identifier, location)
                   VALUES (?, '2', 'Second', 'ISBN V2', ?)""",
                [(edition_id, "Shelf A"), (edition_id, "Shelf B")],
            )
            connection.commit()
            connection.close()

            report = initialize(path)
            connection = connect(path)
            try:
                volumes = connection.execute("SELECT * FROM volumes").fetchall()
                copies = connection.execute(
                    "SELECT volume_id, location FROM copies ORDER BY id"
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(report["shared_volume_groups"], 1)
            self.assertEqual(len(volumes), 1)
            self.assertEqual(volumes[0]["identifier"], "ISBN V2")
            self.assertEqual({copy["volume_id"] for copy in copies}, {volumes[0]["id"]})
            self.assertEqual([copy["location"] for copy in copies], ["Shelf A", "Shelf B"])

    def test_legacy_identifier_conflict_is_preserved_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identifier-conflict.db"
            connection = self.create_legacy_database(path)
            _, edition_id = self.add_legacy_edition(connection)
            connection.executemany(
                """INSERT INTO copies
                       (edition_id, volume_number, identifier)
                   VALUES (?, '1', ?)""",
                [(edition_id, "ISBN A"), (edition_id, "ISBN B")],
            )
            connection.commit()
            connection.close()

            report = initialize(path)
            connection = connect(path)
            try:
                identifier = connection.execute(
                    "SELECT identifier FROM volumes"
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(identifier, "ISBN A; ISBN B")
            self.assertEqual(len(report["identifier_conflicts"]), 1)

    def test_volume_relation_is_migrated_to_volume_id_foreign_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "relation.db"
            connection = self.create_legacy_database(path)
            work_id, edition_id = self.add_legacy_edition(connection)
            connection.execute(
                """UPDATE edition_works SET relation_type = 'volume',
                   volume_number = 'VII'
                   WHERE edition_id = ? AND work_id = ?""",
                (edition_id, work_id),
            )
            connection.execute(
                """INSERT INTO copies (edition_id, volume_number, location)
                   VALUES (?, 'VII', 'Shelf')""",
                (edition_id,),
            )
            connection.commit()
            connection.close()

            initialize(path)
            connection = connect(path)
            try:
                relation_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(edition_works)")
                }
                relation = connection.execute(
                    "SELECT relation_type, volume_id FROM edition_works"
                ).fetchone()
                volume = connection.execute(
                    "SELECT id, volume_number FROM volumes"
                ).fetchone()
                foreign_keys = connection.execute(
                    "PRAGMA foreign_key_list(edition_works)"
                ).fetchall()
            finally:
                connection.close()

            self.assertNotIn("volume_number", relation_columns)
            self.assertEqual(relation["relation_type"], "volume")
            self.assertEqual(relation["volume_id"], volume["id"])
            self.assertEqual(volume["volume_number"], "VII")
            self.assertTrue(any(
                row["from"] == "volume_id" and row["table"] == "volumes"
                for row in foreign_keys
            ))

    def test_initialize_does_not_semantically_merge_duplicate_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicates.db"
            connection = self.create_legacy_database(path)
            for location in ("A", "B"):
                _, edition_id = self.add_legacy_edition(connection)
                connection.execute(
                    "INSERT INTO copies (edition_id, location) VALUES (?, ?)",
                    (edition_id, location),
                )
            connection.commit()
            connection.close()

            initialize(path)
            connection = connect(path)
            try:
                counts = {
                    table: connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                    for table in ("works", "editions", "volumes", "copies")
                }
            finally:
                connection.close()
            self.assertEqual(counts, {
                "works": 2, "editions": 2, "volumes": 2, "copies": 2,
            })


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.db"
        initialize(self.path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_single_volume_book_uses_an_implicit_volume(self) -> None:
        book = sample_book("Implicit Volume")
        book.volume = VolumeInput()
        created = create_book(book, self.path)

        self.assertEqual(created["volume"]["volume_number"], "")
        self.assertEqual(created["volume"]["volume_title"], "")
        self.assertEqual(created["copy"]["volume_id"], created["volume"]["id"])
        connection = connect(self.path)
        try:
            volume_count = connection.execute("SELECT COUNT(*) FROM volumes").fetchone()[0]
            copy_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(copies)")
            }
        finally:
            connection.close()
        self.assertEqual(volume_count, 1)
        self.assertNotIn("volume_number", copy_columns)
        self.assertNotIn("volume_title", copy_columns)
        self.assertNotIn("identifier", copy_columns)

    def test_multiple_volumes_have_independent_overrides(self) -> None:
        first = sample_book("Volume Overrides")
        first.volume = VolumeInput(
            volume_number="1", identifier="ISBN V1", version="1",
            publication_year=2001, responsibility="Editor One",
        )
        second = sample_book("Volume Overrides")
        second.volume = VolumeInput(
            volume_number="2", identifier="ISBN V2", version="2",
            publication_year=2002, responsibility="Editor Two",
        )
        first_record = create_book(first, self.path)
        second_record = create_book(second, self.path)

        self.assertEqual(first_record["edition_id"], second_record["edition_id"])
        self.assertNotEqual(first_record["volume_id"], second_record["volume_id"])
        detail = get_work(list_works("Volume Overrides", self.path)[0]["id"], self.path)
        assert detail is not None
        volumes = [group["volume"] for group in detail["editions"][0]["volumes"]]
        self.assertEqual(
            [
                (
                    volume["volume_number"], volume["identifier"], volume["version"],
                    volume["publication_year"], volume["responsibility"],
                )
                for volume in volumes
            ],
            [
                ("1", "ISBN V1", "第1版", 2001, "Editor One"),
                ("2", "ISBN V2", "第2版", 2002, "Editor Two"),
            ],
        )

    def test_one_volume_can_have_two_physical_copies(self) -> None:
        first = create_book(sample_book("Shared Physical Volume"), self.path)
        second = create_copy_for_volume(
            first["volume_id"],
            CopyInput(location="Second Shelf", reading_record="Unread"),
            self.path,
        )

        self.assertEqual(first["volume_id"], second["volume_id"])
        connection = connect(self.path)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM copies WHERE volume_id = ?",
                    (first["volume_id"],),
                ).fetchone()[0],
                2,
            )
        finally:
            connection.close()

    def test_existing_edition_accepts_new_volume_and_existing_volume_accepts_copy(self) -> None:
        first = create_book(sample_book("Direct Volume CRUD"), self.path)
        volume = create_volume_record(
            first["edition_id"],
            VolumeInput(
                position=5, volume_number="Appendix", volume_title="Tables",
                version="Revised", publication_year="2020–2021",
                responsibility="Compiler",
            ),
            self.path,
        )
        updated = update_volume_details(
            volume["id"],
            VolumeInput(
                position=5, volume_number="A", volume_title="Reference Tables",
                version="3", publication_year=2022, responsibility="New Compiler",
            ),
            self.path,
        )
        assert updated is not None
        copy = create_copy_for_volume(
            volume["id"], CopyInput(location="Archive"), self.path
        )

        self.assertEqual(copy["volume_id"], volume["id"])
        self.assertEqual(updated["volume_number"], "A")
        self.assertEqual(updated["version"], "第3版")
        self.assertEqual(updated["publication_year"], 2022)
        self.assertEqual(updated["responsibility"], "New Compiler")

    def test_create_persists_four_linked_layers(self) -> None:
        created = create_book(sample_book(), self.path)
        self.assertEqual(created["id"], 1)
        self.assertEqual(created["edition_id"], 1)
        self.assertEqual(created["volume"]["volume_number"], "1.2.3")

        connection = connect(self.path)
        try:
            counts = [
                connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in ("works", "editions", "volumes", "copies")
            ]
        finally:
            connection.close()
        self.assertEqual(counts, [1, 1, 1, 1])

    def test_create_allows_optional_year_and_date_to_be_empty(self) -> None:
        payload = BookInput.model_validate({
            "work": {"title": "只填題名", "authors": ""},
            "edition": {
                "identifier": "", "translator": "", "other_title": "", "other_subtitle": "",
                "translated_title": "", "translated_subtitle": "", "edition_scripts": "",
                "publisher": "", "publication_year": None,
            },
            "copy": {"acquisition_date": None, "location": "", "reading_record": ""},
        })

        created = create_book(payload, self.path)

        self.assertIsNone(created["edition"]["publication_year"])
        self.assertIsNone(created["copy"]["acquisition_date"])

    def test_same_edition_is_reused_for_multiple_copies(self) -> None:
        first = sample_book()
        second = sample_book()
        second.copy_.location = "客廳書架"

        create_book(first, self.path)
        create_book(second, self.path)

        connection = connect(self.path)
        try:
            counts = [connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("works", "editions", "copies")]
        finally:
            connection.close()
        self.assertEqual(counts, [1, 1, 2])
        works = list_works(path=self.path)
        self.assertEqual((works[0]["edition_count"], works[0]["copy_count"]), (1, 2))
        detail = get_work(works[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"][0]["volumes"][0]["copies"]), 2)

    def test_different_volumes_share_the_same_edition(self) -> None:
        first = sample_book()
        first.volume.volume_number = "1"
        second = sample_book()
        second.volume.volume_number = "2"

        create_book(first, self.path)
        create_book(second, self.path)

        works = list_works(path=self.path)
        self.assertEqual(len(works), 1)
        self.assertEqual((works[0]["edition_count"], works[0]["copy_count"]), (1, 2))
        detail = get_work(works[0]["id"], self.path)
        assert detail is not None
        self.assertEqual([group["volume"]["volume_number"] for group in detail["editions"][0]["volumes"]], ["1", "2"])

    def test_different_version_creates_another_edition(self) -> None:
        first = sample_book()
        first.edition.version = "初版"
        first.edition.identifier = ""
        second = sample_book()
        second.edition.version = "修訂版"
        second.edition.identifier = ""

        create_book(first, self.path)
        create_book(second, self.path)

        detail = get_work(list_works(path=self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(
            {item["edition"]["version"] for item in detail["editions"]},
            {"初版", "修訂版"},
        )

    def test_identifier_year_and_volume_do_not_split_an_edition(self) -> None:
        first = sample_book()
        first.edition.identifier = "ISBN 111"
        first.edition.version = "\u7b2c 2 \u7248"
        first.edition.publication_year = 2002
        first.volume.volume_number = "1"
        second = sample_book()
        second.edition.identifier = "ISBN 222"
        second.edition.version = "\u7b2c 2 \u7248"
        second.edition.publication_year = 2003
        second.volume.volume_number = "2"

        create_book(first, self.path)
        create_book(second, self.path)

        detail = get_work(list_works(path=self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 1)
        edition = detail["editions"][0]
        self.assertEqual(edition["edition"]["identifier"], "ISBN 111")
        self.assertEqual(edition["edition"]["publication_year"], 2002)
        volumes = [group["volume"] for group in edition["volumes"]]
        self.assertEqual(
            [volume["volume_number"] for volume in volumes], ["1", "2"]
        )
        self.assertEqual(
            [volume["effective_metadata"]["identifier"]["value"] for volume in volumes],
            ["ISBN 111", "ISBN 222"],
        )
        self.assertEqual(
            [volume["effective_metadata"]["publication_year"]["value"]
             for volume in volumes],
            [2002, 2003],
        )

    def test_volume_identifier_can_coexist_with_edition_identifier(self) -> None:
        first = sample_book("Volume identifiers coexist")
        first.edition.identifier = "ISBN SET"
        first.volume.volume_number = "1"
        inherited = create_book(first, self.path)

        second = sample_book("Volume identifiers coexist")
        second.edition.identifier = "ISBN SET"
        second.volume.identifier = "ISBN VOLUME-2"
        second.volume.volume_number = "2"
        explicit = create_book(second, self.path)

        inherited_record = get_book(inherited["id"], self.path)
        explicit_record = get_book(explicit["id"], self.path)
        assert inherited_record is not None and explicit_record is not None
        self.assertEqual(inherited_record["volume"]["identifier"], "")
        self.assertEqual(inherited_record["volume"]["effective_metadata"]["identifier"]["value"], "ISBN SET")
        self.assertEqual(explicit_record["volume"]["identifier"], "ISBN VOLUME-2")
        self.assertEqual(explicit_record["edition"]["identifier"], "ISBN SET")

    def test_edition_identifier_can_be_moved_explicitly_to_volume(self) -> None:
        first = sample_book("Volume identifier demotion")
        first.edition.identifier = "ISBN SET"
        first.volume.volume_number = "1"
        inherited = create_book(first, self.path)

        second = sample_book("Volume identifier demotion")
        second.edition.identifier = "ISBN SET"
        second.volume.identifier = "ISBN VOLUME-2"
        second.volume.volume_number = "2"
        explicit = create_book(second, self.path)

        moved = move_edition_identifier_to_volume(
            inherited["edition_id"], inherited["volume_id"], self.path
        )
        self.assertIsNotNone(moved)
        inherited_record = get_book(inherited["id"], self.path)
        explicit_record = get_book(explicit["id"], self.path)
        assert inherited_record is not None and explicit_record is not None
        self.assertEqual(inherited_record["volume"]["identifier"], "ISBN SET")
        self.assertEqual(explicit_record["volume"]["identifier"], "ISBN VOLUME-2")
        self.assertEqual(explicit_record["edition"]["identifier"], "")

    def test_editing_volume_identifier_does_not_mutate_edition_identifier(self) -> None:
        first = sample_book("Edit volume identifier")
        first.edition.identifier = "ISBN SET"
        first.volume.volume_number = "1"
        create_book(first, self.path)
        second = sample_book("Edit volume identifier")
        second.edition.identifier = "ISBN SET"
        second.volume.volume_number = "2"
        second_record = create_book(second, self.path)

        changed = update_volume_details(
            second_record["volume_id"],
            VolumeInput(volume_number="2", identifier="ISBN VOLUME-2"),
            self.path,
        )
        self.assertIsNotNone(changed)
        books = list_books(path=self.path)
        self.assertEqual({book["edition"]["identifier"] for book in books}, {"ISBN SET"})
        self.assertEqual(
            {book["volume"]["identifier"] for book in books},
            {"", "ISBN VOLUME-2"},
        )

    def test_shared_identifier_does_not_override_different_version(self) -> None:
        first = sample_book()
        first.edition.version = "初版"
        first.edition.publication_year = 2002
        second = sample_book()
        second.edition.version = "修訂版"
        second.edition.publication_year = 2012

        create_book(first, self.path)
        create_book(second, self.path)

        detail = get_work(list_works(path=self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 2)

    def test_force_new_edition_preserves_identical_editions_across_initialize(self) -> None:
        first = sample_book()
        second = sample_book()
        second.volume.volume_number = "2"
        second.edition.force_new_edition = True

        create_book(first, self.path)
        forced = create_book(second, self.path)
        initialize(self.path)

        detail = get_work(list_works(path=self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 2)

        another_copy = sample_book()
        another_copy.edition.existing_edition_id = forced["edition_id"]
        another_copy.volume.volume_number = "3"
        create_book(another_copy, self.path)
        detail = get_work(detail["id"], self.path)
        assert detail is not None
        forced_group = next(
            group for group in detail["editions"] if group["id"] == forced["edition_id"]
        )
        self.assertEqual(sum(len(group["copies"]) for group in forced_group["volumes"]), 2)

    def test_translator_and_edition_scripts_split_editions(self) -> None:
        first = sample_book()
        second = sample_book()
        second.edition.translator = "另一譯者"
        second.volume.volume_number = "2"
        third = sample_book()
        third.edition.edition_scripts = "藏文"
        third.volume.volume_number = "3"

        create_book(first, self.path)
        create_book(second, self.path)
        create_book(third, self.path)

        detail = get_work(list_works(path=self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 3)

    def test_work_matching_ignores_case_and_surrounding_space(self) -> None:
        first = sample_book("Example")
        first.work.authors = "Author"
        second = sample_book("  example  ")
        second.work.authors = "author"

        create_book(first, self.path)
        create_book(second, self.path)

        self.assertEqual(len(list_works(path=self.path)), 1)
        self.assertEqual(list_works(path=self.path)[0]["copy_count"], 2)

    def test_hierarchical_tags_are_assigned_to_work(self) -> None:
        literature = create_tag(TagInput(name="文學"), self.path)
        fiction = create_tag(TagInput(name="小說", parent_id=literature["id"]), self.path)
        book = sample_book()
        book.work.tag_ids = [fiction["id"]]

        created = create_book(book, self.path)

        self.assertEqual(list_tags(self.path)[1]["path"], "文學 → 小說")
        self.assertEqual(created["work"]["tag_ids"], [fiction["id"]])
        works = list_works(path=self.path)
        self.assertEqual(works[0]["tags"][0]["path"], "文學 → 小說")
        self.assertEqual(len(list_works("小說", self.path)), 1)

    def test_direct_tag_input_creates_tags_then_allows_reclassification(self) -> None:
        book = sample_book()
        book.work.tag_names = ["藏文", "佛教", "西藏"]
        created = create_book(book, self.path)

        self.assertEqual({tag["name"] for tag in list_tags(self.path)}, {"藏文", "佛教", "西藏"})
        self.assertEqual(len(created["work"]["tag_ids"]), 3)
        buddhism = next(tag for tag in list_tags(self.path) if tag["name"] == "佛教")
        parent = create_tag(TagInput(name="思想"), self.path)
        updated = update_tag(
            buddhism["id"], TagInput(name="藏傳佛教", parent_id=parent["id"]), self.path
        )
        assert updated is not None
        self.assertEqual(updated["path"], "思想 → 藏傳佛教")
        self.assertEqual(len(list_works("藏傳佛教", self.path)), 1)

    def test_only_leaf_tags_can_hold_works_and_assigned_tags_cannot_gain_children(self) -> None:
        parent = create_tag(TagInput(name="思想"), self.path)
        leaf = create_tag(TagInput(name="佛教", parent_id=parent["id"]), self.path)
        invalid = sample_book("非法分類")
        invalid.work.tag_ids = [parent["id"]]
        with self.assertRaisesRegex(ValueError, "葉節點"):
            create_book(invalid, self.path)

        valid = sample_book("合法分類")
        valid.work.tag_ids = [leaf["id"]]
        create_book(valid, self.path)
        with self.assertRaisesRegex(ValueError, "已有藏書"):
            create_tag(TagInput(name="藏傳佛教", parent_id=leaf["id"]), self.path)

    def test_existing_non_leaf_assignments_are_reported_without_being_changed(self) -> None:
        parent = create_tag(TagInput(name="思想"), self.path)
        book = create_book(sample_book("待整理"), self.path)
        work_id = list_works("待整理", self.path)[0]["id"]
        connection = connect(self.path)
        try:
            connection.execute("INSERT INTO work_tags (work_id, tag_id) VALUES (?, ?)", (work_id, parent["id"]))
            connection.execute("INSERT INTO tags (name, parent_id) VALUES ('宗教', ?)", (parent["id"],))
            connection.commit()
        finally:
            connection.close()

        violations = list_tag_violations(self.path)
        self.assertEqual(violations[0]["work_id"], work_id)
        self.assertEqual(violations[0]["tag_path"], "思想")
        self.assertIsNotNone(get_book(book["id"], self.path))

    def test_batch_copies_share_one_edition_and_volumes_sort_naturally(self) -> None:
        book = sample_book("自然卷冊")
        records = create_books_batch(BookBatchInput(
            work=book.work, edition=book.edition, copy=book.copy_,
            volume_numbers=["1", "1.10", "2", "1.2", "11", "10"],
            volume_titles=["", "One ten", "", "One two", "", ""],
        ), self.path)
        self.assertEqual(len(records), 6)
        detail = get_work(list_works("自然卷冊", self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 1)
        self.assertEqual(
            [group["volume"]["volume_number"] for group in detail["editions"][0]["volumes"]],
            ["1", "1.10", "2", "1.2", "11", "10"],
        )
        self.assertEqual(
            [group["volume"]["volume_title"] for group in detail["editions"][0]["volumes"]],
            ["", "One ten", "", "One two", "", ""],
        )

    def test_effective_scripts_aggregate_from_each_edition(self) -> None:
        french = sample_book("多文種作品")
        french.edition.identifier = "ID-FR"
        french.edition.edition_scripts = "法文"
        german = sample_book("多文種作品")
        german.edition.identifier = "ID-DE"
        german.edition.edition_scripts = "德文"
        create_book(french, self.path)
        create_book(german, self.path)
        summary = list_works("多文種作品", self.path)[0]
        self.assertEqual(summary["effective_scripts"], ["法文", "德文"])

    def test_publisher_aliases_resolve_automatically_and_preserve_raw_name(self) -> None:
        first = sample_book("出版社測試一")
        first.edition.publisher = "西藏人民出版社"
        created = create_book(first, self.path)
        normalize_publisher(PublisherNormalizationInput(
            canonical_name=first.edition.publisher,
            aliases=[first.edition.publisher],
        ), self.path)
        normalize_publisher(PublisherNormalizationInput(
            canonical_name=first.edition.publisher,
            aliases=[
                first.edition.publisher,
                "བོད་ལྗོངས་མི་དམངས་དཔེ་སྐྲུན་ཁང་།",
            ],
        ), self.path)

        second = sample_book("出版社測試二")
        second.edition.publisher = "བོད་ལྗོངས་མི་དམངས་དཔེ་སྐྲུན་ཁང་།"
        second_created = create_book(second, self.path)
        created = get_book(created["id"], self.path)
        assert created is not None

        self.assertEqual(len(list_publishers(self.path)), 1)
        self.assertEqual(second_created["edition"]["publisher"], second.edition.publisher)
        self.assertEqual(
            second_created["edition"]["publisher_canonical"], "西藏人民出版社"
        )
        self.assertEqual(created["edition"]["publisher_canonical"], "西藏人民出版社")
        self.assertEqual(len(list_works("བོད་ལྗོངས", self.path)), 2)

    def test_new_work_and_edition_metadata_is_preserved_and_searchable(self) -> None:
        book = sample_book("དཔེ་ཆ")
        book.work.subtitle = "副標題"
        book.work.scripts = "藏文、漢文"
        book.edition.identifier = "978-7-105-16925-2/I·3194（བོད 403）"
        book.edition.other_title = "Tibetan parallel title"
        book.edition.other_subtitle = "A paired subtitle"
        book.edition.translated_title = "真正的翻譯題名"
        created = create_book(book, self.path)

        self.assertEqual(created["work"]["subtitle"], "副標題")
        self.assertEqual(created["work"]["scripts"], "藏文、漢文")
        self.assertEqual(created["edition"]["identifier"], book.edition.identifier)
        self.assertEqual(created["edition"]["other_title"], "Tibetan parallel title")
        self.assertEqual(created["edition"]["other_subtitle"], "A paired subtitle")
        self.assertEqual(created["edition"]["translated_title"], "真正的翻譯題名")
        for term in ("副標題", "藏文", "བོད 403", "parallel title", "真正的翻譯題名"):
            with self.subTest(term=term):
                self.assertEqual(len(list_works(term, self.path)), 1)
        summary = list_works(path=self.path)[0]
        self.assertEqual(summary["scripts"], "藏文、漢文")
        self.assertEqual(summary["publishers"], ["皇冠"])
        self.assertEqual(summary["locations"], ["書房 A 架"])
        self.assertEqual(summary["years"], [2018])

    def test_each_layer_can_be_edited_directly(self) -> None:
        created = create_book(sample_book(), self.path)
        summary = list_works(path=self.path)[0]
        detail = get_work(summary["id"], self.path)
        assert detail is not None
        edition_id = detail["editions"][0]["id"]

        work = update_work_details(
            summary["id"], WorkInput(title="New title", authors="New author"), self.path
        )
        edition = update_edition_details(
            edition_id,
            EditionInput(version="Revised", identifier="NEW-ISBN", publisher="New Press"),
            self.path,
        )
        volume = update_volume_details(
            created["volume_id"], VolumeInput(volume_number="3"), self.path
        )
        copy = update_copy_details(
            created["id"],
            CopyUpdateInput(location="New location", reading_record="Reread"),
            self.path,
        )

        assert all(item is not None for item in (work, edition, volume, copy))
        self.assertEqual(work["work"]["title"], "New title")
        self.assertEqual(edition["editions"][0]["edition"]["version"], "Revised")
        self.assertEqual(volume["volume_number"], "3")
        self.assertEqual(copy["location"], "New location")

    def test_searches_all_required_fields(self) -> None:
        book = sample_book()
        book.edition.version = "珍藏版"
        book.edition.translated_subtitle = "魔幻家族史"
        book.volume.identifier = "ISBN COPY-UNIQUE"
        create_book(book, self.path)
        terms = ["百年", "加西亚", "葉淑吟", "珍藏版", "魔幻家族史", "978957", "COPY-UNIQUE", "皇冠", "2018", "1.2.3", "2024-01-03", "A 架", "已讀"]
        for term in terms:
            with self.subTest(term=term):
                self.assertEqual(len(list_books(term, self.path)), 1)
        self.assertEqual(list_books("不存在", self.path), [])

    def test_update_changes_each_layer_without_changing_copy_id(self) -> None:
        created = create_book(sample_book(), self.path)
        changed = sample_book("霍亂時期的愛情")
        changed.edition.publication_year = 2019
        changed.copy_.location = "客廳 B 架"

        updated = update_book(created["id"], changed, self.path)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["id"], created["id"])
        self.assertEqual(updated["work"]["title"], "霍亂時期的愛情")
        self.assertEqual(updated["edition"]["publication_year"], 2019)
        self.assertEqual(updated["copy"]["location"], "客廳 B 架")
        self.assertEqual(get_book(9999, self.path), None)


    def test_edition_title_distinguishes_independent_units_under_one_work(self) -> None:
        first = sample_book("Collected Work")
        first.edition.identifier = ""
        first.edition.title = "Independent Unit A"
        first.edition.subtitle = "First subtitle"
        second = sample_book("Collected Work")
        second.edition.identifier = ""
        second.edition.title = "Independent Unit B"
        second.edition.subtitle = "Second subtitle"

        create_book(first, self.path)
        create_book(second, self.path)

        detail = get_work(list_works("Collected Work", self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 2)
        self.assertEqual(len(list_works("Independent Unit A", self.path)), 1)
        self.assertEqual(
            {group["edition"]["title"] for group in detail["editions"]},
            {"Independent Unit A", "Independent Unit B"},
        )

    def test_volume_number_and_title_are_stored_and_sorted_together(self) -> None:
        first = sample_book("Multi-volume Work")
        first.volume.volume_number = "2"
        first.volume.volume_title = "Later Part"
        second = sample_book("Multi-volume Work")
        second.volume.volume_number = "1"
        second.volume.volume_title = "Opening Part"

        create_book(first, self.path)
        create_book(second, self.path)

        detail = get_work(list_works("Multi-volume Work", self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(list_books("Opening Part", self.path)), 1)
        self.assertEqual(
            [
                (group["volume"]["volume_number"], group["volume"]["volume_title"])
                for group in detail["editions"][0]["volumes"]
            ],
            [("2", "Later Part"), ("1", "Opening Part")],
        )


    def test_work_side_can_create_search_update_and_remove_edition_links(self) -> None:
        existing = create_book(sample_book("Existing Edition Work"), self.path)
        edition_id = existing["edition_id"]
        edition_matches = list_editions("9789571375883", self.path)
        self.assertEqual([item["id"] for item in edition_matches], [edition_id])
        self.assertEqual(list_editions("皇冠", self.path)[0]["id"], edition_id)
        self.assertEqual(list_editions("2018", self.path)[0]["id"], edition_id)

        linked_work = create_work_record(WorkInput.model_validate({
            "title": "New Contained Work",
            "subtitle": "Linked from Work side",
            "authors": "Second Author",
            "scripts": "Greek",
            "edition_relations": [{
                "edition_id": edition_id,
                "relation_type": "contained",
            }],
        }), self.path)
        linked_work_id = linked_work["id"]
        edition_group = linked_work["editions"][0]
        relation = next(
            item for item in edition_group["edition"]["work_relations"]
            if item["work_id"] == linked_work_id
        )
        self.assertEqual(relation["relation_type"], "contained")
        self.assertEqual(
            len([item for item in edition_group["edition"]["work_relations"]
                 if item["work_id"] == linked_work_id]),
            1,
        )

        linked_volume = create_volume_record(
            edition_id, VolumeInput(volume_number="2"), self.path
        )
        updated = update_work_details(linked_work_id, WorkInput.model_validate({
            **linked_work["work"],
            "edition_relations": [{
                "edition_id": edition_id,
                "relation_type": "volume",
                "volume_id": linked_volume["id"],
            }],
        }), self.path)
        assert updated is not None
        relation = next(
            item for item in updated["editions"][0]["edition"]["work_relations"]
            if item["work_id"] == linked_work_id
        )
        self.assertEqual(
            (relation["relation_type"], relation["volume_id"]),
            ("volume", linked_volume["id"]),
        )

        detached = update_work_details(linked_work_id, WorkInput.model_validate({
            **updated["work"],
            "edition_relations": [],
        }), self.path)
        assert detached is not None
        self.assertEqual(detached["editions"], [])
        self.assertEqual(
            next(item for item in list_works(path=self.path) if item["id"] == linked_work_id)
                ["edition_count"],
            0,
        )
        original_work_id = existing["edition"]["work_ids"][0]
        original = get_work(original_work_id, self.path)
        assert original is not None
        with self.assertRaisesRegex(ValueError, "至少需要保留一個 Work"):
            update_work_details(original_work_id, WorkInput.model_validate({
                **original["work"],
                "edition_relations": [],
            }), self.path)

    def test_new_work_can_define_its_relation_type_before_it_has_an_id(self) -> None:
        payload = sample_book("New Volume Work").model_dump(by_alias=True)
        payload["volume"]["volume_number"] = "VII"
        payload["edition"]["work_relations"] = [
            {"work_id": 0, "relation_type": "volume", "volume_id": None}
        ]

        created = create_book(BookInput.model_validate(payload), self.path)

        work_id = list_works("New Volume Work", self.path)[0]["id"]
        relation = created["edition"]["work_relations"][0]
        self.assertEqual(relation["work_id"], work_id)
        self.assertEqual(relation["relation_type"], "volume")
        self.assertIsInstance(relation["volume_id"], int)
        self.assertEqual(
            relation["volume_id"],
            next(
                group["id"] for group in get_work(work_id, self.path)["editions"][0]["volumes"]
                if group["volume"]["volume_number"] == "VII"
            ),
        )

    def test_edition_work_relations_distinguish_volumes_from_contained_works(self) -> None:
        first_copy = create_book(sample_book("Tragedy A"), self.path)
        second_book = sample_book("Tragedy B")
        second_book.edition.identifier = "TRAGEDY-B"
        create_book(second_book, self.path)
        third_book = sample_book("Tragedy C")
        third_book.edition.identifier = "TRAGEDY-C"
        create_book(third_book, self.path)
        summaries = {work["title"]: work for work in list_works(path=self.path)}
        work_ids = [summaries[title]["id"] for title in ("Tragedy A", "Tragedy B", "Tragedy C")]
        detail = get_work(work_ids[0], self.path)
        assert detail is not None
        edition_id = detail["editions"][0]["id"]
        edition_data = detail["editions"][0]["edition"]
        first_volume_id = detail["editions"][0]["volumes"][0]["id"]
        second_volume = create_volume_record(
            edition_id, VolumeInput(volume_number="2"), self.path
        )
        edition = EditionInput.model_validate({
            **edition_data,
            "work_ids": [],
            "work_relations": [
                {"work_id": work_ids[0], "relation_type": "volume", "volume_id": first_volume_id},
                {"work_id": work_ids[1], "relation_type": "volume", "volume_id": second_volume["id"]},
                {"work_id": work_ids[2], "relation_type": "contained"},
            ],
        })

        updated = update_edition_details(edition_id, edition, self.path)

        assert updated is not None
        group = next(item for item in updated["editions"] if item["id"] == edition_id)
        self.assertEqual(group["edition"]["work_ids"], work_ids)
        relations = group["edition"]["work_relations"]
        self.assertEqual(
            [(item["work_id"], item["relation_type"], item["volume_id"]) for item in relations],
            [
                (work_ids[0], "volume", first_volume_id),
                (work_ids[1], "volume", second_volume["id"]),
                (work_ids[2], "contained", None),
            ],
        )
        self.assertTrue(all(
            item["volume_id"] is not None for item in relations[:2]
        ))
        self.assertIsNone(relations[2]["volume_id"])
        volume_ids = {
            volume_group["id"] for volume_group in group["volumes"]
        }
        self.assertTrue({item["volume_id"] for item in relations[:2]} <= volume_ids)
        linked = get_book(first_copy["id"], self.path)
        assert linked is not None
        self.assertEqual(linked["edition"]["work_relations"], group["edition"]["work_relations"])

    def test_edition_can_link_ordered_multiple_works_and_survive_primary_deletion(self) -> None:
        first_copy = create_book(sample_book("Independent Work A"), self.path)
        second_book = sample_book("Independent Work B")
        second_book.edition.identifier = "ID-B"
        second_book.edition.version = "Independent edition"
        create_book(second_book, self.path)
        summaries = {work["title"]: work for work in list_works(path=self.path)}
        first_work_id = summaries["Independent Work A"]["id"]
        second_work_id = summaries["Independent Work B"]["id"]
        first_detail = get_work(first_work_id, self.path)
        assert first_detail is not None
        shared_edition_id = first_detail["editions"][0]["id"]
        edition = EditionInput.model_validate(first_detail["editions"][0]["edition"])
        edition.work_ids = [second_work_id, first_work_id]

        updated = update_edition_details(shared_edition_id, edition, self.path)

        assert updated is not None
        self.assertEqual(updated["id"], second_work_id)
        self.assertEqual(
            next(group for group in updated["editions"] if group["id"] == shared_edition_id)
                ["edition"]["work_ids"],
            [second_work_id, first_work_id],
        )
        linked_from_first = get_work(first_work_id, self.path)
        assert linked_from_first is not None
        self.assertEqual(
            next(group for group in linked_from_first["editions"] if group["id"] == shared_edition_id)
                ["volumes"][0]["copies"][0]["id"],
            first_copy["id"],
        )
        self.assertEqual(len(list_books("Independent Work A", self.path)), 1)

        edition.work_ids = [first_work_id, second_work_id]
        restored_order = update_edition_details(shared_edition_id, edition, self.path)
        assert restored_order is not None
        self.assertEqual(
            next(group for group in restored_order["editions"] if group["id"] == shared_edition_id)
                ["edition"]["work_ids"],
            [first_work_id, second_work_id],
        )
        self.assertTrue(delete_work(first_work_id, self.path))
        surviving = get_book(first_copy["id"], self.path)
        assert surviving is not None
        self.assertEqual(surviving["work"]["title"], "Independent Work B")
        self.assertEqual(surviving["edition"]["work_ids"], [second_work_id])



    def test_deleting_volume_retains_edition_and_removes_its_copies(self) -> None:
        first = create_book(sample_book("Delete Volume"), self.path)
        second = create_copy_for_volume(
            first["volume_id"], CopyInput(location="Second"), self.path
        )
        result = delete_volume(first["volume_id"], self.path)
        self.assertEqual(result["deleted_copy_count"], 2)
        self.assertTrue(result["edition_retained"])
        connection = connect(self.path)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM editions").fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM volumes").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM copies").fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_delete_operations_cover_every_managed_layer(self) -> None:
        first = create_book(sample_book("Delete Copies"), self.path)
        second = create_book(sample_book("Delete Copies"), self.path)
        work_id = list_works(path=self.path)[0]["id"]

        first_result = delete_copy(first["id"], self.path)
        assert first_result is not None
        self.assertFalse(first_result["edition_deleted"])
        self.assertIsNotNone(get_work(work_id, self.path))

        second_result = delete_copy(second["id"], self.path)
        assert second_result is not None
        self.assertFalse(second_result["edition_deleted"])
        self.assertFalse(second_result["work_deleted"])
        retained = get_work(work_id, self.path)
        assert retained is not None
        self.assertEqual(len(retained["editions"][0]["volumes"]), 1)
        self.assertEqual(retained["editions"][0]["volumes"][0]["copies"], [])

        edition_book = create_book(sample_book("Delete Edition"), self.path)
        edition_work = list_works("Delete Edition", self.path)[0]
        edition_detail = get_work(edition_work["id"], self.path)
        assert edition_detail is not None
        edition_id = edition_detail["editions"][0]["id"]
        edition_result = delete_edition(edition_id, self.path)
        assert edition_result is not None
        self.assertTrue(edition_result["work_deleted"])
        self.assertIsNone(get_book(edition_book["id"], self.path))

        work_book = create_book(sample_book("Delete Work"), self.path)
        work_record = list_works("Delete Work", self.path)[0]
        self.assertTrue(delete_work(work_record["id"], self.path))
        self.assertIsNone(get_book(work_book["id"], self.path))

        parent = create_tag(TagInput(name="Parent"), self.path)
        child = create_tag(TagInput(name="Child", parent_id=parent["id"]), self.path)
        tag_result = delete_tag(parent["id"], self.path)
        assert tag_result is not None
        self.assertEqual(tag_result["deleted_count"], 2)
        self.assertNotIn(child["id"], [tag["id"] for tag in list_tags(self.path)])

        publisher_book = sample_book("Delete Publisher")
        publisher_book.edition.publisher = "Raw Press"
        publisher_copy = create_book(publisher_book, self.path)
        normalized = normalize_publisher(PublisherNormalizationInput(
            canonical_name="Canonical Press", aliases=["Raw Press"]
        ), self.path)
        self.assertTrue(delete_publisher(normalized["id"], self.path))
        preserved = get_book(publisher_copy["id"], self.path)
        assert preserved is not None
        self.assertEqual(preserved["edition"]["publisher"], "Raw Press")
        self.assertEqual(preserved["edition"]["publisher_canonical"], "")

if __name__ == "__main__":
    unittest.main()
