from __future__ import annotations

import tempfile
import unittest
import sqlite3
from datetime import date
from pathlib import Path

from app.database import connect, initialize
from app.repository import (
    CopyIdentifierTransitionRequired,
    create_book, create_books_batch, create_tag, create_work_record, delete_copy, delete_edition, delete_publisher,
    delete_tag, delete_work, get_book, get_work, list_books, list_editions, list_publishers,
    list_tag_violations, list_tags, list_works, normalize_publisher, update_book, update_copy_details,
    update_edition_details, update_tag, update_work_details,
)
from app.schemas import (
    BookBatchInput, BookInput, CopyInput, EditionInput,
    PublisherNormalizationInput, TagInput, WorkInput,
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
        copy=CopyInput(volume="1.2.3", acquisition_date=date(2024, 1, 3), location="書房 A 架", reading_record="已讀"),
    )


class DatabaseMigrationTests(unittest.TestCase):
    def test_legacy_work_columns_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(path)
            connection.execute(
                """CREATE TABLE works (
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                    subtitle TEXT NOT NULL DEFAULT '', authors TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT ''
                )"""
            )
            connection.commit()
            connection.close()

            initialize(path)

            connection = connect(path)
            try:
                columns = [row["name"] for row in connection.execute("PRAGMA table_info(works)")]
            finally:
                connection.close()
            self.assertEqual(columns, ["id", "title", "subtitle", "authors", "scripts"])

    def test_legacy_names_are_migrated_to_new_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-names.db"
            initialize(path)
            connection = connect(path)
            try:
                connection.execute("ALTER TABLE works ADD COLUMN language TEXT NOT NULL DEFAULT ''")
                connection.execute("ALTER TABLE editions ADD COLUMN isbn TEXT NOT NULL DEFAULT ''")
                connection.execute("CREATE INDEX idx_editions_isbn ON editions(isbn)")
                connection.execute(
                    "ALTER TABLE editions ADD COLUMN translation_language TEXT NOT NULL DEFAULT ''"
                )
                connection.execute(
                    "INSERT INTO works (title, authors, language) VALUES ('舊書', '作者', '藏文')"
                )
                work_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                connection.execute(
                    """INSERT INTO editions (work_id, isbn, translation_language, publisher)
                       VALUES (?, '舊識別號', '漢文', '舊出版社')""",
                    (work_id,),
                )
                edition_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                connection.execute("INSERT INTO copies (edition_id) VALUES (?)", (edition_id,))
                connection.commit()
            finally:
                connection.close()

            initialize(path)
            migrated = get_book(1, path)
            assert migrated is not None
            normalize_publisher(PublisherNormalizationInput(
                canonical_name=migrated["edition"]["publisher"],
                aliases=[migrated["edition"]["publisher"]],
            ), path)
            migrated = get_book(1, path)
            assert migrated is not None
            self.assertEqual(migrated["work"]["scripts"], "藏文")
            self.assertEqual(migrated["edition"]["identifier"], "舊識別號")
            self.assertEqual(migrated["edition"]["edition_scripts"], "漢文")
            self.assertEqual(migrated["edition"]["publisher_canonical"], "舊出版社")
            connection = connect(path)
            try:
                work_columns = {row["name"] for row in connection.execute("PRAGMA table_info(works)")}
                edition_columns = {row["name"] for row in connection.execute("PRAGMA table_info(editions)")}
            finally:
                connection.close()
            self.assertNotIn("language", work_columns)
            self.assertNotIn("isbn", edition_columns)
            self.assertNotIn("translation_language", edition_columns)

    def test_duplicate_hierarchy_is_merged_without_losing_copies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicates.db"
            initialize(path)
            connection = connect(path)
            try:
                connection.execute("INSERT INTO works (title, authors) VALUES ('Same', 'Author')")
                work_one = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                connection.execute("INSERT INTO works (title, authors) VALUES ('Same', 'Author')")
                work_two = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                for work_id, location in ((work_one, "A"), (work_two, "B")):
                    connection.execute("INSERT INTO editions (work_id, identifier) VALUES (?, 'ISBN')", (work_id,))
                    edition_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                    connection.execute(
                        "INSERT INTO copies (edition_id, volume_number, location) VALUES (?, '1', ?)",
                        (edition_id, location),
                    )
                connection.commit()
            finally:
                connection.close()

            initialize(path)

            connection = connect(path)
            try:
                counts = [connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                          for table in ("works", "editions", "copies")]
                locations = [row[0] for row in connection.execute("SELECT location FROM copies ORDER BY id")]
            finally:
                connection.close()
            self.assertEqual(counts, [1, 1, 2])
            self.assertEqual(locations, ["A", "B"])

    def test_edition_volume_is_moved_to_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "volume.db"
            initialize(path)
            connection = connect(path)
            try:
                connection.execute("ALTER TABLE editions ADD COLUMN volume TEXT NOT NULL DEFAULT ''")
                connection.execute("INSERT INTO works (title, authors) VALUES ('Work', 'Author')")
                work_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                connection.execute(
                    "INSERT INTO editions (work_id, version, volume) VALUES (?, 'First', '2')",
                    (work_id,),
                )
                edition_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                connection.execute("INSERT INTO copies (edition_id) VALUES (?)", (edition_id,))
                connection.commit()
            finally:
                connection.close()

            initialize(path)

            connection = connect(path)
            try:
                edition_columns = [row["name"] for row in connection.execute("PRAGMA table_info(editions)")]
                volume = connection.execute("SELECT volume_number FROM copies").fetchone()[0]
            finally:
                connection.close()
            self.assertNotIn("volume", edition_columns)
            self.assertEqual(volume, "2")


    def test_legacy_copy_volume_is_migrated_to_volume_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-copy-volume.db"
            initialize(path)
            connection = connect(path)
            try:
                connection.execute(
                    "ALTER TABLE copies ADD COLUMN volume TEXT NOT NULL DEFAULT ''"
                )
                connection.execute("INSERT INTO works (title) VALUES ('Legacy Work')")
                connection.execute("INSERT INTO editions (work_id) VALUES (1)")
                connection.execute(
                    "INSERT INTO copies (edition_id, volume) VALUES (1, '2.1')"
                )
                connection.commit()
            finally:
                connection.close()

            initialize(path)
            connection = connect(path)
            try:
                row = connection.execute(
                    "SELECT volume_number, volume_title FROM copies WHERE id = 1"
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual((row["volume_number"], row["volume_title"]), ("2.1", ""))


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.db"
        initialize(self.path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_create_persists_three_linked_layers(self) -> None:
        created = create_book(sample_book(), self.path)
        self.assertEqual(created["id"], 1)
        self.assertEqual(created["edition_id"], 1)
        self.assertEqual(created["copy"]["volume_number"], "1.2.3")

        connection = connect(self.path)
        try:
            counts = [connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("works", "editions", "copies")]
        finally:
            connection.close()
        self.assertEqual(counts, [1, 1, 1])

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
        self.assertEqual(len(detail["editions"][0]["copies"]), 2)

    def test_different_volumes_share_the_same_edition(self) -> None:
        first = sample_book()
        first.copy_.volume_number = "1"
        second = sample_book()
        second.copy_.volume_number = "2"

        create_book(first, self.path)
        create_book(second, self.path)

        works = list_works(path=self.path)
        self.assertEqual(len(works), 1)
        self.assertEqual((works[0]["edition_count"], works[0]["copy_count"]), (1, 2))
        detail = get_work(works[0]["id"], self.path)
        assert detail is not None
        self.assertEqual([copy["volume_number"] for copy in detail["editions"][0]["copies"]], ["1", "2"])

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
        first.edition.version = "第 2 版"
        first.edition.publication_year = 2002
        first.copy_.volume_number = "1"
        second = sample_book()
        second.edition.identifier = "ISBN 222"
        second.edition.version = "第 2 版"
        second.edition.publication_year = 2003
        second.copy_.volume_number = "2"

        create_book(first, self.path)
        create_book(second, self.path)

        detail = get_work(list_works(path=self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 1)
        edition = detail["editions"][0]
        self.assertEqual(edition["edition"]["identifier"], "ISBN 111; ISBN 222")
        self.assertEqual(edition["edition"]["publication_year"], "2002–2003")
        self.assertEqual(
            [copy["volume_number"] for copy in edition["copies"]], ["1", "2"]
        )

    def test_copy_identifier_can_keep_shared_edition_identifier(self) -> None:
        first = sample_book("Volume identifiers coexist")
        first.edition.identifier = "ISBN SET"
        first.copy_.identifier = ""
        first.copy_.volume_number = "1"
        inherited = create_book(first, self.path)

        second = sample_book("Volume identifiers coexist")
        second.edition.identifier = "ISBN SET"
        second.copy_.identifier = "ISBN VOLUME-2"
        second.copy_.volume_number = "2"
        with self.assertRaises(CopyIdentifierTransitionRequired):
            create_book(second, self.path)
        self.assertEqual(len(list_books(path=self.path)), 1)

        second.copy_.identifier_transition = "keep"
        explicit = create_book(second, self.path)

        inherited_record = get_book(inherited["id"], self.path)
        explicit_record = get_book(explicit["id"], self.path)
        assert inherited_record is not None and explicit_record is not None
        self.assertEqual(inherited_record["copy"]["identifier"], "")
        self.assertEqual(inherited_record["copy"]["effective_identifier"], "ISBN SET")
        self.assertEqual(explicit_record["copy"]["identifier"], "ISBN VOLUME-2")
        self.assertEqual(explicit_record["edition"]["identifier"], "ISBN SET")

        third = sample_book("Volume identifiers coexist")
        third.edition.identifier = "ISBN SET"
        third.copy_.identifier = "ISBN VOLUME-3"
        third.copy_.volume_number = "3"
        create_book(third, self.path)
        self.assertEqual(len(list_books(path=self.path)), 3)

    def test_copy_identifier_can_demote_edition_identifier(self) -> None:
        first = sample_book("Volume identifier demotion")
        first.edition.identifier = "ISBN SET"
        first.copy_.identifier = ""
        first.copy_.volume_number = "1"
        inherited = create_book(first, self.path)

        second = sample_book("Volume identifier demotion")
        second.edition.identifier = "ISBN SET"
        second.copy_.identifier = "ISBN VOLUME-2"
        second.copy_.identifier_transition = "demote"
        second.copy_.volume_number = "2"
        explicit = create_book(second, self.path)

        inherited_record = get_book(inherited["id"], self.path)
        explicit_record = get_book(explicit["id"], self.path)
        assert inherited_record is not None and explicit_record is not None
        self.assertEqual(inherited_record["copy"]["identifier"], "ISBN SET")
        self.assertEqual(inherited_record["copy"]["effective_identifier"], "ISBN SET")
        self.assertEqual(explicit_record["copy"]["identifier"], "ISBN VOLUME-2")
        self.assertEqual(explicit_record["edition"]["identifier"], "")

    def test_editing_first_distinct_copy_identifier_requires_a_decision(self) -> None:
        first = sample_book("Edit volume identifier")
        first.edition.identifier = "ISBN SET"
        first.copy_.volume_number = "1"
        create_book(first, self.path)
        second = sample_book("Edit volume identifier")
        second.edition.identifier = "ISBN SET"
        second.copy_.volume_number = "2"
        second_record = create_book(second, self.path)

        changed = CopyInput(
            volume_number="2", identifier="ISBN VOLUME-2", location="Shelf"
        )
        with self.assertRaises(CopyIdentifierTransitionRequired):
            update_copy_details(second_record["id"], changed, self.path)
        changed.identifier_transition = "demote"
        update_copy_details(second_record["id"], changed, self.path)

        books = list_books(path=self.path)
        self.assertEqual({book["edition"]["identifier"] for book in books}, {""})
        self.assertEqual(
            {book["copy"]["identifier"] for book in books},
            {"ISBN SET", "ISBN VOLUME-2"},
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
        second.copy_.volume_number = "2"
        second.edition.force_new_edition = True

        create_book(first, self.path)
        forced = create_book(second, self.path)
        initialize(self.path)

        detail = get_work(list_works(path=self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 2)

        another_copy = sample_book()
        another_copy.edition.existing_edition_id = forced["edition_id"]
        another_copy.copy_.volume_number = "3"
        create_book(another_copy, self.path)
        detail = get_work(detail["id"], self.path)
        assert detail is not None
        forced_group = next(
            group for group in detail["editions"] if group["id"] == forced["edition_id"]
        )
        self.assertEqual(len(forced_group["copies"]), 2)

    def test_translator_and_edition_scripts_split_editions(self) -> None:
        first = sample_book()
        second = sample_book()
        second.edition.translator = "另一譯者"
        second.copy_.volume_number = "2"
        third = sample_book()
        third.edition.edition_scripts = "藏文"
        third.copy_.volume_number = "3"

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
            volumes=["1", "1.10", "2", "1.2", "11", "10"],
            volume_titles=["", "One ten", "", "One two", "", ""],
        ), self.path)
        self.assertEqual(len(records), 6)
        detail = get_work(list_works("自然卷冊", self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 1)
        self.assertEqual(
            [copy["volume_number"] for copy in detail["editions"][0]["copies"]],
            ["1", "1.2", "1.10", "2", "10", "11"],
        )
        self.assertEqual(
            [copy["volume_title"] for copy in detail["editions"][0]["copies"]],
            ["", "One two", "One ten", "", "", ""],
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

        work = update_work_details(summary["id"], WorkInput(title="新題名", authors="新作者"), self.path)
        edition = update_edition_details(
            edition_id,
            EditionInput(version="修訂版", identifier="NEW-ISBN", publisher="新出版社"),
            self.path,
        )
        copy = update_copy_details(
            created["id"], CopyInput(volume="3", location="新位置", reading_record="重讀"), self.path
        )

        assert work is not None and edition is not None and copy is not None
        self.assertEqual(work["work"]["title"], "新題名")
        self.assertEqual(edition["editions"][0]["edition"]["version"], "修訂版")
        self.assertEqual(copy["copy"]["volume_number"], "3")
        self.assertEqual(copy["copy"]["location"], "新位置")

    def test_searches_all_required_fields(self) -> None:
        book = sample_book()
        book.edition.version = "珍藏版"
        book.edition.translated_subtitle = "魔幻家族史"
        book.copy_.identifier = "ISBN COPY-UNIQUE"
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
        first.copy_.volume_number = "2"
        first.copy_.volume_title = "Later Part"
        second = sample_book("Multi-volume Work")
        second.copy_.volume_number = "1"
        second.copy_.volume_title = "Opening Part"

        create_book(first, self.path)
        create_book(second, self.path)

        detail = get_work(list_works("Multi-volume Work", self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(list_books("Opening Part", self.path)), 1)
        self.assertEqual(
            [
                (copy["volume_number"], copy["volume_title"])
                for copy in detail["editions"][0]["copies"]
            ],
            [("1", "Opening Part"), ("2", "Later Part")],
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

        updated = update_work_details(linked_work_id, WorkInput.model_validate({
            **linked_work["work"],
            "edition_relations": [{
                "edition_id": edition_id,
                "relation_type": "volume",
                "volume_number": "2",
            }],
        }), self.path)
        assert updated is not None
        relation = next(
            item for item in updated["editions"][0]["edition"]["work_relations"]
            if item["work_id"] == linked_work_id
        )
        self.assertEqual(
            (relation["relation_type"], relation["volume_number"]),
            ("volume", "2"),
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
        payload["edition"]["work_relations"] = [
            {"work_id": 0, "relation_type": "volume", "volume_number": "VII"}
        ]

        created = create_book(BookInput.model_validate(payload), self.path)

        work_id = list_works("New Volume Work", self.path)[0]["id"]
        self.assertEqual(created["edition"]["work_relations"], [{
            "work_id": work_id,
            "relation_type": "volume",
            "volume_number": "VII",
        }])

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
        edition = EditionInput.model_validate({
            **edition_data,
            "work_ids": [],
            "work_relations": [
                {"work_id": work_ids[0], "relation_type": "volume", "volume_number": "1"},
                {"work_id": work_ids[1], "relation_type": "volume", "volume_number": "2"},
                {
                    "work_id": work_ids[2],
                    "relation_type": "contained",
                    "volume_number": "must be discarded",
                },
            ],
        })

        updated = update_edition_details(edition_id, edition, self.path)

        assert updated is not None
        group = next(item for item in updated["editions"] if item["id"] == edition_id)
        self.assertEqual(group["edition"]["work_ids"], work_ids)
        self.assertEqual(group["edition"]["work_relations"], [
            {"work_id": work_ids[0], "relation_type": "volume", "volume_number": "1"},
            {"work_id": work_ids[1], "relation_type": "volume", "volume_number": "2"},
            {"work_id": work_ids[2], "relation_type": "contained", "volume_number": ""},
        ])
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
                ["copies"][0]["id"],
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
        self.assertTrue(second_result["edition_deleted"])
        self.assertTrue(second_result["work_deleted"])
        self.assertIsNone(get_work(work_id, self.path))

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
