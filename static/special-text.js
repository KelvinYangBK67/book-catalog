import {escapeHtml} from "./formatters.js";
import {resolveCatalogFontRoute} from "./generated/font-routes.js";

const EGYPTIAN_CHARACTER = /[\u{13000}-\u{1345F}]/u;
const EGYPTIAN_RUN = /([\u{13000}-\u{1345F}\uFE00-\uFE0F]+)/gu;
const TEXT_FAMILIES = new Set(["sans", "serif", "bold"]);
const BIBLIOGRAPHIC_FIELD_NAMES = new Set([
  "title",
  "subtitle",
  "translated_title",
  "translated_subtitle",
  "other_title",
  "other_subtitle",
  "volume_title",
  "authors",
  "series",
  "responsibility",
  "translator"
]);
const PREVIEW_FIELD_NAMES = new Set([
  "title",
  "subtitle",
  "translated_title",
  "translated_subtitle",
  "other_title",
  "other_subtitle",
  "volume_title"
]);
const BIBLIOGRAPHIC_SELECTOR = [
  "[data-identity-control]",
  "[data-work-search-title]",
  "[data-work-search-subtitle]",
  "[data-work-search-authors]",
  "[data-edition-search-title]",
  "[data-edition-search-subtitle]"
].join(",");
let renderQueued = false;

function fieldName(control) {
  return String(control.name || "").split(".").pop();
}

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

export function renderText(value, options = {}) {
  const tag = /^[a-z][a-z0-9-]*$/i.test(options.tag || "")
    ? options.tag : "span";
  const family = TEXT_FAMILIES.has(options.family) ? options.family : "serif";
  const route = resolveCatalogFontRoute(options.script);
  const className = [
    "rendered-text",
    "font-" + family,
    options.className || ""
  ].filter(Boolean).join(" ");
  const routeAttribute = route
    ? ' data-font-route="' + escapeHtml(route) + '"' : "";
  return "<" + tag + ' class="' + escapeHtml(className) + '" dir="auto"'
    + routeAttribute + ">" + renderTextRuns(value) + "</" + tag + ">";
}

function processPendingHieroglyphs() {
  renderQueued = false;
  if (!window.hierojax) return;
  document.querySelectorAll(
    '.hierojax[data-special-source="egyptian"]:not([data-special-rendered])'
  ).forEach((node) => {
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
  return control.matches("input, textarea")
    && (
      BIBLIOGRAPHIC_FIELD_NAMES.has(fieldName(control))
      || control.matches(BIBLIOGRAPHIC_SELECTOR)
    );
}

function supportsSpecialPreview(control) {
  return PREVIEW_FIELD_NAMES.has(fieldName(control))
    || control.matches(
      '[data-identity-control="title"], [data-identity-control="subtitle"]'
    );
}

function scriptMetadataFor(control) {
  const form = control.closest("form");
  if (!form) return "";
  const fields = [
    "edition.edition_scripts",
    "work.scripts",
    "edition_scripts",
    "scripts"
  ];
  for (const name of fields) {
    const value = form.elements.namedItem(name)?.value?.trim();
    if (value) return value;
  }
  return "";
}

function updateInputPreview(control) {
  if (!isBibliographicInput(control)) return;
  control.classList.add("font-serif", "bibliographic-input");
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
  preview.innerHTML = '<small>預覽</small>' + renderText(control.value, {
    tag: "div",
    family: "serif",
    script: scriptMetadataFor(control)
  });
  scheduleSpecialTextRender();
}

export function initializeSpecialTextRenderer() {
  document.querySelectorAll("input, textarea").forEach(updateInputPreview);
  document.addEventListener("input", (event) => updateInputPreview(event.target));
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue;
        if (node.matches("input, textarea")) updateInputPreview(node);
        node.querySelectorAll?.("input, textarea").forEach(updateInputPreview);
      }
    }
    scheduleSpecialTextRender();
  });
  observer.observe(document.body, {childList: true, subtree: true});
  scheduleSpecialTextRender();
}
