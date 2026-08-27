import {escapeHtml, splitTerms} from "./formatters.js";

function compactIsbn(value) {
  return String(value || '').split('/', 1)[0].replace(/[\s-]/g, '').toUpperCase();
}

function validIsbn10(value) {
  if (!/^\d{9}[\dX]$/.test(value)) return false;
  const check = value[9] === 'X' ? 10 : Number(value[9]);
  const sum = [...value.slice(0, 9)].reduce(
    (total, digit, index) => total + (10 - index) * Number(digit), check
  );
  return sum % 11 === 0;
}

function validIsbn13(value) {
  if (!/^97[89]\d{10}$/.test(value)) return false;
  const sum = [...value.slice(0, 12)].reduce(
    (total, digit, index) => total + Number(digit) * (index % 2 ? 3 : 1), 0
  );
  return (10 - sum % 10) % 10 === Number(value[12]);
}

export function identifierWarnings(value) {
  const warnings = [];
  for (let part of splitTerms(value)) {
    part = part.replace(/\s*\((?:hbk|pbk|ebook)\.?\)\s*$/i, '').trim();
    const explicit = part.match(/^ISBN\s*[:：]?\s*(.+)$/i);
    if (explicit) {
      const main = compactIsbn(explicit[1]);
      const shaped = /^\d{9}[\dX]$/.test(main) || /^\d{13}$/.test(main);
      if (!shaped) {
        warnings.push('ISBN 格式無效，請核對實物；仍可保存。');
      } else if (!validIsbn10(main) && !validIsbn13(main)) {
        warnings.push('ISBN 校驗碼不正確，請核對實物；仍可保存。');
      }
      continue;
    }
    const generic = part.match(/^識別號\s+(.+)$/);
    if (generic) {
      const main = compactIsbn(generic[1]);
      const isbnShape = /^\d{9}[\dX]$/.test(main) || /^97[89]\d{10}$/.test(main);
      if (isbnShape && !validIsbn10(main) && !validIsbn13(main)) {
        warnings.push('疑似 ISBN，校驗未通過；仍保留為普通識別號。');
      }
    }
  }
  return [...new Set(warnings)];
}

export function renderIdentifiers(value, separator = '<br>') {
  return splitTerms(value).map((item) => {
    const warning = identifierWarnings(item);
    const marker = warning.length
      ? ' <span class="identifier-warning-mark" title="' + escapeHtml(warning.join(' ')) + '">⚠</span>'
      : '';
    return escapeHtml(item) + marker;
  }).join(separator);
}
