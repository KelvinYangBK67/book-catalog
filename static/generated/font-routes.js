/* GENERATED FILE — DO NOT EDIT.
 * Rebuild: python scripts/generate_web_fonts.py
 */
export const FONT_ROUTE_ALIASES = Object.freeze({
  "manchu": "manchu",
  "mongolian": "mongolian",
  "ᠮᠣᠩᠭᠣᠯ": "mongolian",
  "满文": "manchu",
  "滿文": "manchu",
  "蒙古文": "mongolian",
  "蒙文": "mongolian"
});
export function resolveCatalogFontRoute(value) {
  const terms = String(value || '').split(/[;；,，、·]/).map((item) => item.trim().toLocaleLowerCase()).filter(Boolean);
  for (const term of terms) {
    if (FONT_ROUTE_ALIASES[term]) return FONT_ROUTE_ALIASES[term].replaceAll('_', '-');
  }
  return '';
}
