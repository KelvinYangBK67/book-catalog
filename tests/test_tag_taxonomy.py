from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.database import connect, initialize
from app.tag_taxonomy import apply_main_tag_taxonomy


class TagTaxonomyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "library.db"
        initialize(self.path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_taxonomy_reuses_ids_preserves_links_and_is_idempotent(self) -> None:
        connection = connect(self.path)
        try:
            work_id = connection.execute(
                "INSERT INTO works (title) VALUES ('Tagged')"
            ).lastrowid
            old_root_id = connection.execute(
                "INSERT INTO tags (name) VALUES ('舊分類')"
            ).lastrowid
            literature_id = connection.execute(
                "INSERT INTO tags (name, parent_id) VALUES ('文學', ?)",
                (old_root_id,),
            ).lastrowid
            connection.execute(
                "INSERT INTO work_tags (work_id, tag_id) VALUES (?, ?)",
                (work_id, literature_id),
            )
            connection.execute("INSERT INTO tags (name) VALUES ('未列舊標籤')")
            connection.commit()
        finally:
            connection.close()

        first = apply_main_tag_taxonomy(self.path)
        second = apply_main_tag_taxonomy(self.path)

        connection = connect(self.path)
        try:
            literature = connection.execute(
                "SELECT id, parent_id FROM tags WHERE name = '文學'"
            ).fetchone()
            humanities = connection.execute(
                "SELECT id FROM tags WHERE name = '人文'"
            ).fetchone()
            self.assertEqual(literature["id"], literature_id)
            self.assertEqual(literature["parent_id"], humanities["id"])
            self.assertIsNotNone(connection.execute(
                "SELECT 1 FROM work_tags WHERE work_id = ? AND tag_id = ?",
                (work_id, literature_id),
            ).fetchone())
            self.assertIsNotNone(connection.execute(
                "SELECT 1 FROM tags WHERE name = '未列舊標籤'"
            ).fetchone())
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM tags WHERE name = '人文'"
                ).fetchone()[0],
                1,
            )
        finally:
            connection.close()

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertFalse(second["moved"])


if __name__ == "__main__":
    unittest.main()
