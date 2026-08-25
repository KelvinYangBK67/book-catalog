const list = document.querySelector('#book-list');
const count = document.querySelector('#book-count');
const notice = document.querySelector('#notice');
const searchForm = document.querySelector('#search-form');
const searchInput = document.querySelector('#search-input');
const bookDialog = document.querySelector('#book-dialog');
const detailDialog = document.querySelector('#detail-dialog');
const copyDialog = document.querySelector('#copy-dialog');
const tagsDialog = document.querySelector('#tags-dialog');
const publishersDialog = document.querySelector('#publishers-dialog');
const importDialog = document.querySelector('#import-dialog');
const csvFileInput = document.querySelector('#csv-file-input');
const viewSelect = document.querySelector('#view-select');
const topModeSelect = document.querySelector('#top-mode-select');
const groupIndex = document.querySelector('#group-index');
const collectionLayout = document.querySelector('.collection-layout');
const workEditDialog = document.querySelector('#work-edit-dialog');
const editionEditDialog = document.querySelector('#edition-edit-dialog');
const copyEditDialog = document.querySelector('#copy-edit-dialog');
const form = document.querySelector('#book-form');
const saveButton = document.querySelector('#save-button');
let works = [];
let books = [];
let editionEntries = [];
let editionOptions = [];
let editingWorkId = null;
let smartWorkExclusions = new Map();
let workOptions = [];
let activeWork = null;
let activeBook = null;
let activeEdition = null;
let activeTopEditionId = null;
let tags = [];
let tagViolations = [];
let publishers = [];
let publisherNames = [];
let selectedTagId = null;
let importRows = [];

const escapeHtml = (value) => String(value ?? '')
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
const shown = (value) => value === null || value === undefined || value === '' ? '—' : escapeHtml(value);

function shownLines(value) {
  const parts = splitTerms(value);
  return parts.length
    ? `<span class="multiline-value">${parts.map(escapeHtml).join('<br>')}</span>`
    : '—';
}

function flash(message, type = 'success') {
  notice.textContent = message;
  notice.dataset.type = type;
  notice.hidden = false;
  setTimeout(() => { notice.hidden = true; }, 5000);
}

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = '操作失敗，請稍後再試。';
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') {
        message = body.detail;
      } else if (Array.isArray(body.detail)) {
        message = body.detail.map((item) => {
          const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join(' → ') : '';
          return field ? `${field}：${item.msg}` : item.msg;
        }).join('；');
      }
    } catch (_) { /* response was not JSON */ }
    throw new Error(message);
  }
  return response.json();
}

async function loadWorks(query = '') {
  list.innerHTML = '<div class="empty">正在整理書架……</div>';
  try {
    [works, books, editionOptions] = await Promise.all([
      request(`/api/works?q=${encodeURIComponent(query)}`),
      request(`/api/books?q=${encodeURIComponent(query)}`),
      request('/api/editions')
    ]);
    workOptions = query ? await request('/api/works') : works;
    editionEntries = buildEditionEntries(books);
    renderWorks(query);
  } catch (error) {
    list.innerHTML = `<div class="empty"><strong>暫時無法讀取藏書</strong>${escapeHtml(error.message)}</div>`;
  }
}

async function loadTags() {
  [tags, tagViolations] = await Promise.all([
    request('/api/tags'), request('/api/tags/violations')
  ]);
  renderTagControls();
}

async function loadPublishers() {
  [publishers, publisherNames] = await Promise.all([
    request('/api/publishers'), request('/api/publishers/names')
  ]);
  renderPublisherControls();
}

function tagAncestors(tag) {
  const parts = tag.path.split(' → ');
  return parts.slice(0, -1).join(' · ');
}

function tagOptionLabel(tag) {
  const ancestors = tagAncestors(tag);
  return tag.name + (ancestors ? ' — ' + ancestors : '');
}

function tagOptionMarkup(selectedIds = []) {
  const selected = new Set(selectedIds.map(Number));
  return tags.filter((tag) => !tag.has_children || selected.has(tag.id)).map((tag) =>
    '<option value="' + tag.id + '" ' + (selected.has(tag.id) ? 'selected' : '') + '>' + escapeHtml(tag.name) + '</option>'
  ).join('');
}

function tagPickerValues(picker) {
  return {
    ids: selectedValues(picker.querySelector('.tag-id-store')),
    names: splitTerms(picker.querySelector('.tag-name-store').value)
  };
}

function renderTagPicker(picker) {
  const stores = tagPickerValues(picker);
  const selectedTags = stores.ids.map((id) => tags.find((tag) => tag.id === id)).filter(Boolean);
  picker.querySelector('.tag-picker-chips').innerHTML = [
    ...selectedTags.map((tag) =>
      '<button class="tag-picker-chip" type="button" data-remove-tag-id="' + tag.id + '" title="' + escapeHtml(tag.path) + '">' + escapeHtml(tag.name) + '<span>×</span></button>'
    ),
    ...stores.names.map((name, index) =>
      '<button class="tag-picker-chip pending" type="button" data-remove-tag-name="' + index + '">' + escapeHtml(name) + '<span>×</span></button>'
    )
  ].join('');
}

function setTagPickerValues(picker, ids = [], names = []) {
  const select = picker.querySelector('.tag-id-store');
  const input = picker.querySelector('.tag-picker-input');
  select.innerHTML = tagOptionMarkup(ids);
  picker.querySelector('.tag-name-store').value = names.join('; ');
  input.value = '';
  input.setCustomValidity('');
  renderTagPicker(picker);
}

function renderTagSuggestions(picker) {
  const input = picker.querySelector('.tag-picker-input');
  const suggestions = picker.querySelector('.tag-picker-suggestions');
  const query = input.value.trim().toLocaleLowerCase();
  const selected = new Set(tagPickerValues(picker).ids);
  const candidates = tags.filter((tag) => !tag.has_children && !selected.has(tag.id))
    .filter((tag) => !query || tag.name.toLocaleLowerCase().includes(query) || tag.path.toLocaleLowerCase().includes(query))
    .slice(0, 12);
  suggestions.innerHTML = candidates.map((tag) => {
    const ancestors = tagAncestors(tag);
    return '<button type="button" data-pick-tag-id="' + tag.id + '"><strong>' + escapeHtml(tag.name) + '</strong>'
      + (ancestors ? '<small>' + escapeHtml(ancestors) + '</small>' : '') + '</button>';
  }).join('') || '<span class="tag-picker-empty">按 Enter 建立新標籤</span>';
  suggestions.hidden = false;
}

function commitTagPickerInput(picker) {
  const input = picker.querySelector('.tag-picker-input');
  const values = splitTerms(input.value);
  if (!values.length) return true;
  const state = tagPickerValues(picker);
  for (const value of values) {
    const matches = tags.filter((tag) => !tag.has_children && tag.name.localeCompare(value, undefined, {sensitivity: 'accent'}) === 0);
    if (matches.length > 1) {
      input.setCustomValidity('存在多個同名標籤，請從候選中選擇。');
      input.reportValidity();
      return false;
    }
    if (matches.length === 1) {
      if (!state.ids.includes(matches[0].id)) state.ids.push(matches[0].id);
    } else if (!state.names.some((name) => name.toLocaleLowerCase() === value.toLocaleLowerCase())) {
      state.names.push(value);
    }
  }
  input.setCustomValidity('');
  setTagPickerValues(picker, state.ids, state.names);
  return true;
}

function renderTagTree(parentId = null) {
  const children = tags.filter((tag) => tag.parent_id === parentId);
  if (!children.length) return '';
  return '<ul class="tag-tree-children">' + children.map((tag) => {
    const descendants = renderTagTree(tag.id);
    const toggle = descendants
      ? '<button class="tag-tree-toggle" type="button" data-tag-toggle aria-expanded="true" aria-label="收合下級">▾</button>'
      : '<span class="tag-tree-leaf" aria-hidden="true">└─</span>';
    return '<li class="tag-tree-node"><div class="tag-tree-row">' + toggle
      + '<span class="tag-tree-label"><strong>' + escapeHtml(tag.name) + '</strong><small>'
      + (tag.has_children ? '分類' : tag.assigned_work_count + ' 部作品') + '</small></span>'
      + '<button class="danger compact" type="button" data-delete-tag="' + tag.id + '">刪除</button></div>'
      + descendants + '</li>';
  }).join('') + '</ul>';
}

function renderTagControls() {
  document.querySelectorAll('[data-tag-picker]').forEach((picker) => {
    const state = tagPickerValues(picker);
    setTagPickerValues(picker, state.ids, state.names);
  });
  const managementOptions = tags.map((tag) => '<option value="' + tag.id + '" '
    + (tag.assigned_work_count ? 'disabled' : '') + '>' + escapeHtml(tagOptionLabel(tag))
    + (tag.assigned_work_count ? '（已有藏書）' : '') + '</option>').join('');
  document.querySelector('#tag-parent').innerHTML = '<option value="">無（頂級分類）</option>' + managementOptions;
  document.querySelector('#tag-tree').innerHTML = tags.length
    ? renderTagTree()
    : '<div class="empty">尚未建立任何標籤。</div>';
  const violationBox = document.querySelector('#tag-violations');
  violationBox.hidden = tagViolations.length === 0;
  violationBox.innerHTML = tagViolations.length
    ? '<strong>需要人工重新分類</strong><p>以下作品仍直接掛在非葉節點；系統未自動搬移：</p><ul>' + tagViolations.map((item) =>
      '<li>' + escapeHtml(item.work_title) + ' → ' + escapeHtml(item.tag_path) + '</li>'
    ).join('') + '</ul>' : '';
  const editSelect = document.querySelector('#tag-edit-id');
  editSelect.innerHTML = tags.map((tag) => '<option value="' + tag.id + '">' + escapeHtml(tagOptionLabel(tag)) + '</option>').join('');
  document.querySelector('#tag-edit-parent').innerHTML = '<option value="">無（頂級分類）</option>' + managementOptions;
  if (selectedTagId && tags.some((tag) => tag.id === selectedTagId)) editSelect.value = String(selectedTagId);
  fillTagEditForm();
}

function setupTagPickers() {
  document.querySelectorAll('[data-tag-picker]').forEach((picker) => {
    const input = picker.querySelector('.tag-picker-input');
    input.addEventListener('focus', () => renderTagSuggestions(picker));
    input.addEventListener('input', () => {
      input.setCustomValidity('');
      renderTagSuggestions(picker);
    });
    input.addEventListener('keydown', (event) => {
      if (!['Enter', ';', '；'].includes(event.key)) return;
      event.preventDefault();
      if (commitTagPickerInput(picker)) picker.querySelector('.tag-picker-suggestions').hidden = true;
    });
    picker.addEventListener('click', (event) => {
      const suggestion = event.target.closest('[data-pick-tag-id]');
      if (suggestion) {
        const state = tagPickerValues(picker);
        const id = Number(suggestion.dataset.pickTagId);
        if (!state.ids.includes(id)) state.ids.push(id);
        input.setCustomValidity('');
        setTagPickerValues(picker, state.ids, state.names);
        input.focus();
        renderTagSuggestions(picker);
        return;
      }
      const removeId = event.target.closest('[data-remove-tag-id]');
      if (removeId) {
        const state = tagPickerValues(picker);
        setTagPickerValues(picker, state.ids.filter((id) => id !== Number(removeId.dataset.removeTagId)), state.names);
        return;
      }
      const removeName = event.target.closest('[data-remove-tag-name]');
      if (removeName) {
        const state = tagPickerValues(picker);
        state.names.splice(Number(removeName.dataset.removeTagName), 1);
        setTagPickerValues(picker, state.ids, state.names);
      }
    });
  });
  document.addEventListener('click', (event) => {
    document.querySelectorAll('[data-tag-picker]').forEach((picker) => {
      if (!picker.contains(event.target)) picker.querySelector('.tag-picker-suggestions').hidden = true;
    });
  });
}

function fillTagEditForm() {
  const id = Number(document.querySelector('#tag-edit-id').value);
  const tag = tags.find((item) => item.id === id);
  if (!tag) return;
  document.querySelector('#tag-edit-name').value = tag.name;
  document.querySelector('#tag-edit-parent').value = tag.parent_id ?? '';
}

function renderPublisherControls() {
  document.querySelector('#publisher-existing-names').innerHTML = publisherNames
    .map((name) => `<label class="publisher-name-option">
      <input type="checkbox" value="${escapeHtml(name)}">
      <span>${escapeHtml(name)}</span>
    </label>`).join('') || '<span class="tag-empty">尚無可歸併的出版社名稱</span>';
  document.querySelector('#publisher-suggestions').innerHTML = publishers.flatMap((publisher) =>
    publisher.aliases.map((alias) => `<option value="${escapeHtml(alias)}">${escapeHtml(publisher.canonical_name)}</option>`)
  ).join('');
  document.querySelector('#publisher-list').innerHTML = publishers.length ? publishers.map((publisher) => `
    <div class="publisher-row"><strong>${escapeHtml(publisher.canonical_name)}</strong>
      <span>${publisher.aliases.map((alias) => `<span class="tag-chip">${escapeHtml(alias)}</span>`).join('')}</span>
      <button class="danger compact" type="button" data-delete-publisher="${publisher.id}">刪除正規型</button>
    </div>`).join('') : '<div class="empty">尚未錄入出版社。</div>';
}

function tagChips(items) {
  return items?.length ? '<span class="tag-chips">' + items.map((tag) => '<span class="tag-chip">' + escapeHtml(tag.name) + '</span>').join('') + '</span>' : '';
}

function groupAnchor(index) {
  return 'collection-group-' + (index + 1);
}

function editionTopDisplay(entry) {
  const related = entry.related_works;
  const fallbackTitle = related.length === 1
    ? related[0].title
    : related.map((work) => work.title).join(' · ');
  const fallbackSubtitle = related.length === 1 ? related[0].subtitle : '';
  return {
    title: entry.edition.title || entry.edition.translated_title || fallbackTitle || '版本資料',
    subtitle: entry.edition.subtitle
      || entry.edition.translated_subtitle
      || fallbackSubtitle
      || ''
  };
}

function buildEditionEntries(records) {
  const byId = new Map();
  for (const record of records) {
    const editionId = Number(record.edition_id || record.edition?.id || 0);
    const key = editionId || JSON.stringify([
      record.edition.identifier, record.edition.title, record.edition.publisher,
      record.edition.publication_year, record.edition.version
    ]);
    if (!byId.has(key)) {
      byId.set(key, {
        kind: 'edition',
        id: editionId,
        edition: record.edition,
        copies: [],
        copyIds: new Set()
      });
    }
    const entry = byId.get(key);
    if (!entry.copyIds.has(record.id)) {
      entry.copyIds.add(record.id);
      entry.copies.push({
        id: record.id,
        volume_number: record.copy.volume_number,
        volume_title: record.copy.volume_title,
        location: record.copy.location
      });
    }
  }
  return [...byId.values()].map((entry) => {
    const relations = editionRelations(entry.edition);
    const relatedWorks = relations.map((relation) =>
      workOptions.find((work) => work.id === relation.work_id)
    ).filter(Boolean);
    const tagsById = new Map();
    for (const work of relatedWorks) {
      for (const tag of work.tags || []) tagsById.set(tag.id, tag);
    }
    const scripts = entry.edition.edition_scripts
      ? splitTerms(entry.edition.edition_scripts)
      : [...new Set(relatedWorks.flatMap((work) => splitTerms(work.scripts)))];
    const display = editionTopDisplay({...entry, related_works: relatedWorks});
    return {
      ...entry,
      relations,
      related_works: relatedWorks,
      title: display.title,
      subtitle: display.subtitle,
      authors: [...new Set(relatedWorks.map((work) => work.authors).filter(Boolean))].join('; '),
      tags: [...tagsById.values()],
      effective_scripts: scripts,
      publishers: [entry.edition.publisher_canonical || entry.edition.publisher].filter(Boolean),
      locations: [...new Set(entry.copies.map((copy) => copy.location).filter(Boolean))],
      years: entry.edition.publication_year ? [entry.edition.publication_year] : [],
      copy_count: entry.copies.length
    };
  }).sort((left, right) => left.title.localeCompare(right.title, 'zh-Hant', {numeric: true}));
}

function smartTopEntries() {
  const collapsedEditions = editionEntries.filter((entry) =>
    entry.relations.length > 1
      && entry.relations.every((relation) => relation.relation_type === 'contained')
  );
  const collapsedIds = new Set(collapsedEditions.map((entry) => entry.id));
  smartWorkExclusions = new Map();
  const workEntries = [];
  for (const work of works) {
    const linked = editionEntries.filter((entry) =>
      entry.relations.some((relation) => relation.work_id === work.id)
    );
    const excluded = linked.filter((entry) => collapsedIds.has(entry.id));
    const remaining = linked.filter((entry) => !collapsedIds.has(entry.id));
    if (excluded.length) {
      smartWorkExclusions.set(work.id, new Set(excluded.map((entry) => entry.id)));
    }
    if (!remaining.length && linked.length) continue;
    const copyIds = new Set(remaining.flatMap((entry) => entry.copies.map((copy) => copy.id)));
    workEntries.push({
      ...work,
      kind: 'work',
      edition_count: remaining.length || work.edition_count,
      copy_count: remaining.length ? copyIds.size : work.copy_count
    });
  }
  return [...workEntries, ...collapsedEditions]
    .sort((left, right) => left.title.localeCompare(right.title, 'zh-Hant', {numeric: true}));
}

function topEntries() {
  if (topModeSelect.value === 'edition') {
    smartWorkExclusions = new Map();
    return editionEntries;
  }
  if (topModeSelect.value === 'work') {
    smartWorkExclusions = new Map();
    return works.map((work) => ({...work, kind: 'work'}));
  }
  return smartTopEntries();
}

function entryGroupingValues(entry, dimension) {
  if (dimension === 'scripts') {
    if (topModeSelect.value === 'work' && entry.kind === 'work') {
      return splitTerms(entry.scripts);
    }
    return entry.effective_scripts ?? [];
  }
  if (dimension === 'tags') return (entry.tags || []).map((tag) => tag.name);
  if (dimension === 'publishers') return entry.publishers || [];
  if (dimension === 'locations') return entry.locations || [];
  if (dimension === 'years') return (entry.years || []).map(String);
  return [];
}

function renderWorks(query) {
  const dimension = viewSelect.value;
  const items = topEntries();
  collectionLayout.classList.toggle('has-index', dimension !== 'all' && items.length > 0);
  const modeName = topModeSelect.value === 'smart'
    ? '智能條目' : (topModeSelect.value === 'edition' ? 'Edition' : 'Work');
  count.textContent = query
    ? items.length + ' 項' + modeName + '搜尋結果'
    : '共 ' + items.length + ' 項' + modeName + ' · ' + books.length + ' 冊實物書';
  if (!items.length) {
    groupIndex.hidden = true;
    list.innerHTML = query ? '<div class="empty"><strong>沒有找到相符藏書</strong>試試較短的關鍵詞，或搜尋其他字段。</div>' : '<div class="empty"><strong>書架還是空的</strong>按右上角「新增藏書」，記下你的第一冊書。</div>';
    return;
  }
  if (dimension === 'all') {
    groupIndex.hidden = true;
    list.innerHTML = renderTopRows(items);
    return;
  }
  const groups = new Map();
  for (const entry of items) {
    let values = entryGroupingValues(entry, dimension);
    if (!values.length) values = ['未記錄'];
    for (const value of new Set(values)) {
      if (!groups.has(value)) groups.set(value, []);
      groups.get(value).push(entry);
    }
  }
  const entries = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b, 'zh-Hant', {numeric: true}));
  groupIndex.hidden = false;
  groupIndex.innerHTML = entries.map(([label], index) => '<a href="#' + groupAnchor(index) + '">' + escapeHtml(label) + '</a>').join('');
  list.innerHTML = entries.map(([label, groupedItems], index) =>
    '<section class="view-group" id="' + groupAnchor(index) + '"><h3>'
      + escapeHtml(label) + '<small>' + groupedItems.length + ' 項</small></h3>'
      + renderTopRows(groupedItems) + '</section>'
  ).join('');
}

function renderTopRows(items) {
  return items.map((entry) =>
    entry.kind === 'edition' ? renderEditionTopRow(entry) : renderWorkRow(entry)
  ).join('');
}

function renderWorkRow(work) {
  return `
    <button class="work-row" type="button" data-work-id="${work.id}">
      <span class="work-title"><strong>${escapeHtml(work.title)}</strong>${work.subtitle ? `<small>${escapeHtml(work.subtitle)}</small>` : ''}${tagChips(work.tags)}</span>
      <span class="cell"><span class="cell-label">作者或相關責任人</span>${shown(work.authors)}</span>
      <span class="cell stat"><b>${work.edition_count}</b><small>版本</small></span>
      <span class="cell stat"><b>${work.copy_count}</b><small>實物冊</small></span>
      <span class="arrow">›</span>
    </button>`;
}

function editionStructureLabel(entry) {
  const volumes = entry.relations.filter((relation) => relation.relation_type === 'volume').length;
  const contained = entry.relations.filter((relation) => relation.relation_type === 'contained').length;
  if (volumes && !contained) return volumes + ' 分冊';
  if (contained > 1 && !volumes) return '內含 ' + contained + ' 部';
  if (volumes || contained > 1) return volumes + ' 分冊 · 內含 ' + contained + ' 部';
  return '單一作品';
}

function renderEditionTopRow(entry) {
  const relatedTitles = entry.related_works.map((work) => work.title).join(' · ');
  return `
    <button class="work-row edition-top-row" type="button" data-edition-top-id="${entry.id}">
      <span class="work-title"><small class="top-kind">EDITION</small><strong>${escapeHtml(entry.title)}</strong>${entry.subtitle ? `<small>${escapeHtml(entry.subtitle)}</small>` : ''}${tagChips(entry.tags)}</span>
      <span class="cell"><span class="cell-label">關聯作品</span>${shown(relatedTitles)}</span>
      <span class="cell stat structure-stat"><b>${escapeHtml(editionStructureLabel(entry))}</b><small>結構</small></span>
      <span class="cell stat"><b>${entry.copy_count}</b><small>實物冊</small></span>
      <span class="arrow">›</span>
    </button>`;
}

function splitTerms(value) {
  return String(value ?? '').replace(/[；、，]/g, ';')
    .split(';').map((item) => item.trim()).filter(Boolean);
}

function createRepeatableRow(container, value = '') {
  const row = document.createElement('span');
  row.className = 'repeatable-row';
  const input = document.createElement('input');
  input.name = container.dataset.repeatableName;
  input.maxLength = Number(container.dataset.maxLength);
  input.value = value;
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'repeatable-remove';
  remove.textContent = '−';
  remove.setAttribute('aria-label', '移除此項');
  remove.addEventListener('click', () => {
    if (container.children.length > 1) row.remove();
    else input.value = '';
  });
  row.append(input, remove);
  container.appendChild(row);
}

function enhanceRepeatable(root, name, addLabel) {
  const original = Array.from(root.querySelectorAll('input')).find((input) => input.name === name);
  if (!original) return;
  const container = document.createElement('span');
  container.className = 'repeatable-inputs';
  container.dataset.repeatableName = name;
  container.dataset.maxLength = original.maxLength;
  original.parentElement.insertBefore(container, original);
  original.remove();
  createRepeatableRow(container);
  const add = document.createElement('button');
  add.type = 'button';
  add.className = 'repeatable-add';
  add.textContent = '＋ ' + addLabel;
  add.addEventListener('click', () => createRepeatableRow(container));
  container.after(add);
}

function repeatableContainer(root, name) {
  return Array.from(root.querySelectorAll('[data-repeatable-name]'))
    .find((item) => item.dataset.repeatableName === name);
}

function setRepeatable(root, name, value) {
  const container = repeatableContainer(root, name);
  if (!container) return;
  container.replaceChildren();
  const parts = splitTerms(value);
  for (const part of parts.length ? parts : ['']) createRepeatableRow(container, part);
}

function repeatableValue(root, name, normalizeVersion = false) {
  const container = repeatableContainer(root, name);
  const parts = Array.from(container?.querySelectorAll('input') ?? [])
    .map((input) => input.value.trim()).filter(Boolean)
    .map((value) => normalizeVersion && /^\d+$/.test(value) ? `第${value}版` : value);
  return parts.join('; ');
}

function splitPairedTerms(value) {
  return String(value ?? '').split(';').map((item) => item.trim());
}

function createTitlePair(editor, title = '', subtitle = '') {
  const row = document.createElement('div');
  row.className = 'paired-title-row';
  const titleLabel = document.createElement('label');
  titleLabel.textContent = '其他標題';
  const titleInput = document.createElement('input');
  titleInput.name = editor.dataset.titleName;
  titleInput.maxLength = 500;
  titleInput.value = title;
  titleLabel.appendChild(titleInput);
  const subtitleLabel = document.createElement('label');
  subtitleLabel.textContent = '其他副標題';
  const subtitleInput = document.createElement('input');
  subtitleInput.name = editor.dataset.subtitleName;
  subtitleInput.maxLength = 500;
  subtitleInput.value = subtitle;
  subtitleLabel.appendChild(subtitleInput);
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'repeatable-remove';
  remove.textContent = '−';
  remove.setAttribute('aria-label', '移除此組其他標題');
  remove.addEventListener('click', () => {
    const rows = editor.querySelector('.paired-title-rows');
    if (rows.children.length > 1) row.remove();
    else {
      titleInput.value = '';
      subtitleInput.value = '';
    }
  });
  row.append(titleLabel, subtitleLabel, remove);
  editor.querySelector('.paired-title-rows').appendChild(row);
}

function setTitlePairs(editor, titles = '', subtitles = '') {
  const titleParts = splitPairedTerms(titles);
  const subtitleParts = splitPairedTerms(subtitles);
  const size = Math.max(titleParts.length, subtitleParts.length, 1);
  const rows = editor.querySelector('.paired-title-rows');
  rows.replaceChildren();
  for (let index = 0; index < size; index += 1) {
    createTitlePair(editor, titleParts[index] ?? '', subtitleParts[index] ?? '');
  }
}

function titlePairValues(editor) {
  const pairs = Array.from(editor.querySelectorAll('.paired-title-row')).map((row) => ({
    title: row.querySelector(`[name="${editor.dataset.titleName}"]`).value.trim(),
    subtitle: row.querySelector(`[name="${editor.dataset.subtitleName}"]`).value.trim()
  }));
  while (pairs.length > 1 && !pairs.at(-1).title && !pairs.at(-1).subtitle) pairs.pop();
  return {
    other_title: pairs.map((pair) => pair.title).join('; '),
    other_subtitle: pairs.map((pair) => pair.subtitle).join('; ')
  };
}

function titlePairsText(titles, subtitles) {
  const titleParts = splitPairedTerms(titles);
  const subtitleParts = splitPairedTerms(subtitles);
  const size = Math.max(titleParts.length, subtitleParts.length);
  return Array.from({length: size}, (_, index) => {
    const title = titleParts[index] || '';
    const subtitle = subtitleParts[index] || '';
    return [title, subtitle].filter(Boolean).join('：');
  }).filter(Boolean).join('\n');
}

document.querySelectorAll('[data-paired-titles]').forEach((editor) => {
  setTitlePairs(editor);
  editor.querySelector('[data-add-title-pair]')
    .addEventListener('click', () => createTitlePair(editor));
});

function pairedTitleItems(titles, subtitles) {
  const titleParts = splitPairedTerms(titles);
  const subtitleParts = splitPairedTerms(subtitles);
  const size = Math.max(titleParts.length, subtitleParts.length);
  return Array.from({length: size}, (_, index) => ({
    title: titleParts[index] || '',
    subtitle: subtitleParts[index] || ''
  })).filter((pair) => pair.title || pair.subtitle);
}

function editionDisplayData(edition) {
  const work = activeWork?.work;
  return {
    title: edition.title || edition.translated_title || work?.title || '版本資料',
    subtitle: edition.subtitle
      || edition.translated_subtitle
      || work?.subtitle
      || ''
  };
}

function hasVisibleEditionDetails(edition) {
  const fields = [
    'title', 'subtitle', 'identifier', 'translator',
    'other_title', 'other_subtitle',
    'translated_title', 'translated_subtitle',
    'edition_scripts', 'version', 'series',
    'publisher', 'publisher_canonical', 'publication_year'
  ];
  return fields.some((field) =>
    edition[field] !== null
      && edition[field] !== undefined
      && String(edition[field]).trim() !== ''
  ) || editionRelations(edition).length > 1;
}

function effectiveEditionScripts(edition) {
  return edition.edition_scripts || activeWork?.work.scripts || '';
}

function editionRelations(edition) {
  if (Array.isArray(edition.work_relations) && edition.work_relations.length) {
    return edition.work_relations.map((relation) => ({
      work_id: Number(relation.work_id),
      relation_type: relation.relation_type === 'volume' ? 'volume' : 'contained',
      volume_number: relation.relation_type === 'volume' ? (relation.volume_number || '') : ''
    }));
  }
  return (edition.work_ids || []).map((workId) => ({
    work_id: Number(workId), relation_type: 'contained', volume_number: ''
  }));
}

function relationVolumeDisplay(value) {
  const text = String(value || '').trim();
  return /^\d+(?:\.\d+)*$/.test(text) ? ('第 ' + text + ' 冊') : text;
}

function editionHoldingLabel(group) {
  const relations = editionRelations(group.edition);
  const volumeCount = relations.filter((relation) => relation.relation_type === 'volume').length;
  const containedCount = relations.filter((relation) => relation.relation_type === 'contained').length;
  const copyCount = group.copies.length;
  if (volumeCount && !containedCount) return volumeCount + ' 分冊 · ' + copyCount + ' 實物冊';
  if (containedCount > 1 && !volumeCount) return copyCount + ' 冊 · 內含 ' + containedCount + ' 部';
  if (volumeCount || containedCount > 1) {
    return copyCount + ' 冊'
      + (volumeCount ? ' · ' + volumeCount + ' 分冊作品' : '')
      + (containedCount ? ' · 內含 ' + containedCount + ' 部' : '');
  }
  return copyCount + ' 冊';
}

function editionHeader(group, options = {}) {
  const edition = group.edition;
  const display = options.display || editionDisplayData(edition);
  const publisher = publisherDisplay(edition);
  const publication = [publisher === '—' ? '' : publisher, edition.publication_year || ''].filter(Boolean).join(' · ');
  const scripts = splitTerms(effectiveEditionScripts(edition)).join(' · ');
  const versions = splitTerms(edition.version);
  const identifiers = splitTerms(edition.identifier);
  return '<span class="edition-summary">'
    + '<span class="edition-summary-main"><span class="edition-title-line"><strong>' + escapeHtml(display.title) + '</strong>'
    + (scripts ? '<span class="edition-script">[' + escapeHtml(scripts) + ']</span>' : '') + '</span>'
    + (display.subtitle ? '<small class="edition-subtitle">' + escapeHtml(display.subtitle) + '</small>' : '')
    + (publication ? '<small class="edition-publication">' + publication + '</small>' : '') + '</span>'
    + (versions.length ? '<span class="edition-summary-versions">' + versions.map((value) => '<span>' + escapeHtml(value) + '</span>').join('') + '</span>' : '<span class="edition-summary-versions"></span>')
    + '<span class="edition-count">' + editionHoldingLabel(group) + '</span>'
    + (options.disclosure ? '<span class="disclosure">⌄</span>' : '<span class="edition-summary-spacer"></span>')
    + (identifiers.length ? '<span class="edition-summary-identifiers">' + identifiers.map((value) => '<span>' + escapeHtml(value) + '</span>').join('') + '</span>' : '')
    + '</span>';
}

function publisherDisplay(edition) {
  if (edition.publisher && edition.publisher_canonical && edition.publisher !== edition.publisher_canonical) {
    return `${escapeHtml(edition.publisher)}（${escapeHtml(edition.publisher_canonical)}）`;
  }
  return shown(edition.publisher_canonical || edition.publisher);
}

function naturalVolumeCompare(left, right) {
  const numeric = (value) => /^\d+(?:\.\d+)*$/.test(value) ? value.split('.').map(Number) : null;
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

function groupedVolumes(group) {
  const volumes = new Map();
  for (const copy of group.copies) {
    const volumeNumber = copy.volume_number || '';
    const volumeTitle = copy.volume_title || '';
    const key = JSON.stringify([volumeNumber, volumeTitle]);
    if (!volumes.has(key)) volumes.set(key, {
      volume_number: volumeNumber, volume_title: volumeTitle, copies: []
    });
    volumes.get(key).copies.push(copy);
  }
  return [...volumes.values()].sort((left, right) =>
    naturalVolumeCompare(left.volume_number, right.volume_number)
      || left.volume_title.localeCompare(right.volume_title, 'zh-Hant', {numeric: true})
  );
}

function volumeName(volume, fallback = '未標卷冊') {
  const parts = [volume.volume_number, volume.volume_title].filter(Boolean);
  return parts.length ? parts.map(escapeHtml).join(' · ') : fallback;
}

function copyRows(copies) {
  return copies.map((copy) => `
    <button class="copy-row" type="button" data-copy-id="${copy.id}">
      <span><small>實物冊</small><strong>#${copy.id}</strong></span>
      <span><small>藏書位置</small>${shown(copy.location)}</span><span class="arrow">›</span>
    </button>`).join('');
}

function renderVolumeContent(group) {
  const volumes = groupedVolumes(group);
  if (volumes.length === 1) {
    const volume = volumes[0];
    const copies = volume.copies;
    const hasVolume = volume.volume_number || volume.volume_title;
    if (!hasVolume && copies.length === 1) {
      const copy = copies[0];
      return `<button class="location-single" type="button" data-copy-id="${copy.id}">
        <span><small>藏書位置</small>${shown(copy.location)}</span><span class="arrow">›</span>
      </button>`;
    }
    if (!hasVolume) return `<div class="copy-list">${copyRows(copies)}</div>`;
    const label = volumeName(volume);
    if (copies.length === 1) {
      const copy = copies[0];
      return `<button class="volume-single merged-volume" type="button" data-copy-id="${copy.id}">
        <span><small>卷冊</small><strong>${label}</strong></span>
        <span><small>藏書位置</small>${shown(copy.location)}</span><span class="arrow">›</span>
      </button>`;
    }
    return `<div class="single-volume-group">
      <div class="single-volume-label"><span><small>卷冊</small><strong>${label}</strong></span><span>${copies.length} 冊重複實物冊</span></div>
      <div class="copy-list">${copyRows(copies)}</div>
    </div>`;
  }
  return volumes.map((volume) => {
    const copies = volume.copies;
    const label = volumeName(volume);
    if (copies.length === 1) {
      const copy = copies[0];
      return `<button class="volume-single" type="button" data-copy-id="${copy.id}">
        <span><small>卷冊</small><strong>${label}</strong></span>
        <span><small>藏書位置</small>${shown(copy.location)}</span><span class="arrow">›</span>
      </button>`;
    }
    return `<details class="volume-duplicates">
      <summary><span><small>卷冊</small><strong>${label}</strong></span><span>${copies.length} 冊重複實物冊</span><span class="disclosure">⌄</span></summary>
      <div class="copy-list">${copyRows(copies)}</div>
    </details>`;
  }).join('');
}

function renderPairedTitleDetail(label, pairs) {
  if (!pairs.length) return '';
  return '<div class="edition-detail-item title-pair-detail"><small>' + label + '</small>'
    + '<div class="edition-title-pairs">' + pairs.map((pair) =>
      '<div class="edition-title-pair">' + (pair.title ? '<strong>' + escapeHtml(pair.title) + '</strong>' : '')
      + (pair.subtitle ? '<span>' + escapeHtml(pair.subtitle) + '</span>' : '') + '</div>'
    ).join('') + '</div></div>';
}

function renderEditionBody(group) {
  const edition = group.edition;
  const details = [];
  const relations = editionRelations(edition).map((relation) => ({
    ...relation,
    work: workOptions.find((work) => work.id === relation.work_id)
  }));
  const relationGroups = [
    ['volume', '分冊作品'],
    ['contained', '本冊收錄']
  ];
  for (const [type, label] of relationGroups) {
    const members = relations.filter((relation) => relation.relation_type === type);
    if (!members.length || (relations.length === 1 && type === 'contained')) continue;
    details.push('<div class="edition-detail-item title-pair-detail"><small>' + label
      + (type === 'volume' ? '（' + members.length + ' 冊）' : '（' + members.length + ' 部）') + '</small>'
      + '<ol class="edition-related-works relation-' + type + '">' + members.map((relation) => {
        const work = relation.work;
        const title = work?.title || ('Work #' + relation.work_id);
        const author = work?.authors || '';
        return '<li>'
          + (type === 'volume' && relation.volume_number
            ? '<span class="relation-volume-number">' + escapeHtml(relationVolumeDisplay(relation.volume_number)) + '</span>' : '')
          + '<strong>' + escapeHtml(title) + '</strong>'
          + (author ? '<span>' + escapeHtml(author) + '</span>' : '') + '</li>';
      }).join('') + '</ol></div>');
  }
  if (edition.series) details.push('<div class="edition-detail-item"><small>系列</small><span>' + escapeHtml(edition.series) + '</span></div>');
  if (edition.translator) details.push('<div class="edition-detail-item"><small>譯者或相關責任人</small><span>' + escapeHtml(edition.translator) + '</span></div>');
  const otherTitles = renderPairedTitleDetail('其他題名', pairedTitleItems(edition.other_title, edition.other_subtitle));
  if (otherTitles) details.push(otherTitles);
  const translated = renderPairedTitleDetail('翻譯題名', pairedTitleItems(edition.translated_title, edition.translated_subtitle));
  if (translated) details.push(translated);
  const metadata = details.length ? '<div class="edition-detail-grid">' + details.join('') + '</div>' : '';
  return '<div class="edition-body">' + metadata
    + '<div class="volume-list">' + renderVolumeContent(group) + '</div>'
    + '<div class="edition-actions"><button class="text-button" type="button" data-edit-edition="' + group.id + '">修改此版本</button>'
    + '<button class="text-button" type="button" data-add-edition-copy="' + group.id + '">＋ 新增此版本的實物冊</button>'
    + '<button class="text-button danger-text" type="button" data-delete-edition="' + group.id + '">刪除此版本</button></div></div>';
}

function setWorkLevelActionsVisible(visible) {
  document.querySelector('#delete-work-button').hidden = !visible;
  document.querySelector('#edit-work-button').hidden = !visible;
  document.querySelector('#add-work-copy-button').hidden = !visible;
}

function renderWorkDetail(work) {
  setWorkLevelActionsVisible(true);
  document.querySelector('#detail-title').textContent = work.work.title;
  const author = work.work.authors ? '<p class="work-detail-author">' + escapeHtml(work.work.authors) + '</p>' : '';
  const subtitle = work.work.subtitle ? '<p class="work-detail-subtitle">' + escapeHtml(work.work.subtitle) + '</p>' : '';
  const scripts = work.work.scripts ? '<p class="work-detail-scripts"><small>文種</small>' + escapeHtml(work.work.scripts) + '</p>' : '';
  const assignedTags = tags.filter((tag) => work.work.tag_ids.includes(tag.id));
  let editions;
  if (work.editions.length === 1) {
    const group = work.editions[0];
    const volumes = groupedVolumes(group);
    const fullyCollapsed = !hasVisibleEditionDetails(group.edition)
      && volumes.length === 1 && !volumes[0].volume_number && !volumes[0].volume_title
      && volumes[0].copies.length === 1;
    if (fullyCollapsed) {
      const copy = volumes[0].copies[0];
      editions = '<section class="collapsed-book"><button class="collapsed-book-row" type="button" data-copy-id="' + copy.id + '">'
        + editionHeader(group) + '<span><small>藏書位置</small>' + shown(copy.location) + '</span><span class="arrow">›</span></button>'
        + '<div class="collapsed-actions"><button class="text-button" type="button" data-edit-edition="' + group.id + '">修改版本資料</button>'
        + '<button class="text-button" type="button" data-add-edition-copy="' + group.id + '">＋ 新增實物冊</button>'
        + '<button class="text-button danger-text" type="button" data-delete-edition="' + group.id + '">刪除此版本</button></div></section>';
    } else {
      editions = '<section class="merged-edition"><div class="merged-edition-header">' + editionHeader(group) + '</div>' + renderEditionBody(group) + '</section>';
    }
  } else {
    editions = work.editions.map((group) => '<details class="edition-card"><summary>' + editionHeader(group, {disclosure: true}) + '</summary>' + renderEditionBody(group) + '</details>').join('');
  }
  document.querySelector('#detail-content').innerHTML =
    '<section class="work-overview">' + subtitle + author + scripts + tagChips(assignedTags)
    + '<p>' + work.editions.length + ' 個版本 · ' + work.editions.reduce((sum, item) => sum + item.copies.length, 0) + ' 冊</p></section>'
    + '<section class="edition-list">' + (editions || '<div class="empty">此作品還沒有版本。</div>') + '</section>';
}

function renderEditionTopDetail() {
  const entry = editionEntries.find((item) => item.id === activeTopEditionId);
  const group = activeWork?.editions.find((item) => item.id === activeTopEditionId);
  if (!entry || !group) {
    detailDialog.close();
    return;
  }
  activeWork = {...activeWork, editions: [group]};
  setWorkLevelActionsVisible(false);
  const display = editionTopDisplay(entry);
  document.querySelector('#detail-title').textContent = display.title;
  document.querySelector('#detail-content').innerHTML =
    '<section class="edition-top-overview"><p class="eyebrow">EDITION VIEW</p>'
    + '<p>' + escapeHtml(editionStructureLabel(entry)) + ' · '
    + group.copies.length + ' 冊實物書</p></section>'
    + '<section class="edition-list"><section class="merged-edition">'
    + '<div class="merged-edition-header">' + editionHeader(group, {display}) + '</div>'
    + renderEditionBody(group) + '</section></section>';
}

function renderCurrentDetail() {
  if (activeTopEditionId !== null) renderEditionTopDetail();
  else renderWorkDetail(activeWork);
}

async function openWork(workId) {
  try {
    activeTopEditionId = null;
    activeWork = await request(`/api/works/${workId}`);
    const excluded = smartWorkExclusions.get(workId);
    if (excluded?.size) {
      activeWork = {
        ...activeWork,
        editions: activeWork.editions.filter((group) => !excluded.has(group.id))
      };
    }
    renderWorkDetail(activeWork);
    detailDialog.showModal();
  } catch (error) {
    flash(error.message, 'error');
  }
}

async function openEditionTop(editionId) {
  const entry = editionEntries.find((item) => item.id === editionId);
  const workId = entry?.relations[0]?.work_id;
  if (!entry || !workId) {
    flash('找不到此 Edition 的關聯 Work。', 'error');
    return;
  }
  try {
    activeTopEditionId = editionId;
    activeWork = await request(`/api/works/${workId}`);
    renderEditionTopDetail();
    detailDialog.showModal();
  } catch (error) {
    flash(error.message, 'error');
  }
}

function pairs(items, omitEmpty = false) {
  const visible = omitEmpty
    ? items.filter(([, value]) => value !== null && value !== undefined && value !== '')
    : items;
  return '<dl class="details">' + visible.map(([label, value, wide, lines]) =>
    '<div class="' + (wide ? 'wide' : '') + '"><dt>' + label + '</dt><dd>' + (lines ? shownLines(value) : shown(value)) + '</dd></div>'
  ).join('') + '</dl>';
}

async function openCopy(copyId) {
  try {
    activeBook = await request('/api/books/' + copyId);
    document.querySelector('#copy-detail-title').textContent = activeBook.work.title + ' · #' + activeBook.id;
    document.querySelector('#copy-detail-content').innerHTML =
      '<section class="detail-section"><h3>01 · 作品信息</h3>' + pairs([
        ['標題', activeBook.work.title, true], ['副標題', activeBook.work.subtitle, true],
        ['作者或相關責任人', activeBook.work.authors, true], ['文種', activeBook.work.scripts, true]
      ]) + '</section>'
      + '<section class="detail-section"><h3>02 · 版本信息</h3>' + pairs([
        ['版本題名', activeBook.edition.title, true],
        ['版本副標題', activeBook.edition.subtitle, true],
        ['版本', activeBook.edition.version], ['系列', activeBook.edition.series],
        ['出版社原始名稱', activeBook.edition.publisher], ['出版社實體', activeBook.edition.publisher_canonical],
        ['出版年份', activeBook.edition.publication_year],
        ['識別號', activeBook.edition.identifier, true, true],
        ['文種', activeBook.edition.edition_scripts || activeBook.work.scripts],
        ['其他標題', titlePairsText(activeBook.edition.other_title, activeBook.edition.other_subtitle), true],
        ['翻譯標題', activeBook.edition.translated_title, true],
        ['翻譯副標題', activeBook.edition.translated_subtitle, true],
        ['譯者或相關責任人', activeBook.edition.translator, true]
      ], true) + '</section>'
      + '<section class="detail-section"><h3>03 · 實物冊 #' + activeBook.id + '</h3>' + pairs([
        ['卷冊編號', activeBook.copy.volume_number],
        ['卷冊題名', activeBook.copy.volume_title, true],
        ['取得日期', activeBook.copy.acquisition_date],
        ['藏書位置', activeBook.copy.location], ['閱讀記錄', activeBook.copy.reading_record, true]
      ]) + '</section>';
    copyDialog.showModal();
  } catch (error) {
    flash(error.message, 'error');
  }
}

function setField(name, value) {
  const control = form.elements.namedItem(name);
  if (control) control.value = value ?? '';
}

function selectedValues(control) {
  return Array.from(control?.selectedOptions ?? []).map((option) => Number(option.value));
}

function batchVolumeData() {
  const customNumbers = splitTerms(form.elements.namedItem('batch.volume_numbers').value);
  if (customNumbers.length) {
    const rawTitles = form.elements.namedItem('batch.volume_titles').value
      .replace(/[；、，]/g, ';').split(';').map((value) => value.trim());
    return {
      volume_numbers: customNumbers,
      volume_titles: customNumbers.map((_, index) => rawTitles[index] || '')
    };
  }
  const start = Number(form.elements.namedItem('batch.start').value);
  const end = Number(form.elements.namedItem('batch.end').value);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start) {
    throw new Error('批量新增請填寫有效的起始與結束卷冊，或提供自訂卷冊編號。');
  }
  if (end - start + 1 > 500) throw new Error('一次最多批量新增 500 冊。');
  return {
    volume_numbers: Array.from({length: end - start + 1}, (_, index) => String(start + index)),
    volume_titles: []
  };
}

function updateCopyMode() {
  const batch = form.elements.namedItem('copy-mode').value === 'batch';
  form.querySelector('[data-single-volume]').hidden = batch;
  form.querySelector('[data-batch-fields]').hidden = !batch;
}

enhanceRepeatable(form, 'edition.identifier', '添加識別號');
enhanceRepeatable(form, 'edition.version', '添加版本');
enhanceRepeatable(document.querySelector('#edition-edit-form'), 'identifier', '添加識別號');
enhanceRepeatable(document.querySelector('#edition-edit-form'), 'version', '添加版本');

function workOptionMarkup(selectedId) {
  return workOptions.map((work) =>
    '<option value="' + work.id + '" ' + (work.id === selectedId ? 'selected' : '') + '>'
      + escapeHtml(work.title + (work.authors ? ' — ' + work.authors : '')) + '</option>'
  ).join('');
}

function updateEditionWorkWarning(editor) {
  const containedCount = [...editor.querySelectorAll('.edition-work-link-row')]
    .filter((row) => row.querySelector('[data-relation-type]').value === 'contained').length;
  editor.querySelector('.edition-work-warning').hidden = containedCount < 2;
}

function updateEditionRelationRow(row, clear = false) {
  const type = row.querySelector('[data-relation-type]').value;
  const input = row.querySelector('[data-relation-volume]');
  const isVolume = type === 'volume';
  input.hidden = !isVolume;
  input.disabled = !isVolume;
  if (!isVolume && clear) input.value = '';
}

function createEditionWorkRow(editor, relation, fixed = false) {
  const normalized = typeof relation === 'object'
    ? relation
    : {work_id: Number(relation), relation_type: 'contained', volume_number: ''};
  const workId = Number(normalized.work_id);
  const relationType = normalized.relation_type === 'volume' ? 'volume' : 'contained';
  const row = document.createElement('div');
  row.className = 'edition-work-link-row';
  row.dataset.fixed = String(fixed);
  row.dataset.implicitWork = String(workId === 0);
  const workOptionsMarkup = workId === 0
    ? '<option value="0">目前正在新增的 Work</option>'
    : workOptionMarkup(workId);
  row.innerHTML = '<select class="edition-work-select" aria-label="關聯作品" '
    + (workId === 0 ? 'disabled' : '') + '>' + workOptionsMarkup + '</select>'
    + '<select class="edition-relation-type" data-relation-type aria-label="關聯類型">'
    + '<option value="contained"' + (relationType === 'contained' ? ' selected' : '') + '>同冊收錄</option>'
    + '<option value="volume"' + (relationType === 'volume' ? ' selected' : '') + '>分冊</option></select>'
    + '<input class="edition-relation-volume" data-relation-volume aria-label="分冊號" placeholder="冊號" value="'
    + escapeHtml(normalized.volume_number || '') + '">'
    + '<button type="button" data-work-up aria-label="上移">↑</button>'
    + '<button type="button" data-work-down aria-label="下移">↓</button>'
    + '<button type="button" data-work-remove aria-label="移除" ' + (fixed ? 'disabled title="目前作品不能從此處移除"' : '') + '>×</button>';
  editor.querySelector('.edition-work-link-rows').append(row);
  updateEditionRelationRow(row);
}

function setEditionWorkLinks(editor, relations = [], fixedPrimaryId = null) {
  const rows = editor.querySelector('.edition-work-link-rows');
  rows.innerHTML = '';
  editor.querySelectorAll('[data-work-relation-search] input').forEach((input) => { input.value = ''; });
  const candidateResults = editor.querySelector('[data-work-results]');
  if (candidateResults) {
    candidateResults.hidden = true;
    candidateResults.replaceChildren();
  }
  editor.dataset.implicitPrimary = 'false';
  editor.dataset.fixedPrimaryId = fixedPrimaryId ?? '';
  const normalized = [];
  const positions = new Map();
  for (const item of relations || []) {
    const relation = typeof item === 'object'
      ? {...item, work_id: Number(item.work_id)}
      : {work_id: Number(item), relation_type: 'contained', volume_number: ''};
    if (!relation.work_id) continue;
    if (positions.has(relation.work_id)) normalized[positions.get(relation.work_id)] = relation;
    else {
      positions.set(relation.work_id, normalized.length);
      normalized.push(relation);
    }
  }
  if (fixedPrimaryId !== null && !positions.has(Number(fixedPrimaryId))) {
    normalized.unshift({
      work_id: Number(fixedPrimaryId), relation_type: 'contained', volume_number: ''
    });
  }
  if (fixedPrimaryId === null && !normalized.length) {
    normalized.push({work_id: 0, relation_type: 'contained', volume_number: ''});
  }
  normalized.forEach((relation) =>
    createEditionWorkRow(editor, relation, relation.work_id === Number(fixedPrimaryId))
  );
  updateEditionWorkWarning(editor);
}

function editionWorkRelations(editor) {
  const relations = [...editor.querySelectorAll('.edition-work-link-row')].map((row) => {
    const relationType = row.querySelector('[data-relation-type]').value;
    return {
      work_id: Number(row.querySelector('.edition-work-select').value),
      relation_type: relationType,
      volume_number: relationType === 'volume'
        ? row.querySelector('[data-relation-volume]').value.trim() : ''
    };
  }).filter((relation, index) =>
    relation.work_id || [...editor.querySelectorAll('.edition-work-link-row')][index].dataset.implicitWork === 'true'
  );
  const ids = relations.map((relation) => relation.work_id);
  if (new Set(ids).size !== ids.length) throw new Error('同一個 Work 不能重複關聯。');
  return relations;
}

function installWorkSearch(editor) {
  if (editor.querySelector('[data-work-relation-search]')) return;
  const search = document.createElement('div');
  search.className = 'relation-search';
  search.dataset.workRelationSearch = '';
  search.innerHTML =
    '<div class="relation-search-grid">'
    + '<input data-work-search-title placeholder="Work 題名">'
    + '<input data-work-search-subtitle placeholder="副題名">'
    + '<input data-work-search-authors placeholder="作者或相關責任人">'
    + '</div><div class="relation-search-results" data-work-results hidden></div>';
  editor.querySelector('.edition-work-link-rows').before(search);
  const button = editor.querySelector('[data-add-edition-work]');
  button.textContent = '搜尋／瀏覽已有 Work';
}

function renderWorkRelationCandidates(editor) {
  const text = (selector) => editor.querySelector(selector).value.trim().toLocaleLowerCase();
  const criteria = {
    title: text('[data-work-search-title]'),
    subtitle: text('[data-work-search-subtitle]'),
    authors: text('[data-work-search-authors]')
  };
  const used = new Set(
    [...editor.querySelectorAll('.edition-work-select')].map((select) => Number(select.value))
  );
  const matches = workOptions.filter((work) =>
    !used.has(work.id)
      && (!criteria.title || work.title.toLocaleLowerCase().includes(criteria.title))
      && (!criteria.subtitle || work.subtitle.toLocaleLowerCase().includes(criteria.subtitle))
      && (!criteria.authors || work.authors.toLocaleLowerCase().includes(criteria.authors))
  ).slice(0, 40);
  const results = editor.querySelector('[data-work-results]');
  results.hidden = false;
  results.innerHTML = matches.length ? matches.map((work) =>
    '<button type="button" class="relation-candidate" data-work-candidate="' + work.id + '">'
      + '<strong>' + escapeHtml(work.title) + '</strong>'
      + (work.subtitle ? '<span>' + escapeHtml(work.subtitle) + '</span>' : '')
      + (work.authors ? '<small>' + escapeHtml(work.authors) + '</small>' : '')
      + '</button>'
  ).join('') : '<p class="empty-candidates">沒有符合條件且尚未關聯的 Work。</p>';
}

function setupEditionWorkLinks() {
  document.querySelectorAll('[data-edition-work-links]').forEach((editor) => {
    installWorkSearch(editor);
    editor.addEventListener('change', (event) => {
      if (event.target.matches('[data-relation-type]')) {
        updateEditionRelationRow(event.target.closest('.edition-work-link-row'), true);
      }
    });
    editor.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && event.target.closest('[data-work-relation-search]')) {
        event.preventDefault();
        renderWorkRelationCandidates(editor);
      }
    });
    editor.addEventListener('click', (event) => {
      const candidateButton = event.target.closest('[data-work-candidate]');
      if (candidateButton) {
        createEditionWorkRow(editor, {
          work_id: Number(candidateButton.dataset.workCandidate),
          relation_type: 'contained',
          volume_number: ''
        });
        renderWorkRelationCandidates(editor);
        updateEditionWorkWarning(editor);
        return;
      }
      const add = event.target.closest('[data-add-edition-work]');
      if (add) {
        renderWorkRelationCandidates(editor);
        return;
      }
      const row = event.target.closest('.edition-work-link-row');
      if (!row) return;
      if (event.target.closest('[data-work-remove]') && row.dataset.fixed !== 'true') row.remove();
      if (event.target.closest('[data-work-up]') && row.previousElementSibling) row.before(row.previousElementSibling);
      if (event.target.closest('[data-work-down]') && row.nextElementSibling) row.after(row.nextElementSibling);
      updateEditionWorkWarning(editor);
    });
  });
}


function editionCandidateTitle(edition) {
  return edition.title
    || edition.translated_title
    || splitTerms(edition.identifier)[0]
    || ('Edition #' + edition.id);
}

function updateWorkEditionRelationRow(row, clear = false) {
  const isVolume = row.querySelector('[data-work-edition-type]').value === 'volume';
  const volume = row.querySelector('[data-work-edition-volume]');
  volume.hidden = !isVolume;
  volume.disabled = !isVolume;
  if (!isVolume && clear) volume.value = '';
}

function createWorkEditionRow(editor, relation) {
  const editionId = Number(relation.edition_id);
  if ([...editor.querySelectorAll('.work-edition-link-row')]
      .some((row) => Number(row.dataset.editionId) === editionId)) return;
  const edition = editionOptions.find((item) => item.id === editionId);
  if (!edition) return;
  const relationType = relation.relation_type === 'volume' ? 'volume' : 'contained';
  const row = document.createElement('div');
  row.className = 'work-edition-link-row';
  row.dataset.editionId = editionId;
  const publication = [
    edition.publisher_canonical || edition.publisher,
    edition.publication_year
  ].filter(Boolean).join(' · ');
  row.innerHTML =
    '<span class="work-edition-selected"><strong>' + escapeHtml(editionCandidateTitle(edition)) + '</strong>'
    + (edition.subtitle || edition.translated_subtitle
      ? '<span>' + escapeHtml(edition.subtitle || edition.translated_subtitle) + '</span>' : '')
    + (publication ? '<small>' + escapeHtml(publication) + '</small>' : '')
    + (edition.identifier ? '<small>' + shownLines(edition.identifier) + '</small>' : '')
    + '</span><select data-work-edition-type aria-label="關聯類型">'
    + '<option value="contained"' + (relationType === 'contained' ? ' selected' : '') + '>同冊收錄</option>'
    + '<option value="volume"' + (relationType === 'volume' ? ' selected' : '') + '>分冊</option></select>'
    + '<input data-work-edition-volume aria-label="分冊號" placeholder="冊號" value="'
    + escapeHtml(relation.volume_number || '') + '">'
    + '<button type="button" data-remove-work-edition aria-label="移除關聯">×</button>';
  editor.querySelector('.work-edition-link-rows').append(row);
  updateWorkEditionRelationRow(row);
}

function setWorkEditionLinks(editor, work = null) {
  editor.querySelector('.work-edition-link-rows').replaceChildren();
  editor.querySelectorAll('.relation-search-grid input').forEach((input) => { input.value = ''; });
  const results = editor.querySelector('[data-edition-results]');
  results.hidden = true;
  results.replaceChildren();
  if (!work) return;
  for (const group of work.editions) {
    const relation = editionRelations(group.edition)
      .find((item) => item.work_id === work.id);
    if (relation) createWorkEditionRow(editor, {
      edition_id: group.id,
      relation_type: relation.relation_type,
      volume_number: relation.volume_number
    });
  }
}

function renderEditionRelationCandidates(editor) {
  const value = (selector) => editor.querySelector(selector).value.trim().toLocaleLowerCase();
  const criteria = {
    title: value('[data-edition-search-title]'),
    subtitle: value('[data-edition-search-subtitle]'),
    identifier: value('[data-edition-search-identifier]'),
    publisher: value('[data-edition-search-publisher]'),
    year: value('[data-edition-search-year]')
  };
  const used = new Set(
    [...editor.querySelectorAll('.work-edition-link-row')]
      .map((row) => Number(row.dataset.editionId))
  );
  const matches = editionOptions.filter((edition) => {
    const title = [edition.title, edition.translated_title].join(' ').toLocaleLowerCase();
    const subtitle = [edition.subtitle, edition.translated_subtitle].join(' ').toLocaleLowerCase();
    const publisher = [edition.publisher, edition.publisher_canonical].join(' ').toLocaleLowerCase();
    return !used.has(edition.id)
      && (!criteria.title || title.includes(criteria.title))
      && (!criteria.subtitle || subtitle.includes(criteria.subtitle))
      && (!criteria.identifier || edition.identifier.toLocaleLowerCase().includes(criteria.identifier))
      && (!criteria.publisher || publisher.includes(criteria.publisher))
      && (!criteria.year || String(edition.publication_year || '').includes(criteria.year));
  }).slice(0, 40);
  const results = editor.querySelector('[data-edition-results]');
  results.hidden = false;
  results.innerHTML = matches.length ? matches.map((edition) => {
    const publication = [
      edition.publisher_canonical || edition.publisher,
      edition.publication_year
    ].filter(Boolean).join(' · ');
    return '<button type="button" class="relation-candidate" data-edition-candidate="' + edition.id + '">'
      + '<strong>' + escapeHtml(editionCandidateTitle(edition)) + '</strong>'
      + (edition.subtitle || edition.translated_subtitle
        ? '<span>' + escapeHtml(edition.subtitle || edition.translated_subtitle) + '</span>' : '')
      + (publication ? '<small>' + escapeHtml(publication) + '</small>' : '')
      + (edition.identifier ? '<small>' + escapeHtml(edition.identifier) + '</small>' : '')
      + '</button>';
  }).join('') : '<p class="empty-candidates">沒有符合條件且尚未關聯的 Edition。</p>';
}

function workEditionRelations(editor) {
  return [...editor.querySelectorAll('.work-edition-link-row')].map((row) => {
    const relationType = row.querySelector('[data-work-edition-type]').value;
    return {
      edition_id: Number(row.dataset.editionId),
      relation_type: relationType,
      volume_number: relationType === 'volume'
        ? row.querySelector('[data-work-edition-volume]').value.trim() : ''
    };
  });
}

function setupWorkEditionLinks() {
  const editor = document.querySelector('[data-work-edition-links]');
  editor.addEventListener('change', (event) => {
    if (event.target.matches('[data-work-edition-type]')) {
      updateWorkEditionRelationRow(event.target.closest('.work-edition-link-row'), true);
    }
  });
  editor.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && event.target.closest('.relation-search-grid')) {
      event.preventDefault();
      renderEditionRelationCandidates(editor);
    }
  });
  editor.addEventListener('click', (event) => {
    if (event.target.closest('[data-search-edition]')) {
      renderEditionRelationCandidates(editor);
      return;
    }
    const candidate = event.target.closest('[data-edition-candidate]');
    if (candidate) {
      createWorkEditionRow(editor, {
        edition_id: Number(candidate.dataset.editionCandidate),
        relation_type: 'contained',
        volume_number: ''
      });
      renderEditionRelationCandidates(editor);
      return;
    }
    const remove = event.target.closest('[data-remove-work-edition]');
    if (remove) remove.closest('.work-edition-link-row').remove();
  });
}

function openWorkEditor(work = null) {
  const editForm = document.querySelector('#work-edit-form');
  editForm.reset();
  editingWorkId = work?.id ?? null;
  document.querySelector('#work-form-mode').textContent = work ? '修改作品' : '新增作品';
  document.querySelector('#work-form-title').textContent = work ? '修改作品' : '建立 Work';
  document.querySelector('#work-save-button').textContent = work ? '保存作品' : '建立作品';
  for (const name of ['title', 'subtitle', 'authors', 'scripts']) {
    editForm.elements.namedItem(name).value = work?.work?.[name] ?? '';
  }
  setTagPickerValues(
    editForm.querySelector('[data-tag-picker]'),
    work?.work?.tag_ids ?? [],
    []
  );
  setWorkEditionLinks(editForm.querySelector('[data-work-edition-links]'), work);
  workEditDialog.showModal();
}


function openForm(book = null, presetWork = null, presetEdition = null, primaryWorkId = null) {
  form.reset();
  setTagPickerValues(form.querySelector('[data-tag-picker]'));
  form.elements.namedItem('copy-mode').value = 'single';
  document.querySelector('#copy-mode-controls').hidden = Boolean(book);
  updateCopyMode();
  setRepeatable(form, 'edition.identifier', '');
  setRepeatable(form, 'edition.version', '');
  setTitlePairs(form.querySelector('[data-paired-titles]'));
  setEditionWorkLinks(
    form.querySelector('[data-edition-work-links]'),
    book?.edition.work_relations ?? presetEdition?.work_relations ?? book?.edition.work_ids ?? presetEdition?.work_ids ?? [],
    book ? (book.edition.work_ids?.[0] ?? primaryWorkId) : primaryWorkId
  );
  document.querySelector('#copy-id').value = book?.id ?? '';
  document.querySelector('#form-mode').textContent = book ? '修改實物冊' : '新增實物冊';
  document.querySelector('#form-title').textContent = book ? '修改藏書' : '新增藏書';
  saveButton.textContent = book ? '保存修改' : '保存藏書';
  const sourceWork = book?.work ?? presetWork;
  const sourceEdition = book?.edition ?? presetEdition;
  if (sourceWork) {
    for (const [key, value] of Object.entries(sourceWork)) {
      if (key !== 'tag_ids' && key !== 'tag_names') setField(`work.${key}`, value);
    }
    setTagPickerValues(form.querySelector('[data-tag-picker]'), sourceWork.tag_ids ?? [], sourceWork.tag_names ?? []);
  }
  if (sourceEdition) {
    for (const [key, value] of Object.entries(sourceEdition)) {
      if (!['identifier', 'version', 'other_title', 'other_subtitle'].includes(key)) {
        setField(`edition.${key}`, value);
      }
    }
    setRepeatable(form, 'edition.identifier', sourceEdition.identifier);
    setRepeatable(form, 'edition.version', sourceEdition.version);
    setTitlePairs(
      form.querySelector('[data-paired-titles]'),
      sourceEdition.other_title,
      sourceEdition.other_subtitle
    );
  }
  if (book) {
    for (const [key, value] of Object.entries(book.copy)) setField(`copy.${key}`, value);
  }
  bookDialog.showModal();
}

function formPayload() {
  if (!commitTagPickerInput(form.querySelector('[data-tag-picker]'))) {
    throw new Error('請先從候選中選擇同名標籤。');
  }
  const get = (name) => form.elements.namedItem(name).value.trim();
  const year = get('edition.publication_year');
  const otherTitles = titlePairValues(form.querySelector('[data-paired-titles]'));
  return {
    work: {
      title: get('work.title'), subtitle: get('work.subtitle'),
      authors: get('work.authors'), scripts: get('work.scripts'),
      tag_ids: selectedValues(form.elements.namedItem('work.tag_ids')),
      tag_names: splitTerms(get('work.tags'))
    },
    edition: {
      title: get('edition.title'), subtitle: get('edition.subtitle'),
      work_relations: editionWorkRelations(form.querySelector('[data-edition-work-links]')),
      identifier: repeatableValue(form, 'edition.identifier'), translator: get('edition.translator'),
      other_title: otherTitles.other_title,
      other_subtitle: otherTitles.other_subtitle,
      translated_title: get('edition.translated_title'),
      translated_subtitle: get('edition.translated_subtitle'),
      edition_scripts: get('edition.edition_scripts'),
      version: repeatableValue(form, 'edition.version', true),
      series: get('edition.series'),
      publisher: get('edition.publisher'), publisher_id: null, publisher_canonical: '',
      publication_year: year ? Number(year) : null
    },
    copy: {
      volume_number: get('copy.volume_number'),
      volume_title: get('copy.volume_title'),
      acquisition_date: get('copy.acquisition_date') || null,
      location: get('copy.location'), reading_record: get('copy.reading_record')
    }
  };
}

searchForm.addEventListener('submit', (event) => {
  event.preventDefault(); loadWorks(searchInput.value);
});
document.querySelector('#add-button').addEventListener('click', () => openForm());
document.querySelector('#add-work-button').addEventListener('click', () => openWorkEditor());
document.querySelector('#tags-button').addEventListener('click', () => tagsDialog.showModal());
document.querySelector('#publishers-button').addEventListener('click', () => publishersDialog.showModal());
document.querySelector('#import-button').addEventListener('click', () => {
  csvFileInput.value = '';
  csvFileInput.click();
});
viewSelect.addEventListener('change', () => {
  localStorage.setItem('book-catalog-view', viewSelect.value);
  renderWorks(searchInput.value);
});
topModeSelect.addEventListener('change', () => {
  localStorage.setItem('book-catalog-top-mode', topModeSelect.value);
  renderWorks(searchInput.value);
});
form.elements.namedItem('copy-mode').forEach((radio) =>
  radio.addEventListener('change', updateCopyMode)
);
document.querySelector('.brand').addEventListener('click', (event) => {
  event.preventDefault(); searchInput.value = ''; loadWorks();
});
list.addEventListener('click', (event) => {
  const editionRow = event.target.closest('[data-edition-top-id]');
  if (editionRow) {
    openEditionTop(Number(editionRow.dataset.editionTopId));
    return;
  }
  const row = event.target.closest('[data-work-id]');
  if (row) openWork(Number(row.dataset.workId));
});
document.querySelector('#detail-content').addEventListener('click', async (event) => {
  const copyRow = event.target.closest('[data-copy-id]');
  if (copyRow) {
    openCopy(Number(copyRow.dataset.copyId));
    return;
  }
  const deleteEditionButton = event.target.closest('[data-delete-edition]');
  if (deleteEditionButton) {
    const group = activeWork.editions.find(
      (item) => item.id === Number(deleteEditionButton.dataset.deleteEdition)
    );
    if (!group || !window.confirm(`確定刪除此版本及其 ${group.copies.length} 冊實物冊嗎？`)) return;
    try {
      const result = await request(`/api/editions/${group.id}`, {method: 'DELETE'});
      if (activeTopEditionId !== null
          || result.work_deleted
          || result.deleted_work_ids?.includes(activeWork.id)) {
        detailDialog.close();
        activeWork = null;
        activeTopEditionId = null;
      } else {
        activeWork = await request(`/api/works/${activeWork.id}`);
        renderWorkDetail(activeWork);
      }
      await loadWorks(searchInput.value);
      flash('版本及其實物冊已刪除。');
    } catch (error) {
      flash(error.message, 'error');
    }
    return;
  }
  const addButton = event.target.closest('[data-add-edition-copy]');
  if (addButton) {
    const group = activeWork.editions.find((item) => item.id === Number(addButton.dataset.addEditionCopy));
    detailDialog.close();
    openForm(null, activeWork.work, group.edition, activeWork.id);
    return;
  }
  const editButton = event.target.closest('[data-edit-edition]');
  if (editButton) {
    activeEdition = activeWork.editions.find((item) => item.id === Number(editButton.dataset.editEdition));
    const editForm = document.querySelector('#edition-edit-form');
    for (const [key, value] of Object.entries(activeEdition.edition)) {
      if (!['identifier', 'version', 'other_title', 'other_subtitle'].includes(key)) {
        const control = editForm.elements.namedItem(key);
        if (control) control.value = value ?? '';
      }
    }
    setRepeatable(editForm, 'identifier', activeEdition.edition.identifier);
    setEditionWorkLinks(
      editForm.querySelector('[data-edition-work-links]'),
      activeEdition.edition.work_relations ?? activeEdition.edition.work_ids,
      activeWork.id
    );
    setRepeatable(editForm, 'version', activeEdition.edition.version);
    setTitlePairs(
      editForm.querySelector('[data-paired-titles]'),
      activeEdition.edition.other_title,
      activeEdition.edition.other_subtitle
    );
    editionEditDialog.showModal();
  }
});
document.querySelector('#add-work-copy-button').addEventListener('click', () => {
  detailDialog.close(); openForm(null, activeWork.work, null, activeWork.id);
});
document.querySelector('#delete-work-button').addEventListener('click', async () => {
  if (!activeWork || !window.confirm(`確定刪除作品「${activeWork.work.title}」嗎？僅關聯此作品的 Edition 會一併刪除；仍關聯其他 Work 的合刊 Edition 與實物冊會保留。`)) return;
  try {
    await request(`/api/works/${activeWork.id}`, {method: 'DELETE'});
    detailDialog.close();
    activeWork = null;
    await loadWorks(searchInput.value);
    flash('作品已刪除；仍有其他 Work 關聯的合刊 Edition 已保留。');
  } catch (error) {
    flash(error.message, 'error');
  }
});
document.querySelector('#edit-work-button').addEventListener('click', () => {
  openWorkEditor(activeWork);
});
document.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => bookDialog.close()));
document.querySelectorAll('[data-detail-close]').forEach((button) => button.addEventListener('click', () => detailDialog.close()));
document.querySelectorAll('[data-copy-close]').forEach((button) => button.addEventListener('click', () => copyDialog.close()));
document.querySelectorAll('[data-tags-close]').forEach((button) => button.addEventListener('click', () => tagsDialog.close()));
document.querySelectorAll('[data-publishers-close]').forEach((button) => button.addEventListener('click', () => publishersDialog.close()));
document.querySelectorAll('[data-import-close]').forEach((button) => button.addEventListener('click', () => importDialog.close()));
document.querySelectorAll('[data-work-edit-close]').forEach((button) => button.addEventListener('click', () => workEditDialog.close()));
document.querySelectorAll('[data-edition-edit-close]').forEach((button) => button.addEventListener('click', () => editionEditDialog.close()));
document.querySelectorAll('[data-copy-edit-close]').forEach((button) => button.addEventListener('click', () => copyEditDialog.close()));
document.querySelector('#tag-tree').addEventListener('click', async (event) => {
  const toggle = event.target.closest('[data-tag-toggle]');
  if (toggle) {
    const children = toggle.closest('.tag-tree-node').querySelector(':scope > .tag-tree-children');
    const collapsed = !children.hidden;
    children.hidden = collapsed;
    toggle.textContent = collapsed ? '▸' : '▾';
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.setAttribute('aria-label', collapsed ? '展開下級' : '收合下級');
    return;
  }
  const button = event.target.closest('[data-delete-tag]');
  if (!button) return;
  const tag = tags.find((item) => item.id === Number(button.dataset.deleteTag));
  if (!tag || !window.confirm(`確定刪除標籤「${tag.path}」及其所有下級標籤嗎？`)) return;
  try {
    const result = await request(`/api/tags/${tag.id}`, {method: 'DELETE'});
    selectedTagId = null;
    await loadTags(); await loadWorks(searchInput.value);
    flash(`已刪除 ${result.deleted_count} 個標籤。`);
  } catch (error) {
    flash(error.message, 'error');
  }
});
document.querySelector('#publisher-list').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-delete-publisher]');
  if (!button) return;
  const publisher = publishers.find((item) => item.id === Number(button.dataset.deletePublisher));
  if (!publisher || !window.confirm(`確定刪除出版社正規型「${publisher.canonical_name}」嗎？原始出版社名稱會保留。`)) return;
  try {
    await request(`/api/publishers/${publisher.id}`, {method: 'DELETE'});
    await loadPublishers(); await loadWorks(searchInput.value);
    flash('出版社正規型已刪除；出版物原始名稱仍保留。');
  } catch (error) {
    flash(error.message, 'error');
  }
});
document.querySelector('#tag-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = document.querySelector('#tag-name').value.trim();
  const parent = document.querySelector('#tag-parent').value;
  if (!name) return;
  try {
    await request('/api/tags', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, parent_id: parent ? Number(parent) : null})
    });
    document.querySelector('#tag-name').value = '';
    await loadTags();
  } catch (error) {
    flash(error.message, 'error');
  }
});
document.querySelector('#tag-edit-id').addEventListener('change', fillTagEditForm);
document.querySelector('#tag-edit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const tagId = Number(document.querySelector('#tag-edit-id').value);
  selectedTagId = tagId;
  const parent = document.querySelector('#tag-edit-parent').value;
  try {
    await request(`/api/tags/${tagId}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: document.querySelector('#tag-edit-name').value.trim(), parent_id: parent ? Number(parent) : null})
    });
    await loadTags(); await loadWorks(searchInput.value);
    flash('標籤已更新。');
  } catch (error) { flash(error.message, 'error'); }
});
document.querySelector('#publisher-normalize-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const normalizeForm = event.currentTarget;
  const canonicalInput = normalizeForm.querySelector('#publisher-canonical-name');
  const namesContainer = normalizeForm.querySelector('#publisher-existing-names');
  const canonicalName = canonicalInput.value.trim();
  const aliases = Array.from(
    namesContainer.querySelectorAll('input:checked')
  ).map((input) => input.value);
  if (!canonicalName) return;
  try {
    await request('/api/publishers/normalize', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({canonical_name: canonicalName, aliases})
    });
    normalizeForm.reset();
    await loadPublishers(); await loadWorks(searchInput.value);
    flash('出版社正規名稱與既有名稱已關聯。');
  } catch (error) { flash(error.message, 'error'); }
});
document.querySelector('#work-edit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const editForm = event.currentTarget;
  const tagInput = editForm.elements.namedItem('tag_names');
  if (!commitTagPickerInput(editForm.querySelector('[data-tag-picker]'))) return;
  const isNew = editingWorkId === null;
  try {
    activeWork = await request(isNew ? '/api/works' : `/api/works/${editingWorkId}`, {
      method: isNew ? 'POST' : 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        title: editForm.elements.namedItem('title').value.trim(),
        subtitle: editForm.elements.namedItem('subtitle').value.trim(),
        authors: editForm.elements.namedItem('authors').value.trim(),
        scripts: editForm.elements.namedItem('scripts').value.trim(),
        tag_ids: selectedValues(editForm.elements.namedItem('tag_ids')),
        tag_names: splitTerms(tagInput.value),
        edition_relations: workEditionRelations(
          editForm.querySelector('[data-work-edition-links]')
        )
      })
    });
    editingWorkId = activeWork.id;
    workEditDialog.close();
    await loadTags();
    await loadWorks(searchInput.value);
    activeTopEditionId = null;
    renderWorkDetail(activeWork);
    if (!detailDialog.open) detailDialog.showModal();
    flash(isNew ? '作品已建立並完成 Edition 關聯。' : '作品資料與 Edition 關聯已更新。');
  } catch (error) { flash(error.message, 'error'); }
});
document.querySelector('#edition-edit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const editForm = event.currentTarget;
  const get = (name) => editForm.elements.namedItem(name).value.trim();
  const year = get('publication_year');
  const otherTitles = titlePairValues(editForm.querySelector('[data-paired-titles]'));
  try {
    activeWork = await request(`/api/editions/${activeEdition.id}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        title: get('title'), subtitle: get('subtitle'),
        work_relations: editionWorkRelations(editForm.querySelector('[data-edition-work-links]')),
        version: repeatableValue(editForm, 'version', true),
        series: get('series'),
        identifier: repeatableValue(editForm, 'identifier'), publisher: get('publisher'),
        publisher_id: activeEdition.edition.publisher_id, publisher_canonical: activeEdition.edition.publisher_canonical,
        publication_year: year ? Number(year) : null, translator: get('translator'),
        edition_scripts: get('edition_scripts'),
        other_title: otherTitles.other_title, other_subtitle: otherTitles.other_subtitle,
        translated_title: get('translated_title'), translated_subtitle: get('translated_subtitle')
      })
    });
    editionEditDialog.close();
    await loadPublishers(); await loadWorks(searchInput.value);
    renderCurrentDetail();
    flash('版本資料已更新。');
  } catch (error) { flash(error.message, 'error'); }
});
document.querySelector('#copy-edit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const editForm = event.currentTarget;
  const get = (name) => editForm.elements.namedItem(name).value.trim();
  try {
    activeBook = await request(`/api/copies/${activeBook.id}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        volume_number: get('volume_number'), volume_title: get('volume_title'),
        acquisition_date: get('acquisition_date') || null,
        location: get('location'), reading_record: get('reading_record')
      })
    });
    copyEditDialog.close();
    copyDialog.close();
    activeWork = await request(`/api/works/${activeWork.id}`);
    await loadTags(); await loadPublishers(); await loadWorks(searchInput.value);
    renderCurrentDetail();
    flash(`實物冊 #${activeBook.id} 已更新。`);
  } catch (error) { flash(error.message, 'error'); }
});
document.querySelector('#edit-copy-button').addEventListener('click', () => {
  const editForm = document.querySelector('#copy-edit-form');
  for (const [key, value] of Object.entries(activeBook.copy)) editForm.elements.namedItem(key).value = value ?? '';
  copyEditDialog.showModal();
});
document.querySelector('#delete-copy-button').addEventListener('click', async () => {
  if (!activeBook) return;
  const label = `#${activeBook.id}${(activeBook.copy.volume_number || activeBook.copy.volume_title) ? `（卷冊 ${[activeBook.copy.volume_number, activeBook.copy.volume_title].filter(Boolean).join(' · ')}）` : ''}`;
  if (!window.confirm(`確定刪除實物冊 ${label} 嗎？`)) return;
  const workId = activeWork?.id;
  try {
    const result = await request(`/api/copies/${activeBook.id}`, {method: 'DELETE'});
    copyDialog.close();
    if (result.work_deleted || result.deleted_work_ids?.includes(workId) || !workId) {
      detailDialog.close();
      activeWork = null;
    } else {
      activeWork = await request(`/api/works/${workId}`);
    }
    activeBook = null;
    await loadWorks(searchInput.value);
    if (activeWork) renderCurrentDetail();
    flash('實物冊已刪除。');
  } catch (error) {
    flash(error.message, 'error');
  }
});
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  const id = document.querySelector('#copy-id').value;
  const isBatch = !id && form.elements.namedItem('copy-mode').value === 'batch';
  saveButton.disabled = true;
  try {
    const payload = formPayload();
    let saved;
    if (isBatch) {
      saved = await request('/api/books/batch', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...payload, ...batchVolumeData()})
      });
    } else {
      saved = await request(id ? '/api/books/' + id : '/api/books', {
        method: id ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
    }
    bookDialog.close();
    await loadTags(); await loadPublishers(); await loadWorks(searchInput.value);
    if (id) flash('藏書資料已更新。');
    else if (isBatch) flash('已在同一版本下新增 ' + saved.length + ' 冊。');
    else flash('實物冊 #' + saved.id + ' 已加入書架。');
  } catch (error) {
    flash(error.message, 'error');
  } finally {
    saveButton.disabled = false;
  }
});

function renderImportPreview() {
  const preview = document.querySelector('#import-preview');
  document.querySelector('#import-summary').textContent =
    `共讀取 ${importRows.length} 行；題名與作者、版本及卷冊會自動併入既有層級。`;
  preview.innerHTML = importRows.map((row, index) => {
    const book = row.book;
    const matches = row.matching_copies;
    const editionMatches = row.matching_edition_copies ?? [];
    const volumes = [...new Set(editionMatches.map((match) =>
      [match.volume_number, match.volume_title].filter(Boolean).join(' · ') || '未標卷冊'
    ))];
    const matchText = matches.length
      ? `找到 ${matches.length} 個同版本、同卷冊的實物冊`
      : editionMatches.length
        ? `已識別為同一版本；既有卷冊：${volumes.map(escapeHtml).join('; ')}`
        : '新增作品或版本';
    return `<div class="import-row">
      <label class="import-keep"><input type="checkbox" data-import-keep="${index}" checked> 保留</label>
      <div><strong>${escapeHtml(book.work.title)}</strong>
        <small>${shown(book.work.authors)} · ${shown(book.edition.version)} · 卷冊 ${shown([book.copy.volume_number, book.copy.volume_title].filter(Boolean).join(' · '))}</small>
        <small>${matchText}</small></div>
      <label>實物冊處理
        <select data-import-action="${index}" ${matches.length ? '' : 'disabled'}>
          ${matches.map((match) => match.id
            ? `<option value="copy:${match.id}">覆蓋實物冊 #${match.id}${match.location ? ` · ${escapeHtml(match.location)}` : ''}</option>`
            : `<option value="row:${match.row_number}">覆蓋本次 CSV 第 ${match.row_number} 行的實物冊</option>`
          ).join('')}
          <option value="import">${matches.length ? '仍新增為另一實物冊' : '新增實物冊'}</option>
        </select>
      </label>
    </div>`;
  }).join('') || '<div class="empty">CSV 沒有可導入的資料行。</div>';
  document.querySelector('#import-select-all').checked = true;
  document.querySelector('#import-select-all').indeterminate = false;
  document.querySelector('#import-confirm').disabled = importRows.length === 0;
}

document.querySelector('#import-select-all').addEventListener('change', (event) => {
  document.querySelectorAll('[data-import-keep]').forEach((checkbox) => {
    checkbox.checked = event.currentTarget.checked;
  });
});

document.querySelector('#import-preview').addEventListener('change', (event) => {
  if (!event.target.matches('[data-import-keep]')) return;
  const boxes = Array.from(document.querySelectorAll('[data-import-keep]'));
  const selected = boxes.filter((box) => box.checked).length;
  const selectAll = document.querySelector('#import-select-all');
  selectAll.checked = selected === boxes.length;
  selectAll.indeterminate = selected > 0 && selected < boxes.length;
});

csvFileInput.addEventListener('change', async () => {
  const file = csvFileInput.files?.[0];
  if (!file) return;
  importRows = [];
  document.querySelector('#import-summary').textContent = '正在分析 CSV……';
  document.querySelector('#import-preview').innerHTML = '';
  document.querySelector('#import-confirm').disabled = true;
  importDialog.showModal();
  try {
    const result = await request('/api/import/csv/preview', {
      method: 'POST', headers: {'Content-Type': 'text/csv; charset=utf-8'},
      body: await file.arrayBuffer()
    });
    importRows = result.rows;
    renderImportPreview();
  } catch (error) {
    document.querySelector('#import-summary').textContent = error.message;
  }
});

document.querySelector('#import-confirm').addEventListener('click', async () => {
  const button = document.querySelector('#import-confirm');
  button.disabled = true;
  try {
    const rows = importRows.map((row, index) => {
      const choice = document.querySelector(`[data-import-action="${index}"]`)?.value ?? 'import';
      const [kind, rawTarget] = choice.split(':');
      return {
        row_number: row.row_number,
        book: row.book,
        csv_fields: row.csv_fields,
        action: kind === 'import' ? 'create' : 'replace',
        target_copy_id: kind === 'copy' ? Number(rawTarget) : null,
        target_row_number: kind === 'row' ? Number(rawTarget) : null
      };
    }).filter((_, index) => document.querySelector(`[data-import-keep="${index}"]`)?.checked);
    const result = await request('/api/import/csv', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({rows})
    });
    importDialog.close();
    await loadTags(); await loadPublishers(); await loadWorks(searchInput.value);
    flash(`已新增 ${result.imported} 冊，覆蓋 ${result.overwritten} 冊實物冊。`);
  } catch (error) {
    flash(error.message, 'error');
    button.disabled = false;
  }
});

function addExportControls() {
  const controls = document.querySelector('.view-controls');
  const countNode = document.querySelector('#book-count');
  for (const format of ['json', 'csv']) {
    const link = document.createElement('a');
    link.className = 'secondary export-link';
    link.href = `/api/export/${format}`;
    link.download = `book-catalog.${format}`;
    link.textContent = `導出 ${format.toUpperCase()}`;
    controls.insertBefore(link, countNode);
  }
}

form.elements.namedItem('work.authors').placeholder = '多項用半角分號 ; 分隔';
form.elements.namedItem('work.scripts').placeholder = '多項用半角分號 ; 分隔';
setupTagPickers();
setupEditionWorkLinks();
setupWorkEditionLinks();
addExportControls();
const savedView = localStorage.getItem('book-catalog-view');
if (Array.from(viewSelect.options).some((option) => option.value === savedView)) {
  viewSelect.value = savedView;
}
const savedTopMode = localStorage.getItem('book-catalog-top-mode');
if (Array.from(topModeSelect.options).some((option) => option.value === savedTopMode)) {
  topModeSelect.value = savedTopMode;
}

Promise.all([loadTags(), loadPublishers(), loadWorks()])
  .catch((error) => flash(error.message, 'error'));
