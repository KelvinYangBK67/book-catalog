from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CATALOG_MODEL = (ROOT / "static" / "catalog-model.js").read_text(encoding="utf-8")


class FrontendStructureTests(unittest.TestCase):
    def test_plain_modules_are_split_without_framework(self) -> None:
        self.assertIn('type="module" src="/static/app.js', HTML)
        for filename in ("api.js", "state.js", "components.js", "formatters.js", "catalog-model.js"):
            self.assertTrue((ROOT / "static" / filename).exists())
        self.assertIn('from "./api.js"', JS)
        self.assertNotIn("React", HTML + JS)
        self.assertNotIn("Vue", HTML + JS)

    def test_common_single_volume_flow_stays_outside_disclosures(self) -> None:
        first_disclosure = HTML.index('<details class="form-disclosure"')
        for name in (
            "work.title", "work.subtitle", "work.authors", "work.scripts",
            "work.tags", "edition.publisher", "edition.publication_year",
            "edition.version", "edition.identifier",
        ):
            self.assertLess(HTML.index(f'name="{name}"'), first_disclosure)
        self.assertIn('name="copy.location"', HTML)
        self.assertIn('name="copy.acquisition_date"', HTML)

    def test_low_frequency_fields_are_progressively_disclosed(self) -> None:
        for label in (
            "更多版本信息", "冊資料", "冊級例外",
            "其他館藏信息", "進階結構",
        ):
            self.assertIn(f'data-label="{label}"', HTML)
        self.assertIn("updateDisclosureCounts(form)", JS)
        self.assertIn("details.classList.toggle('has-values'", (
            ROOT / "static" / "components.js"
        ).read_text(encoding="utf-8"))

    def test_volume_overrides_are_real_volume_inputs(self) -> None:
        self.assertIn('name="volume.version"', HTML)
        self.assertIn('name="volume.publication_year"', HTML)
        self.assertIn('name="volume.responsibility"', HTML)
        self.assertIn("version: get('volume.version')", JS)
        self.assertIn("responsibility: get('volume.responsibility')", JS)

    def test_hierarchy_uses_volume_groups_and_copy_only_details(self) -> None:
        self.assertIn("return (group.volumes || [])", CATALOG_MODEL)
        self.assertIn("volume.effective_metadata?.responsibility?.value", JS)
        self.assertIn("activeCopy = await request('/api/copies/'", JS)
        copy_block = JS[JS.index("async function openCopy"):JS.index(
            "function setField", JS.index("async function openCopy")
        )]
        self.assertNotIn("activeBook.work", copy_block)
        self.assertNotIn("activeBook.edition", copy_block)

    def test_each_layer_has_one_action_menu(self) -> None:
        for layer in ("work", "edition", "volume", "copy"):
            self.assertIn(f"actionMenu('{layer}'", JS)
        self.assertNotIn('class="edition-actions"', JS)
        self.assertIn("data-layer-action", (
            ROOT / "static" / "components.js"
        ).read_text(encoding="utf-8"))
        for obsolete_id in (
            "delete-work-button", "edit-work-button", "add-work-copy-button",
            "edit-copy-button", "delete-copy-button",
        ):
            self.assertNotIn(obsolete_id, HTML + JS)
        self.assertNotIn("edition.work_ids ||", CATALOG_MODEL)

    def test_group_tag_and_publisher_collapse_controls_exist(self) -> None:
        for attribute in (
            "data-groups-collapse", "data-groups-expand",
            "data-tags-collapse", "data-tags-expand",
            "data-publishers-collapse", "data-publishers-expand",
        ):
            self.assertIn(attribute, HTML)
        self.assertIn("setAllGroups", JS)
        self.assertIn("setAllPublishers", JS)
        self.assertIn("tags-collapsed", JS)

    def test_compact_and_mobile_layout_rules_exist(self) -> None:
        self.assertIn("min-height: 56px", CSS)
        self.assertIn("grid-template-columns: repeat(12", CSS)
        self.assertIn("@media (max-width: 760px)", CSS)
        self.assertIn("grid-template-columns: repeat(2", CSS)
        self.assertIn("overflow-x: auto", CSS)
        self.assertIn(".action-menu-popover", CSS)


if __name__ == "__main__":
    unittest.main()
