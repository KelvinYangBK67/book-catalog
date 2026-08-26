const PREFIX = 'book-catalog-';

export function getPreference(key, fallback = '') {
  return localStorage.getItem(PREFIX + key) ?? fallback;
}

export function setPreference(key, value) {
  localStorage.setItem(PREFIX + key, String(value));
}

export function getBooleanPreference(key, fallback = false) {
  const value = localStorage.getItem(PREFIX + key);
  return value === null ? fallback : value === 'true';
}
