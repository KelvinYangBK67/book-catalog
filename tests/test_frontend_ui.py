from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CATALOG_MODEL = (ROOT / "static" / "catalog-model.js").read_text(encoding="utf-8")
SPECIAL_TEXT = (ROOT / "static" / "special-text.js").read_text(encoding="utf-8")


class FrontendStructureTests(unittest.TestCase):
    def test_plain_modules_are_split_without_framework(self) -> None:
        self.assertIn('type="module" src="/static/app.js', HTML)
        for filename in ("api.js", "state.js", "components.js", "formatters.js", "catalog-model.js"):
            self.assertTrue((ROOT / "static" / filename).exists())
        self.assertIn('from "./api.js"', JS)
        self.assertNotIn("React", HTML + JS)
        self.assertNotIn("Vue", HTML + JS)

    def test_quick_entry_contains_only_daily_fields(self) -> None:
        first_disclosure = HTML.index('<details class="form-disclosure"')
        for name in (
            "work.title", "work.subtitle", "work.authors", "work.scripts",
            "work.tags", "edition.publisher",
        ):
            self.assertLess(HTML.index(f'name="{name}"'), first_disclosure)
        for name in (
            "edition.publication_year", "edition.version",
            "edition.identifier", "edition.title", "edition.subtitle",
            "edition.series", "edition.edition_scripts",
            "edition.responsibility", "edition.other_title",
            "copy.location", "copy.acquisition_date", "copy.reading_record",
        ):
            self.assertGreater(HTML.index(f'name="{name}"'), first_disclosure)
        self.assertIn('class="span-7">題名', HTML)
        self.assertIn('class="span-5">副題名', HTML)

    def test_low_frequency_fields_are_progressively_disclosed(self) -> None:
        for label in (
            "更多版本資料", "其他館藏資料", "進階結構",
        ):
            self.assertIn(f'data-label="{label}"', HTML)
        self.assertNotIn('data-label="更多作品資料"', HTML)
        self.assertIn('data-add-volume-fields>＋ 新增冊', HTML)
        self.assertIn('data-volume-form-fields hidden', HTML)
        self.assertIn('data-volume-inherits checked', HTML)
        self.assertIn('data-volume-override-fields hidden', HTML)
        self.assertNotIn('data-label="冊資料"', HTML)
        self.assertNotIn('data-label="冊級例外"', HTML)
        self.assertIn("updateDisclosureCounts(form)", JS)
        self.assertIn("currentForm.addEventListener('input'", JS)
        self.assertIn("details.classList.toggle('has-values'", (
            ROOT / "static" / "components.js"
        ).read_text(encoding="utf-8"))

    def test_volume_overrides_are_real_volume_inputs(self) -> None:
        self.assertIn('name="volume.version"', HTML)
        self.assertIn('name="volume.publication_year"', HTML)
        self.assertIn('name="volume.responsibility"', HTML)
        self.assertIn("? '' : get('volume.version')", JS)
        self.assertIn("? '' : get('volume.responsibility')", JS)

    def test_translation_fields_are_conditional_and_responsibilities_are_separate(self) -> None:
        self.assertEqual(HTML.count("data-translation-toggle"), 2)
        self.assertEqual(HTML.count("data-translation-identity"), 2)
        self.assertEqual(HTML.count('data-identity-control="title"'), 2)
        self.assertNotIn("data-translation-fields", HTML)
        self.assertIn('name="edition.responsibility"', HTML)
        self.assertIn('name="responsibility"', HTML)
        self.assertIn("responsibility: get('edition.responsibility')", JS)
        self.assertIn("syncTranslationIdentity", JS)
        self.assertIn("translationStoreName", JS)
        self.assertIn("updateTranslationFields", JS)

    def test_regression_copy_volume_and_dialog_state_controls(self) -> None:
        self.assertIn('data-remove-volume-fields', HTML)
        self.assertIn("clearUnsavedVolumeFields", JS)
        self.assertIn("bookDialog.scrollTop = 0", JS)
        self.assertIn("setBookVolumeFieldsVisible(false)", JS)
        self.assertIn("form.elements.namedItem('copy-mode').value = 'single'", JS)
        self.assertIn("form.querySelector('[data-volume-inherits]').checked = true", JS)

    def test_ui_copy_uses_no_full_width_slash(self) -> None:
        self.assertNotIn("／", HTML + JS)

    def test_new_and_edit_forms_share_the_twelve_column_grid(self) -> None:
        for form_id in (
            "book-form", "work-edit-form", "edition-edit-form",
            "volume-edit-form", "copy-edit-form",
        ):
            start = HTML.index(f'id="{form_id}"')
            end = HTML.index("</form>", start)
            self.assertIn('class="form-grid"', HTML[start:end])
        self.assertNotIn('class="fields two"', HTML)

    def test_detail_hierarchy_is_progressive_and_add_actions_are_separate(self) -> None:
        self.assertIn('data-layer-toggle="edition"', JS)
        self.assertIn('data-layer-toggle="volume"', JS)
        self.assertIn("data-layer-content hidden", JS)
        self.assertIn("layerAddButton('work'", JS)
        self.assertIn("layerAddButton('edition'", JS)
        self.assertIn("layerAddButton('volume'", JS)
        work_menu = JS[JS.index("function workMenu"):JS.index("function editionMenu")]
        edition_menu = JS[JS.index("function editionMenu"):JS.index("function volumeMenu")]
        volume_menu = JS[JS.index("function volumeMenu"):JS.index("function copyMenu")]
        self.assertNotIn("add-edition", work_menu)
        self.assertNotIn("add-volume", edition_menu)
        self.assertNotIn("add-copy", edition_menu + volume_menu)

    def test_internal_model_names_and_ids_are_not_presented(self) -> None:
        self.assertNotIn(">Work<", HTML)
        self.assertNotIn(">Edition<", HTML)
        self.assertNotIn(">VOLUME<", HTML)
        self.assertNotIn(">COPY<", HTML)
        self.assertNotIn("EDITION VIEW", JS)
        self.assertNotIn("實物副本 #", JS)
        for function_name in ("function editionTopDisplay", "function editionDisplayData"):
            block_start = JS.index(function_name)
            block_end = JS.index("\n}", block_start)
            self.assertNotIn("版本資料", JS[block_start:block_end])

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

    def test_tag_parent_candidates_and_browse_tree_use_real_hierarchy(self) -> None:
        self.assertIn("function tagDescendantIds", JS)
        self.assertIn("function legalTagParents", JS)
        self.assertIn("tag.direct_work_count ?? tag.assigned_work_count", JS)
        parent_options = JS[JS.index("function tagParentOptions"):JS.index(
            "function renderPublisherControls"
        )]
        self.assertNotIn("disabled", parent_options)
        self.assertIn("function subtreeWorkIds", JS)
        self.assertIn("function browseTagTree", JS)
        self.assertIn("data-browse-tag-toggle", JS)
        self.assertIn("data-browse-tag-select", JS)
        self.assertIn("counts.get(tag.id).size", JS)

    def test_work_header_and_edition_summary_are_natural_information_flows(self) -> None:
        work_detail = JS[JS.index("function renderWorkDetail"):JS.index(
            "function renderEditionTopDetail"
        )]
        self.assertIn("detail-title-scripts", work_detail)
        self.assertIn("work-detail-meta", work_detail)
        self.assertNotIn("<small>文種</small>", work_detail)
        edition_header = JS[JS.index("function editionHeader"):JS.index(
            "function publisherDisplay"
        )]
        self.assertIn("edition-responsibility", edition_header)
        self.assertIn("edition-bibliography", edition_header)
        self.assertNotIn("edition-summary-identifiers", edition_header)
        self.assertNotIn("border-top", edition_header)
        self.assertIn("editionSummaryData", JS)
        self.assertIn("usedFields.has('translated_title')", JS)
        self.assertNotIn("detail-header-actions", HTML + JS)
        self.assertIn("work-summary-action-row", JS)

    def test_volume_sort_prefers_natural_number_then_position(self) -> None:
        sort_block = CATALOG_MODEL[CATALOG_MODEL.index("export function groupedVolumes"):]
        natural_index = sort_block.index("naturalVolumeCompare")
        position_index = sort_block.index("(left.position ?? 0)", natural_index)
        self.assertLess(natural_index, position_index)
        self.assertIn("if (leftNumber && rightNumber)", sort_block)
        self.assertIn("if (Boolean(leftNumber) !== Boolean(rightNumber))", sort_block)

    def test_compact_and_mobile_layout_rules_exist(self) -> None:
        self.assertIn("min-height: 56px", CSS)
        self.assertIn("grid-template-columns: repeat(12", CSS)
        self.assertIn("@media (max-width: 760px)", CSS)
        self.assertIn("grid-template-columns: repeat(2", CSS)
        self.assertIn("overflow-x: auto", CSS)
        self.assertIn(".action-menu-popover", CSS)

    def test_css_is_consolidated_and_uses_distinct_font_roles(self) -> None:
        self.assertNotIn("Compact application shell", CSS)
        self.assertNotIn("Second-pass entry", CSS)
        self.assertNotIn("min-height: 42px", CSS)
        self.assertNotIn("height: 43px", CSS)
        self.assertIn('--ui-font: "Library UI Latin", "Library UI Han"', CSS)
        self.assertIn(".bibliographic-text, .bibliographic-input", CSS)
        self.assertIn("font: 14px/1.5 var(--ui-font)", CSS)
        self.assertIn("min-height: 40px", CSS)
        self.assertIn("padding: 8px 10px", CSS)
        self.assertIn("line-height: 1.55", CSS)
        self.assertIn("grid-template-columns: 24px minmax(0, 1fr) auto", CSS)
        self.assertIn("#publisher-normalize-form { align-items: start; }", CSS)
        self.assertIn("list-style: none", CSS)
        self.assertIn("BIBLIOGRAPHIC_SELECTOR", SPECIAL_TEXT)

    def test_home_is_tool_focused_and_mobile_actions_are_collapsed(self) -> None:
        self.assertIn('id="catalog-title">我的藏書', HTML)
        self.assertNotIn("每一本書，都有它的位置。", HTML)
        self.assertNotIn("PERSONAL LIBRARY", HTML)
        self.assertEqual(HTML.count('id="book-count"'), 1)
        self.assertIn('id="mobile-more-button"', HTML)
        self.assertIn('id="secondary-actions"', HTML)
        self.assertIn("function setupMobileActions", JS)
        self.assertIn(".secondary-actions.is-open", CSS)

    def test_special_script_renderer_is_local_and_keeps_unicode_inputs(self) -> None:
        vendor = ROOT / "static" / "vendor" / "hierojax"
        for filename in ("hierojax.js", "hierojax.css", "NewGardiner.otf", "LICENSE", "VENDORED.md"):
            self.assertTrue((vendor / filename).exists())
        self.assertIn("/static/vendor/hierojax/hierojax.js", HTML)
        self.assertNotIn("cdn", HTML.lower())
        self.assertIn("renderBibliographicText", SPECIAL_TEXT)
        self.assertIn("window.hierojax.processFragment", SPECIAL_TEXT)
        self.assertIn("special-text-preview", SPECIAL_TEXT)
        self.assertIn('import {escapeHtml}', SPECIAL_TEXT)
        self.assertIn("renderBibliographicText(work.title)", JS)
        self.assertNotIn("svg", HTML[HTML.index('name="work.title"'):HTML.index('name="work.authors"')])


if __name__ == "__main__":
    unittest.main()
