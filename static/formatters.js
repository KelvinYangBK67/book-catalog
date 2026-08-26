export const escapeHtml = (value) => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

export function splitTerms(value) {
  return String(value || '')
    .replace(/[；、，]/g, ';')
    .split(';')
    .map((part) => part.trim())
    .filter(Boolean);
}

export function naturalVolumeCompare(left, right) {
  const numeric = (value) => /^\d+(?:\.\d+)*$/.test(value)
    ? value.split('.').map(Number) : null;
  const a = numeric(left);
  const b = numeric(right);
  if (a && b) {
    const size = Math.max(a.length, b.length);
    for (let index = 0; index < size; index += 1) {
      const difference = (a[index] ?? -1) - (b[index] ?? -1);
      if (difference) return difference;
    }
    return 0;
  }
  if (a) return -1;
  if (b) return 1;
  return left.localeCompare(right, 'zh-Hant', {numeric: true});
}
