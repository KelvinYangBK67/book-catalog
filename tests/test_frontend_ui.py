from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CATALOG_MODEL = (ROOT / "static" / "catalog-model.js").read_text(encoding="utf-8")
SPECIAL_TEXT = (ROOT / "static" / "special-text.js").read_text(encoding="utf-8")
IDENTIFIER_VALIDATION = (
    ROOT / "static" / "identifier-validation.js"
).read_text(encoding="utf-8")
GENERATED = ROOT / "static" / "generated"
FONTS = (GENERATED / "fonts.css").read_text(encoding="utf-8")
FONT_ROUTES = (GENERATED / "font-routes.js").read_text(encoding="utf-8")
FONT_MANIFEST = json.loads(
    (GENERATED / "font-manifest.json").read_text(encoding="utf-8")
)


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
            "work.tags",
        ):
            self.assertLess(HTML.index(f'name="{name}"'), first_disclosure)
        for name in (
            "edition.publication_year", "edition.version",
            "edition.identifier", "edition.title", "edition.subtitle",
            "edition.series", "edition.publisher", "edition.edition_scripts",
            "edition.responsibility", "edition.other_title",
            "copy.location", "copy.acquisition_date", "copy.reading_record",
        ):
            self.assertGreater(HTML.index(f'name="{name}"'), first_disclosure)
        self.assertIn('class="span-7">題名', HTML)
        self.assertIn('class="span-5">副題名', HTML)
        self.assertEqual(HTML.count('class="span-7">作者或主要責任人'), 2)
        self.assertEqual(HTML.count('class="span-5">文種'), 2)
        self.assertIn('class="span-12">出版社<input name="edition.publisher"', HTML)

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
        self.assertIn("--ui-font: var(--font-sans)", CSS)
        self.assertIn("--book-font: var(--font-serif)", CSS)
        self.assertIn("--book-title-font: var(--font-bold)", CSS)
        self.assertIn(".rendered-text { unicode-bidi: plaintext; }", CSS)
        self.assertNotIn("bibliographic-input", CSS + SPECIAL_TEXT)
        self.assertIn("font: 14px/1.5 var(--ui-font)", CSS)
        self.assertIn("font-family: var(--ui-font);", CSS)
        self.assertIn("min-height: 40px", CSS)
        self.assertIn("padding: 8px 10px", CSS)
        self.assertIn("line-height: 1.55", CSS)
        self.assertIn("grid-template-columns: 24px minmax(0, 1fr) auto", CSS)
        self.assertIn("#publisher-normalize-form { align-items: start; }", CSS)
        self.assertIn("list-style: none", CSS)
        self.assertIn("script-input-override", SPECIAL_TEXT)

    def test_dialog_errors_and_soft_isbn_warnings_are_local_and_persistent(self) -> None:
        self.assertIn("error.validationErrors", (
            ROOT / "static" / "api.js"
        ).read_text(encoding="utf-8"))
        self.assertIn("function showFormError", JS)
        self.assertIn("installFormErrorHandling()", JS)
        self.assertIn("showFormError(form, error)", JS)
        self.assertIn("showFormError(editForm, error)", JS)
        self.assertIn("renderIdentifiers(edition.identifier)", JS)
        self.assertIn("identifierWarnings", IDENTIFIER_VALIDATION)
        self.assertIn("疑似 ISBN", IDENTIFIER_VALIDATION)
        self.assertIn(".form-message", CSS)
        self.assertIn(".identifier-form-warning", CSS)

    def test_impe_catalog_generates_three_explicit_web_roles(self) -> None:
        self.assertIn("GENERATED FILE — DO NOT EDIT", FONTS)
        for role in ("Library Sans", "Library Serif", "Library Bold"):
            self.assertIn(f'font-family: "{role}"', FONTS)
        for path in (
            "/fonts/hindi/NotoSansDevanagari-Regular.ttf",
            "/fonts/tibetan/NotoSerifTibetan-Regular.ttf",
            "/fonts/tibetan/NotoSerifTibetan-Bold.ttf",
            "/fonts/tangut/NotoSerifTangut-Regular.ttf",
            "/fonts/korean/NotoSansKR-Regular.ttf",
            "/fonts/mongolian/mnglwhiteotf.ttf",
            "/fonts/mongolian/NotoSansMongolian-Regular.ttf",
            "/fonts/mongolian/mngltitleotf.ttf",
            "/fonts/arabic/NotoNaskhArabic-Regular.ttf",
        ):
            self.assertIn(path, FONTS)
        self.assertNotIn("Library UI", FONTS + CSS)
        self.assertNotIn("Library Bibliographic", FONTS + CSS)

    def test_generated_manifest_resolves_fallbacks_and_metadata_overrides(self) -> None:
        families = FONT_MANIFEST["families"]
        for family_id in (
            "libertinus",
            "chinese_simplified",
            "chinese_traditional",
            "japanese",
            "korean",
            "tibetan",
            "devanagari",
            "arabic",
            "hebrew",
            "syriac",
            "tamil",
            "thai",
            "mongolian",
            "mongolian_baiti",
            "manchu",
            "tangut",
        ):
            self.assertIn(family_id, families)
            for role in ("regular", "sans", "bold"):
                self.assertTrue(families[family_id]["urls"][role])
        self.assertEqual(
            FONT_MANIFEST["style_fallbacks"],
            {
                "bold": "regular",
                "italic": "regular",
                "sans": "regular",
                "sansbold": "sans",
                "mono": "regular",
                "monobold": "mono",
            },
        )
        self.assertEqual(
            families["tibetan"]["faces"]["bold"],
            "NotoSerifTibetan-Bold.ttf",
        )
        self.assertEqual(
            families["tangut"]["face_sources"]["bold"],
            "regular",
        )
        self.assertEqual(FONT_MANIFEST["aliases"]["蒙古文"], "mongolian")
        self.assertEqual(FONT_MANIFEST["aliases"]["滿文"], "manchu")
        self.assertNotIn("日文", FONT_MANIFEST["aliases"])
        self.assertNotIn("梵文", FONT_MANIFEST["aliases"])
        self.assertEqual(
            FONT_MANIFEST["profile_defaults"]["cjk-tc"],
            "shanggu",
        )
        self.assertEqual(
            FONT_MANIFEST["profile_defaults"]["mongolian"],
            "mongolian",
        )
        self.assertEqual(
            FONT_MANIFEST["aggregate_profile_extensions"]["latin"],
            ["greek", "cyrillic"],
        )
        self.assertIn(
            '.font-serif[data-font-route="mongolian"]',
            FONTS,
        )
        self.assertIn('.font-serif[data-font-route="manchu"]', FONTS)
        self.assertNotIn('data-font-route="japanese"', FONTS)
        self.assertNotIn('data-font-route="tibetan"', FONTS)
        self.assertIn("replaceAll('_', '-')", FONT_ROUTES)

    def test_unicode_ranges_route_mixed_scripts_and_shared_mongolian_block(self) -> None:
        libertinus_face = next(
            line for line in FONTS.splitlines()
            if 'font-family: "Library Serif"' in line
            and "LibertinusSerif-Regular" in line
        )
        for unicode_range in (
            "U+0100-017F",  # Śāntideva
            "U+0370-03FF",  # Πλάτων
            "U+0400-04FF",  # Пушкин
        ):
            self.assertIn(unicode_range, libertinus_face)

        devanagari_face = next(
            line for line in FONTS.splitlines()
            if 'font-family: "Library Serif"' in line
            and "NotoSerifDevanagari" in line
        )
        self.assertIn("U+0900-0950", devanagari_face)
        japanese_face = next(
            line for line in FONTS.splitlines()
            if 'font-family: "Library Serif"' in line
            and "NotoSerifJP" in line
        )
        self.assertIn("U+3040-309F", japanese_face)
        self.assertNotIn("U+4E00-9FFF", japanese_face)
        shanggu_face = next(
            line for line in FONTS.splitlines()
            if 'font-family: "Library Serif"' in line
            and "ShangguSerif-Regular" in line
        )
        self.assertIn("U+4E00-9FFF", shanggu_face)

        override_faces = "\n".join(FONTS.splitlines()[:12])
        self.assertIn("mongolian/mnglwhiteotf.ttf", override_faces)
        self.assertIn("mongolian/NotoSansMongolian-Regular.ttf", override_faces)
        self.assertIn("mongolian/mngltitleotf.ttf", override_faces)
        self.assertNotIn("mongolian_baiti/monbaiti.ttf", override_faces)
        self.assertIn('manchu/Ab-Xy.ttf', override_faces)
        self.assertIn('manchu/Ab-Xy_B.ttf', override_faces)
        for unicode_range in ("U+1800-18AF", "U+200C-200D", "U+202F"):
            self.assertIn(unicode_range, override_faces)

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
        self.assertIn("export function renderText", SPECIAL_TEXT)
        self.assertIn("resolveCatalogFontRoute", SPECIAL_TEXT)
        self.assertIn("window.hierojax.processFragment", SPECIAL_TEXT)
        self.assertIn("special-text-preview", SPECIAL_TEXT)
        self.assertIn("mongolian-script-run", SPECIAL_TEXT)
        self.assertIn("manchu-script-run", SPECIAL_TEXT)
        self.assertIn("\\u1800-\\u18AF", SPECIAL_TEXT)
        self.assertIn("\\u200C\\u200D\\u202F", SPECIAL_TEXT)
        self.assertIn('route === "mongolian" || route === "manchu"', SPECIAL_TEXT)
        self.assertIn('control.classList.toggle("font-sans", hasOverride)', SPECIAL_TEXT)
        self.assertNotIn('classList.add("font-serif"', SPECIAL_TEXT)
        self.assertIn(".mongolian-script-run,\n.manchu-script-run", CSS)
        self.assertIn("font-size: 1.3em", CSS)
        self.assertIn("white-space: nowrap", CSS)
        self.assertIn("overflow-wrap: normal", CSS)
        self.assertIn("word-break: keep-all", CSS)
        self.assertIn('import {escapeHtml}', SPECIAL_TEXT)
        self.assertIn("bibliographicTitle(work.title, work.scripts)", JS)
        self.assertIn("bibliographicText(work.subtitle, work.scripts)", JS)
        self.assertIn("bibliographicText(work.authors, work.scripts)", JS)
        self.assertIn('document.querySelectorAll("input, textarea").forEach(updateInputRendering)', SPECIAL_TEXT)
        self.assertNotIn("renderBibliographicText", SPECIAL_TEXT + JS)
        self.assertIn("family: \"serif\"", SPECIAL_TEXT)
        self.assertIn("family: \"bold\"", JS)
        self.assertNotIn("svg", HTML[HTML.index('name="work.title"'):HTML.index('name="work.authors"')])


if __name__ == "__main__":
    unittest.main()
