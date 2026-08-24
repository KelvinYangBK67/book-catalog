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
const workEditDialog = document.querySelector('#work-edit-dialog');
const editionEditDialog = document.querySelector('#edition-edit-dialog');
const copyEditDialog = document.querySelector('#copy-edit-dialog');
const form = document.querySelector('#book-form');
const saveButton = document.querySelector('#save-button');
let works = [];
let activeWork = null;
let activeBook = null;
let activeEdition = null;
let tags = [];
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
    works = await request(`/api/works?q=${encodeURIComponent(query)}`);
    renderWorks(query);
  } catch (error) {
    list.innerHTML = `<div class="empty"><strong>暫時無法讀取藏書</strong>${escapeHtml(error.message)}</div>`;
  }
}

async function loadTags() {
  tags = await request('/api/tags');
  renderTagControls();
}

async function loadPublishers() {
  [publishers, publisherNames] = await Promise.all([
    request('/api/publishers'), request('/api/publishers/names')
  ]);
  renderPublisherControls();
}

function renderTagControls() {
  document.querySelector('#tag-suggestions').innerHTML = tags
    .map((tag) => `<option value="${escapeHtml(tag.name)}">${escapeHtml(tag.path)}</option>`).join('');
  document.querySelector('#tag-parent').innerHTML = '<option value="">無（頂級分類）</option>'
    + tags.map((tag) => `<option value="${tag.id}">${escapeHtml(tag.path)}</option>`).join('');
  document.querySelector('#tag-tree').innerHTML = tags.length
    ? tags.map((tag) => `<div class="tag-tree-row">
        <span>${escapeHtml(tag.path)}${tag.parent_id ? '<small>子分類</small>' : '<small>頂級</small>'}</span>
        <button class="danger compact" type="button" data-delete-tag="${tag.id}">刪除</button>
      </div>`).join('')
    : '<div class="empty">尚未建立任何標籤。</div>';
  const editSelect = document.querySelector('#tag-edit-id');
  editSelect.innerHTML = tags.map((tag) => `<option value="${tag.id}">${escapeHtml(tag.path)}</option>`).join('');
  document.querySelector('#tag-edit-parent').innerHTML = '<option value="">無（頂級分類）</option>'
    + tags.map((tag) => `<option value="${tag.id}">${escapeHtml(tag.path)}</option>`).join('');
  if (selectedTagId && tags.some((tag) => tag.id === selectedTagId)) {
    editSelect.value = String(selectedTagId);
  }
  fillTagEditForm();
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
  return items?.length ? `<span class="tag-chips">${items.map((tag) => `<span class="tag-chip">${escapeHtml(tag.path)}</span>`).join('')}</span>` : '';
}

function renderWorks(query) {
  const copies = works.reduce((total, work) => total + work.copy_count, 0);
  count.textContent = query ? `${works.length} 項作品搜尋結果` : `共 ${works.length} 部作品 · ${copies} 冊`;
  if (!works.length) {
    list.innerHTML = query
      ? '<div class="empty"><strong>沒有找到相符作品</strong>試試較短的關鍵詞，或搜尋其他字段。</div>'
      : '<div class="empty"><strong>書架還是空的</strong>按右上角「新增藏書」，記下你的第一冊書。</div>';
    return;
  }
  const dimension = viewSelect.value;
  if (dimension === 'all') {
    list.innerHTML = renderWorkRows(works);
    return;
  }
  const groups = new Map();
  for (const work of works) {
    let values = [];
    if (dimension === 'scripts') values = splitTerms(work.scripts, false);
    if (dimension === 'tags') values = work.tags.map((tag) => tag.path);
    if (dimension === 'publishers') values = work.publishers;
    if (dimension === 'locations') values = work.locations;
    if (dimension === 'years') values = work.years.map(String);
    if (!values.length) values = ['未記錄'];
    for (const value of new Set(values)) {
      if (!groups.has(value)) groups.set(value, []);
      groups.get(value).push(work);
    }
  }
  list.innerHTML = [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b, 'zh-Hant', {numeric: true}))
    .map(([label, items]) => `<section class="view-group"><h3>${escapeHtml(label)}<small>${items.length} 部</small></h3>${renderWorkRows(items)}</section>`)
    .join('');
}

function renderWorkRows(items) {
  return items.map((work) => `
    <button class="work-row" type="button" data-work-id="${work.id}">
      <span class="work-title"><strong>${escapeHtml(work.title)}</strong>${work.subtitle ? `<small>${escapeHtml(work.subtitle)}</small>` : ''}${tagChips(work.tags)}</span>
      <span class="cell"><span class="cell-label">作者或相關責任人</span>${shown(work.authors)}</span>
      <span class="cell stat"><b>${work.edition_count}</b><small>版本</small></span>
      <span class="cell stat"><b>${work.copy_count}</b><small>實物冊</small></span>
      <span class="arrow">›</span>
    </button>`).join('');
}

function splitTerms(value) {
  return String(value ?? '').split(';').map((item) => item.trim()).filter(Boolean);
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

function editionLabel(edition) {
  if (edition.version) return `版本 ${escapeHtml(edition.version)}`;
  if (edition.publisher) return escapeHtml(edition.publisher);
  if (edition.publication_year) return String(edition.publication_year);
  if (edition.identifier) return escapeHtml(edition.identifier);
  return '版本資料';
}

function publisherDisplay(edition) {
  if (edition.publisher && edition.publisher_canonical && edition.publisher !== edition.publisher_canonical) {
    return `${escapeHtml(edition.publisher)}（${escapeHtml(edition.publisher_canonical)}）`;
  }
  return shown(edition.publisher_canonical || edition.publisher);
}

function groupedVolumes(group) {
  const volumes = new Map();
  for (const copy of group.copies) {
    const key = copy.volume || '';
    if (!volumes.has(key)) volumes.set(key, []);
    volumes.get(key).push(copy);
  }
  return [...volumes.entries()];
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
    const [volume, copies] = volumes[0];
    if (!volume && copies.length === 1) {
      const copy = copies[0];
      return `<button class="location-single" type="button" data-copy-id="${copy.id}">
        <span><small>藏書位置</small>${shown(copy.location)}</span><span class="arrow">›</span>
      </button>`;
    }
    if (!volume) {
      return `<div class="copy-list">${copyRows(copies)}</div>`;
    }
    const volumeName = escapeHtml(volume);
    if (copies.length === 1) {
      const copy = copies[0];
      return `<button class="volume-single merged-volume" type="button" data-copy-id="${copy.id}">
        <span><small>卷冊</small><strong>${volumeName}</strong></span>
        <span><small>藏書位置</small>${shown(copy.location)}</span><span class="arrow">›</span>
      </button>`;
    }
    return `<div class="single-volume-group">
      <div class="single-volume-label"><span><small>卷冊</small><strong>${volumeName}</strong></span><span>${copies.length} 本重複藏書</span></div>
      <div class="copy-list">${copyRows(copies)}</div>
    </div>`;
  }
  return volumes.map(([volume, copies]) => {
    const volumeName = volume ? escapeHtml(volume) : '未標';
    if (copies.length === 1) {
      const copy = copies[0];
      return `<button class="volume-single" type="button" data-copy-id="${copy.id}">
        <span><small>卷冊</small><strong>${volumeName}</strong></span>
        <span><small>藏書位置</small>${shown(copy.location)}</span><span class="arrow">›</span>
      </button>`;
    }
    return `<details class="volume-duplicates">
      <summary><span><small>卷冊</small><strong>${volumeName}</strong></span><span>${copies.length} 本重複藏書</span><span class="disclosure">⌄</span></summary>
      <div class="copy-list">${copyRows(copies)}</div>
    </details>`;
  }).join('');
}

function renderEditionBody(group) {
  const effectiveScripts = group.edition.edition_scripts || activeWork?.work.scripts || '';
  return `<div class="edition-body">
    <div class="edition-meta">
      <span><small>系列</small>${shown(group.edition.series)}</span>
      <span><small>文種</small>${shown(effectiveScripts)}</span>
      <span><small>譯者或相關責任人</small>${shown(group.edition.translator)}</span>
      <span><small>其他標題</small>${shown(titlePairsText(group.edition.other_title, group.edition.other_subtitle))}</span>
      <span><small>翻譯標題</small>${shown(group.edition.translated_title)}</span>
      <span><small>翻譯副標題</small>${shown(group.edition.translated_subtitle)}</span>
    </div>
    <div class="volume-list">${renderVolumeContent(group)}</div>
    <button class="text-button" type="button" data-edit-edition="${group.id}">修改此版本</button>
    <button class="text-button" type="button" data-add-edition-copy="${group.id}">＋ 新增此版本的實物冊</button>
    <button class="text-button danger-text" type="button" data-delete-edition="${group.id}">刪除此版本</button>
  </div>`;
}

function renderWorkDetail(work) {
  document.querySelector('#detail-title').textContent = work.work.title;
  const author = work.work.authors
    ? `<p class="work-detail-author">${escapeHtml(work.work.authors)}</p>` : '';
  const subtitle = work.work.subtitle ? `<p class="work-detail-subtitle">${escapeHtml(work.work.subtitle)}</p>` : '';
  const scripts = work.work.scripts ? `<p class="work-detail-scripts"><small>文種</small>${escapeHtml(work.work.scripts)}</p>` : '';
  const assignedTags = tags.filter((tag) => work.work.tag_ids.includes(tag.id));
  let editions;
  if (work.editions.length === 1) {
    const group = work.editions[0];
    const volumes = groupedVolumes(group);
    const fullyCollapsed = !group.edition.version && volumes.length === 1
      && !volumes[0][0] && volumes[0][1].length === 1;
    if (fullyCollapsed) {
      const copy = volumes[0][1][0];
      editions = `<section class="collapsed-book">
        <button class="collapsed-book-row" type="button" data-copy-id="${copy.id}">
          <span><small>出版信息</small>${publisherDisplay(group.edition)}${group.edition.publication_year ? ` · ${group.edition.publication_year}` : ''}</span>
          <span><small>識別號</small>${shownLines(group.edition.identifier)}</span>
          <span><small>藏書位置</small>${shown(copy.location)}</span>
          <span class="arrow">›</span>
        </button>
        <div class="collapsed-actions">
          <button class="text-button" type="button" data-edit-edition="${group.id}">修改版本資料</button>
          <button class="text-button" type="button" data-add-edition-copy="${group.id}">＋ 新增實物冊</button>
        </div>
      </section>`;
    } else {
      editions = `<section class="merged-edition">
      <div class="merged-edition-header">
        <span class="edition-main"><strong>${editionLabel(group.edition)}</strong><small>${publisherDisplay(group.edition)}${group.edition.publication_year ? ` · ${group.edition.publication_year}` : ''}</small></span>
        <span class="edition-isbn"><small>識別號</small>${shownLines(group.edition.identifier)}</span>
      </div>
      ${renderEditionBody(group)}
    </section>`;
    }
  } else {
    editions = work.editions.map((group) => `
    <details class="edition-card">
      <summary>
        <span class="edition-main"><strong>${editionLabel(group.edition)}</strong><small>${publisherDisplay(group.edition)}${group.edition.publication_year ? ` · ${group.edition.publication_year}` : ''}</small></span>
        <span class="edition-isbn"><small>識別號</small>${shownLines(group.edition.identifier)}</span>
        <span class="edition-count">${group.copies.length} 冊</span>
        <span class="disclosure">⌄</span>
      </summary>
      ${renderEditionBody(group)}
    </details>`).join('');
  }
  document.querySelector('#detail-content').innerHTML = `
    <section class="work-overview">${subtitle}${author}${scripts}${tagChips(assignedTags)}<p>${work.editions.length} 個版本 · ${work.editions.reduce((sum, item) => sum + item.copies.length, 0)} 冊實物書</p></section>
    <section class="edition-list">${editions || '<div class="empty">此作品還沒有版本。</div>'}</section>`;
}

async function openWork(workId) {
  try {
    activeWork = await request(`/api/works/${workId}`);
    renderWorkDetail(activeWork);
    detailDialog.showModal();
  } catch (error) {
    flash(error.message, 'error');
  }
}

function pairs(items) {
  return `<dl class="details">${items.map(([label, value, wide, lines]) => `
    <div class="${wide ? 'wide' : ''}"><dt>${label}</dt><dd>${lines ? shownLines(value) : shown(value)}</dd></div>`).join('')}</dl>`;
}

async function openCopy(copyId) {
  try {
    activeBook = await request(`/api/books/${copyId}`);
    document.querySelector('#copy-detail-title').textContent = `${activeBook.work.title} · #${activeBook.id}`;
    document.querySelector('#copy-detail-content').innerHTML = `
      <section class="detail-section"><h3>01 · 作品信息</h3>${pairs([
        ['標題', activeBook.work.title, true], ['副標題', activeBook.work.subtitle, true],
        ['作者或相關責任人', activeBook.work.authors, true],
        ['文種', activeBook.work.scripts, true]
      ])}</section>
      <section class="detail-section"><h3>02 · 版本信息</h3>${pairs([
        ['版本', activeBook.edition.version], ['系列', activeBook.edition.series],
        ['識別號', activeBook.edition.identifier, false, true],
        ['出版社原始名稱', activeBook.edition.publisher], ['出版社實體', activeBook.edition.publisher_canonical],
        ['出版年份', activeBook.edition.publication_year],
        ['文種', activeBook.edition.edition_scripts || activeBook.work.scripts],
        ['譯者或相關責任人', activeBook.edition.translator],
        ['其他標題', titlePairsText(activeBook.edition.other_title, activeBook.edition.other_subtitle), true],
        ['翻譯標題', activeBook.edition.translated_title, true],
        ['翻譯副標題', activeBook.edition.translated_subtitle, true]
      ])}</section>
      <section class="detail-section"><h3>03 · 實物冊 #${activeBook.id}</h3>${pairs([
        ['卷冊', activeBook.copy.volume], ['取得日期', activeBook.copy.acquisition_date],
        ['藏書位置', activeBook.copy.location],
        ['閱讀記錄', activeBook.copy.reading_record, true]
      ])}</section>`;
    copyDialog.showModal();
  } catch (error) {
    flash(error.message, 'error');
  }
}

function setField(name, value) {
  const control = form.elements.namedItem(name);
  if (control) control.value = value ?? '';
}

enhanceRepeatable(form, 'edition.identifier', '添加識別號');
enhanceRepeatable(form, 'edition.version', '添加版本');
enhanceRepeatable(document.querySelector('#edition-edit-form'), 'identifier', '添加識別號');
enhanceRepeatable(document.querySelector('#edition-edit-form'), 'version', '添加版本');

function openForm(book = null, presetWork = null, presetEdition = null) {
  form.reset();
  setRepeatable(form, 'edition.identifier', '');
  setRepeatable(form, 'edition.version', '');
  setTitlePairs(form.querySelector('[data-paired-titles]'));
  document.querySelector('#copy-id').value = book?.id ?? '';
  document.querySelector('#form-mode').textContent = book ? 'EDIT COPY' : 'NEW COPY';
  document.querySelector('#form-title').textContent = book ? '修改藏書' : '新增藏書';
  saveButton.textContent = book ? '保存修改' : '保存藏書';
  const sourceWork = book?.work ?? presetWork;
  const sourceEdition = book?.edition ?? presetEdition;
  if (sourceWork) {
    for (const [key, value] of Object.entries(sourceWork)) {
      if (key !== 'tag_ids' && key !== 'tag_names') setField(`work.${key}`, value);
    }
    const assigned = sourceWork.tag_names?.length
      ? sourceWork.tag_names
      : tags.filter((tag) => (sourceWork.tag_ids ?? []).includes(tag.id)).map((tag) => tag.name);
    setField('work.tags', assigned.join('; '));
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
  const get = (name) => form.elements.namedItem(name).value.trim();
  const year = get('edition.publication_year');
  const otherTitles = titlePairValues(form.querySelector('[data-paired-titles]'));
  return {
    work: {
      title: get('work.title'), subtitle: get('work.subtitle'),
      authors: get('work.authors'), scripts: get('work.scripts'), tag_ids: [],
      tag_names: splitTerms(get('work.tags'))
    },
    edition: {
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
      volume: get('copy.volume'),
      acquisition_date: get('copy.acquisition_date') || null,
      location: get('copy.location'), reading_record: get('copy.reading_record')
    }
  };
}

searchForm.addEventListener('submit', (event) => {
  event.preventDefault(); loadWorks(searchInput.value);
});
document.querySelector('#add-button').addEventListener('click', () => openForm());
document.querySelector('#tags-button').addEventListener('click', () => tagsDialog.showModal());
document.querySelector('#publishers-button').addEventListener('click', () => publishersDialog.showModal());
document.querySelector('#import-button').addEventListener('click', () => {
  csvFileInput.value = '';
  csvFileInput.click();
});
viewSelect.addEventListener('change', () => renderWorks(searchInput.value));
document.querySelector('.brand').addEventListener('click', (event) => {
  event.preventDefault(); searchInput.value = ''; loadWorks();
});
list.addEventListener('click', (event) => {
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
    if (!group || !window.confirm(`確定刪除此版本及其 ${group.copies.length} 冊實物書嗎？`)) return;
    try {
      const result = await request(`/api/editions/${group.id}`, {method: 'DELETE'});
      if (result.work_deleted) {
        detailDialog.close();
        activeWork = null;
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
    openForm(null, activeWork.work, group.edition);
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
  detailDialog.close(); openForm(null, activeWork.work);
});
document.querySelector('#delete-work-button').addEventListener('click', async () => {
  if (!activeWork || !window.confirm(`確定刪除作品「${activeWork.work.title}」及其所有版本與實物冊嗎？`)) return;
  try {
    await request(`/api/works/${activeWork.id}`, {method: 'DELETE'});
    detailDialog.close();
    activeWork = null;
    await loadWorks(searchInput.value);
    flash('作品及其所有版本與實物冊已刪除。');
  } catch (error) {
    flash(error.message, 'error');
  }
});
document.querySelector('#edit-work-button').addEventListener('click', () => {
  const editForm = document.querySelector('#work-edit-form');
  editForm.elements.namedItem('title').value = activeWork.work.title;
  editForm.elements.namedItem('subtitle').value = activeWork.work.subtitle;
  editForm.elements.namedItem('authors').value = activeWork.work.authors;
  editForm.elements.namedItem('scripts').value = activeWork.work.scripts;
  const assignedTagNames = activeWork.work.tag_names?.length
    ? activeWork.work.tag_names
    : tags.filter((tag) => activeWork.work.tag_ids.includes(tag.id)).map((tag) => tag.name);
  const tagInput = editForm.elements.namedItem('tag_names');
  tagInput.value = assignedTagNames.join('; ');
  tagInput.dataset.original = tagInput.value;
  workEditDialog.showModal();
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
  const tagsChanged = tagInput.value.trim() !== (tagInput.dataset.original ?? '');
  try {
    activeWork = await request(`/api/works/${activeWork.id}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        title: editForm.elements.namedItem('title').value.trim(),
        subtitle: editForm.elements.namedItem('subtitle').value.trim(),
        authors: editForm.elements.namedItem('authors').value.trim(),
        scripts: editForm.elements.namedItem('scripts').value.trim(),
        tag_ids: tagsChanged ? [] : activeWork.work.tag_ids,
        tag_names: tagsChanged ? splitTerms(tagInput.value) : []
      })
    });
    workEditDialog.close();
    renderWorkDetail(activeWork);
    await loadWorks(searchInput.value);
    flash('作品資料已更新。');
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
    renderWorkDetail(activeWork);
    await loadPublishers(); await loadWorks(searchInput.value);
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
        volume: get('volume'), acquisition_date: get('acquisition_date') || null,
        location: get('location'), reading_record: get('reading_record')
      })
    });
    copyEditDialog.close();
    copyDialog.close();
    activeWork = await request(`/api/works/${activeWork.id}`);
    renderWorkDetail(activeWork);
    await loadTags(); await loadPublishers(); await loadWorks(searchInput.value);
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
  const label = `#${activeBook.id}${activeBook.copy.volume ? `（卷冊 ${activeBook.copy.volume}）` : ''}`;
  if (!window.confirm(`確定刪除實物冊 ${label} 嗎？`)) return;
  const workId = activeWork?.id;
  try {
    const result = await request(`/api/copies/${activeBook.id}`, {method: 'DELETE'});
    copyDialog.close();
    if (result.work_deleted || !workId) {
      detailDialog.close();
      activeWork = null;
    } else {
      activeWork = await request(`/api/works/${workId}`);
      renderWorkDetail(activeWork);
    }
    activeBook = null;
    await loadWorks(searchInput.value);
    flash('實物冊已刪除。');
  } catch (error) {
    flash(error.message, 'error');
  }
});
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  const id = document.querySelector('#copy-id').value;
  saveButton.disabled = true;
  try {
    const saved = await request(id ? `/api/books/${id}` : '/api/books', {
      method: id ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(formPayload())
    });
    bookDialog.close();
    await loadTags(); await loadPublishers(); await loadWorks(searchInput.value);
    flash(id ? '藏書資料已更新。' : `實物冊 #${saved.id} 已加入書架。`);
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
    const volumes = [...new Set(editionMatches.map((match) => match.volume || '未標卷冊'))];
    const matchText = matches.length
      ? `找到 ${matches.length} 個同版本、同卷冊的 Copy`
      : editionMatches.length
        ? `已識別為同一版本；既有卷冊：${volumes.map(escapeHtml).join('; ')}`
        : '新增作品或版本';
    return `<div class="import-row">
      <label class="import-keep"><input type="checkbox" data-import-keep="${index}" checked> 保留</label>
      <div><strong>${escapeHtml(book.work.title)}</strong>
        <small>${shown(book.work.authors)} · ${shown(book.edition.version)} · 卷冊 ${shown(book.copy.volume)}</small>
        <small>${matchText}</small></div>
      <label>Copy 處理
        <select data-import-action="${index}" ${matches.length ? '' : 'disabled'}>
          ${matches.map((match) => match.id
            ? `<option value="copy:${match.id}">覆蓋 Copy #${match.id}${match.location ? ` · ${escapeHtml(match.location)}` : ''}</option>`
            : `<option value="row:${match.row_number}">覆蓋本次 CSV 第 ${match.row_number} 行的 Copy</option>`
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
    flash(`已新增 ${result.imported} 冊，覆蓋 ${result.overwritten} 冊實物書。`);
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

form.elements.namedItem('work.authors').placeholder = '多位請用半角分號;分隔';
form.elements.namedItem('work.scripts').placeholder = '例如：藏文; 漢文';
form.elements.namedItem('work.tags').placeholder = '例如：藏文; 佛教; 西藏';
document.querySelector('#work-edit-form').elements.namedItem('tag_names').placeholder = '以半角分號;分隔';
addExportControls();

Promise.all([loadTags(), loadPublishers(), loadWorks()])
  .catch((error) => flash(error.message, 'error'));
