from __future__ import annotations

import tempfile
import unittest
import sqlite3
from datetime import date
from pathlib import Path

from app.database import connect, initialize
from app.repository import (
    create_book, create_tag, delete_copy, delete_edition, delete_publisher,
    delete_tag, delete_work, get_book, get_work, list_books, list_publishers,
    list_tags, list_works, normalize_publisher, update_book, update_copy_details,
    update_edition_details, update_tag, update_work_details,
)
from app.schemas import (
    BookInput, CopyInput, EditionInput,
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
                        "INSERT INTO copies (edition_id, volume, location) VALUES (?, '1', ?)",
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
                volume = connection.execute("SELECT volume FROM copies").fetchone()[0]
            finally:
                connection.close()
            self.assertNotIn("volume", edition_columns)
            self.assertEqual(volume, "2")


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
        self.assertEqual(created["copy"]["volume"], "1.2.3")

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
        first.copy_.volume = "1"
        second = sample_book()
        second.copy_.volume = "2"

        create_book(first, self.path)
        create_book(second, self.path)

        works = list_works(path=self.path)
        self.assertEqual(len(works), 1)
        self.assertEqual((works[0]["edition_count"], works[0]["copy_count"]), (1, 2))
        detail = get_work(works[0]["id"], self.path)
        assert detail is not None
        self.assertEqual([copy["volume"] for copy in detail["editions"][0]["copies"]], ["1", "2"])

    def test_different_version_creates_another_edition(self) -> None:
        first = sample_book()
        first.edition.version = "初版"
        second = sample_book()
        second.edition.version = "修訂版"

        create_book(first, self.path)
        create_book(second, self.path)

        detail = get_work(list_works(path=self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(
            {item["edition"]["version"] for item in detail["editions"]},
            {"初版", "修訂版"},
        )

    def test_same_named_version_merges_despite_other_metadata_difference(self) -> None:
        first = sample_book()
        first.edition.version = "第 2 版"
        first.edition.publication_year = 2002
        second = sample_book()
        second.edition.version = "第 2 版"
        second.edition.publication_year = 2012
        second.copy_.volume = "2"

        create_book(first, self.path)
        create_book(second, self.path)

        detail = get_work(list_works(path=self.path)[0]["id"], self.path)
        assert detail is not None
        self.assertEqual(len(detail["editions"]), 1)
        self.assertEqual(len(detail["editions"][0]["copies"]), 2)
        self.assertEqual(detail["editions"][0]["edition"]["version"], "第 2 版")

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
        tibet = next(tag for tag in list_tags(self.path) if tag["name"] == "西藏")
        updated = update_tag(
            buddhism["id"], TagInput(name="藏傳佛教", parent_id=tibet["id"]), self.path
        )
        assert updated is not None
        self.assertEqual(updated["path"], "西藏 → 藏傳佛教")
        self.assertEqual(len(list_works("藏傳佛教", self.path)), 1)

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
        self.assertEqual(copy["copy"]["volume"], "3")
        self.assertEqual(copy["copy"]["location"], "新位置")

    def test_searches_all_required_fields(self) -> None:
        create_book(sample_book(), self.path)
        terms = ["百年", "加西亚", "978957", "皇冠", "A 架", "已讀"]
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
