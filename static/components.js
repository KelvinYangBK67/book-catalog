export function actionMenu(layer, id, items) {
  return `<details class="action-menu" data-action-menu>
    <summary aria-label="操作" title="操作">⋯</summary>
    <div class="action-menu-popover">
      ${items.map((item) => `<button type="button"
        class="${item.danger ? 'danger-item' : ''}"
        data-layer-action="${item.action}" data-layer="${layer}" data-layer-id="${id}">${item.label}</button>`).join('')}
    </div>
  </details>`;
}

function hasValue(control) {
  if (control.disabled || control.type === 'hidden' || control.type === 'radio') return false;
  if (control.closest('.edition-work-link-row[data-implicit-work="true"]')) return false;
  if (control.type === 'checkbox') return control.checked;
  if (control.multiple) return Array.from(control.selectedOptions).some((option) => option.value);
  return String(control.value || '').trim() !== '';
}

export function updateDisclosureCounts(root = document) {
  root.querySelectorAll('[data-disclosure]').forEach((details) => {
    const label = details.querySelector('[data-disclosure-label]');
    if (!label) return;
    const count = Array.from(details.querySelectorAll('input, select, textarea'))
      .filter(hasValue).length;
    const base = label.dataset.label || label.textContent.split(' · ')[0];
    label.textContent = count ? `${base} · ${count} 項` : base;
    details.classList.toggle('has-values', count > 0);
  });
}


export function closeActionMenus(except = null) {
  document.querySelectorAll('[data-action-menu][open]').forEach((menu) => {
    if (menu !== except) menu.open = false;
  });
}
