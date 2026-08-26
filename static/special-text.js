import {escapeHtml} from "./formatters.js";

const EGYPTIAN_CHARACTER = /[𓀀-𔏿]/u;
const EGYPTIAN_RUN = /([𓀀-𔏿︀-️]+)/gu;
const BIBLIOGRAPHIC_FIELD = /(?:^|\.)(?:title|subtitle|translated_title|translated_subtitle|other_title|other_subtitle|volume_title|authors|scripts|edition_scripts|publisher|series|responsibility|translator|location|reading_record|tag_names?|tags)$/;
const PREVIEW_FIELD = /(?:^|\.)(?:title|subtitle|translated_title|translated_subtitle|other_title|other_subtitle|volume_title)$/;
const BIBLIOGRAPHIC_SELECTOR = [
  ".bibliographic-input",
  ".tag-picker-input",
  "[data-identity-control]",
  "[data-work-search-title]",
  "[data-work-search-subtitle]",
  "[data-work-search-authors]",
  "[data-edition-search-title]",
  "[data-edition-search-subtitle]",
  "[data-edition-search-publisher]",
  "#tag-name",
  "#tag-edit-name",
  "#tag-parent",
  "#tag-edit-parent",
  "#publisher-canonical-name"
].join(",");
let renderQueued = false;

export function containsEgyptianText(value) {
  return EGYPTIAN_CHARACTER.test(String(value || ""));
}

function renderTextRuns(value) {
  const source = String(value || "");
  let offset = 0;
  let html = "";
  for (const match of source.matchAll(EGYPTIAN_RUN)) {
    html += escapeHtml(source.slice(offset, match.index));
    html += '<span class="hierojax" data-type="svg" data-special-source="egyptian">'
      + escapeHtml(match[0]) + "</span>";
    offset = match.index + match[0].length;
  }
  return html + escapeHtml(source.slice(offset));
}

export function renderBibliographicText(value, options = {}) {
  const tag = options.tag || "span";
  const className = ["bibliographic-text", options.className || ""].filter(Boolean).join(" ");
  return "<" + tag + ' class="' + className + '" dir="auto">'
    + renderTextRuns(value) + "</" + tag + ">";
}

function processPendingHieroglyphs() {
  renderQueued = false;
  if (!window.hierojax) return;
  document.querySelectorAll('.hierojax[data-special-source="egyptian"]:not([data-special-rendered])')
    .forEach((node) => {
      node.dataset.specialRendered = "true";
      window.hierojax.processFragment(node);
    });
}

export function scheduleSpecialTextRender() {
  if (renderQueued) return;
  renderQueued = true;
  window.requestAnimationFrame(processPendingHieroglyphs);
}

function isBibliographicInput(control) {
  return control.matches("input, textarea, select")
    && (BIBLIOGRAPHIC_FIELD.test(control.name || "") || control.matches(BIBLIOGRAPHIC_SELECTOR));
}

function supportsSpecialPreview(control) {
  return PREVIEW_FIELD.test(control.name || "")
    || control.matches('[data-identity-control="title"], [data-identity-control="subtitle"]');
}

function updateInputPreview(control) {
  if (!isBibliographicInput(control)) return;
  control.classList.add("bibliographic-input");
  if (!supportsSpecialPreview(control)) return;
  const label = control.closest("label");
  if (!label) return;
  let preview = label.querySelector(":scope > .special-text-preview");
  if (!containsEgyptianText(control.value)) {
    preview?.remove();
    return;
  }
  if (!preview) {
    preview = document.createElement("div");
    preview.className = "special-text-preview";
    label.appendChild(preview);
  }
  preview.innerHTML = '<small>預覽</small>' + renderBibliographicText(control.value, {tag: "div"});
  scheduleSpecialTextRender();
}

export function initializeSpecialTextRenderer() {
  document.querySelectorAll("input, textarea, select").forEach(updateInputPreview);
  document.addEventListener("input", (event) => updateInputPreview(event.target));
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue;
        if (node.matches("input, textarea, select")) updateInputPreview(node);
        node.querySelectorAll?.("input, textarea, select").forEach(updateInputPreview);
      }
    }
    scheduleSpecialTextRender();
  });
  observer.observe(document.body, {childList: true, subtree: true});
  scheduleSpecialTextRender();
}
