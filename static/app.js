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

const escapeHtml = (value) => String(value ?? '')
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
const shown = (value) => value === null || value === undefined || value === '' ? '—' : escapeHtml(value);

function flash(message) {
  notice.textContent = message;
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
  publishers = await request('/api/publishers');
  renderPublisherControls();
}

function renderTagControls() {
  document.querySelector('#tag-suggestions').innerHTML = tags
    .map((tag) => `<option value="${escapeHtml(tag.name)}">${escapeHtml(tag.path)}</option>`).join('');
  document.querySelector('#tag-parent').innerHTML = '<option value="">無（頂級分類）</option>'
    + tags.map((tag) => `<option value="${tag.id}">${escapeHtml(tag.path)}</option>`).join('');
  document.querySelector('#tag-tree').innerHTML = tags.length
    ? tags.map((tag) => `<div class="tag-tree-row">${escapeHtml(tag.path)}${tag.parent_id ? '<small>子分類</small>' : '<small>頂級</small>'}</div>`).join('')
    : '<div class="empty">尚未建立任何標籤。</div>';
  const editSelect = document.querySelector('#tag-edit-id');
  editSelect.innerHTML = tags.map((tag) => `<option value="${tag.id}">${escapeHtml(tag.path)}</option>`).join('');
  document.querySelector('#tag-edit-parent').innerHTML = '<option value="">無（頂級分類）</option>'
    + tags.map((tag) => `<option value="${tag.id}">${escapeHtml(tag.path)}</option>`).join('');
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
  const options = publishers.map((publisher) =>
    `<option value="${publisher.id}">${escapeHtml(publisher.canonical_name)}</option>`).join('');
  document.querySelector('#publisher-target').innerHTML = options;
  document.querySelector('#publisher-suggestions').innerHTML = publishers.flatMap((publisher) =>
    publisher.aliases.map((alias) => `<option value="${escapeHtml(alias)}">${escapeHtml(publisher.canonical_name)}</option>`)
  ).join('');
  document.querySelector('#publisher-list').innerHTML = publishers.length ? publishers.map((publisher) => `
    <div class="publisher-row"><strong>${escapeHtml(publisher.canonical_name)}</strong>
      <span>${publisher.aliases.map((alias) => `<span class="tag-chip">${escapeHtml(alias)}</span>`).join('')}</span>
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
      <span class="cell"><span class="cell-label">作者或相關責任人</span>${shown(work.authors)}${work.scripts ? `<small>${escapeHtml(work.scripts)}</small>` : ''}</span>
      <span class="cell stat"><b>${work.edition_count}</b><small>版本</small></span>
      <span class="cell stat"><b>${work.copy_count}</b><small>實物冊</small></span>
      <span class="arrow">›</span>
    </button>`).join('');
}

function splitTerms(value, whitespace = true) {
  const pattern = whitespace ? /[\s、,，;；]+/ : /[、,，;；]+/;
  return String(value ?? '').split(pattern).map((item) => item.trim()).filter(Boolean);
}

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
  return `<div class="edition-body">
    <div class="edition-meta">
      <span><small>譯者或相關責任人</small>${shown(group.edition.translator)}</span>
      <span><small>翻譯題名</small>${shown(group.edition.translated_title)}</span>
      <span><small>譯本文種</small>${shown(group.edition.translation_script)}</span>
    </div>
    <div class="volume-list">${renderVolumeContent(group)}</div>
    <button class="text-button" type="button" data-edit-edition="${group.id}">修改此版本</button>
    <button class="text-button" type="button" data-add-edition-copy="${group.id}">＋ 新增此版本的實物冊</button>
  </div>`;
}

function renderWorkDetail(work) {
  document.querySelector('#detail-title').textContent = work.work.title;
  const author = work.work.authors
    ? `<p class="work-detail-author">${escapeHtml(work.work.authors)}</p>` : '';
  const subtitle = work.work.subtitle ? `<p class="work-detail-subtitle">${escapeHtml(work.work.subtitle)}</p>` : '';
  const scripts = work.work.scripts ? `<p class="work-detail-scripts">文種 · ${escapeHtml(work.work.scripts)}</p>` : '';
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
          <span><small>ISBN／識別號</small>${shown(group.edition.identifier)}</span>
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
        <span class="edition-isbn"><small>ISBN／識別號</small>${shown(group.edition.identifier)}</span>
      </div>
      ${renderEditionBody(group)}
    </section>`;
    }
  } else {
    editions = work.editions.map((group) => `
    <details class="edition-card">
      <summary>
        <span class="edition-main"><strong>${editionLabel(group.edition)}</strong><small>${publisherDisplay(group.edition)}${group.edition.publication_year ? ` · ${group.edition.publication_year}` : ''}</small></span>
        <span class="edition-isbn"><small>ISBN／識別號</small>${shown(group.edition.identifier)}</span>
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
    flash(error.message);
  }
}

function pairs(items) {
  return `<dl class="details">${items.map(([label, value, wide]) => `
    <div class="${wide ? 'wide' : ''}"><dt>${label}</dt><dd>${shown(value)}</dd></div>`).join('')}</dl>`;
}

async function openCopy(copyId) {
  try {
    activeBook = await request(`/api/books/${copyId}`);
    document.querySelector('#copy-detail-title').textContent = `${activeBook.work.title} · #${activeBook.id}`;
    document.querySelector('#copy-detail-content').innerHTML = `
      <section class="detail-section"><h3>01 · 作品信息</h3>${pairs([
        ['題名', activeBook.work.title, true], ['副標題', activeBook.work.subtitle, true],
        ['作者或相關責任人', activeBook.work.authors, true], ['文種', activeBook.work.scripts, true]
      ])}</section>
      <section class="detail-section"><h3>02 · 版本信息</h3>${pairs([
        ['版本', activeBook.edition.version], ['ISBN／識別號', activeBook.edition.identifier],
        ['出版社原始名稱', activeBook.edition.publisher], ['出版社實體', activeBook.edition.publisher_canonical],
        ['出版年份', activeBook.edition.publication_year],
        ['譯者或相關責任人', activeBook.edition.translator], ['譯本文種', activeBook.edition.translation_script],
        ['其他題名', activeBook.edition.other_title, true],
        ['翻譯題名', activeBook.edition.translated_title, true],
        ['翻譯副標題', activeBook.edition.translated_subtitle, true]
      ])}</section>
      <section class="detail-section"><h3>03 · 實物冊 #${activeBook.id}</h3>${pairs([
        ['卷冊', activeBook.copy.volume], ['取得日期', activeBook.copy.acquisition_date],
        ['藏書位置', activeBook.copy.location],
        ['閱讀記錄', activeBook.copy.reading_record, true]
      ])}</section>`;
    copyDialog.showModal();
  } catch (error) {
    flash(error.message);
  }
}

function setField(name, value) {
  const control = form.elements.namedItem(name);
  if (control) control.value = value ?? '';
}

function openForm(book = null, presetWork = null, presetEdition = null) {
  form.reset();
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
    const assigned = tags.filter((tag) => (sourceWork.tag_ids ?? []).includes(tag.id)).map((tag) => tag.name);
    setField('work.tags', assigned.join(' '));
  }
  if (sourceEdition) {
    for (const [key, value] of Object.entries(sourceEdition)) setField(`edition.${key}`, value);
  }
  if (book) {
    for (const [key, value] of Object.entries(book.copy)) setField(`copy.${key}`, value);
  }
  bookDialog.showModal();
}

function formPayload() {
  const get = (name) => form.elements.namedItem(name).value.trim();
  const year = get('edition.publication_year');
  return {
    work: {
      title: get('work.title'), subtitle: get('work.subtitle'),
      authors: get('work.authors'), scripts: get('work.scripts'), tag_ids: [],
      tag_names: splitTerms(get('work.tags'))
    },
    edition: {
      identifier: get('edition.identifier'), translator: get('edition.translator'),
      other_title: get('edition.other_title'),
      translated_title: get('edition.translated_title'),
      translated_subtitle: get('edition.translated_subtitle'),
      translation_script: get('edition.translation_script'),
      version: get('edition.version'),
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
viewSelect.addEventListener('change', () => renderWorks(searchInput.value));
document.querySelector('.brand').addEventListener('click', (event) => {
  event.preventDefault(); searchInput.value = ''; loadWorks();
});
list.addEventListener('click', (event) => {
  const row = event.target.closest('[data-work-id]');
  if (row) openWork(Number(row.dataset.workId));
});
document.querySelector('#detail-content').addEventListener('click', (event) => {
  const copyRow = event.target.closest('[data-copy-id]');
  if (copyRow) {
    openCopy(Number(copyRow.dataset.copyId));
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
      const control = editForm.elements.namedItem(key);
      if (control) control.value = value ?? '';
    }
    editionEditDialog.showModal();
  }
});
document.querySelector('#add-work-copy-button').addEventListener('click', () => {
  detailDialog.close(); openForm(null, activeWork.work);
});
document.querySelector('#edit-work-button').addEventListener('click', () => {
  const editForm = document.querySelector('#work-edit-form');
  editForm.elements.namedItem('title').value = activeWork.work.title;
  editForm.elements.namedItem('subtitle').value = activeWork.work.subtitle;
  editForm.elements.namedItem('authors').value = activeWork.work.authors;
  editForm.elements.namedItem('scripts').value = activeWork.work.scripts;
  editForm.elements.namedItem('tag_names').value = tags
    .filter((tag) => activeWork.work.tag_ids.includes(tag.id)).map((tag) => tag.name).join(' ');
  workEditDialog.showModal();
});
document.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => bookDialog.close()));
document.querySelectorAll('[data-detail-close]').forEach((button) => button.addEventListener('click', () => detailDialog.close()));
document.querySelectorAll('[data-copy-close]').forEach((button) => button.addEventListener('click', () => copyDialog.close()));
document.querySelectorAll('[data-tags-close]').forEach((button) => button.addEventListener('click', () => tagsDialog.close()));
document.querySelectorAll('[data-publishers-close]').forEach((button) => button.addEventListener('click', () => publishersDialog.close()));
document.querySelectorAll('[data-work-edit-close]').forEach((button) => button.addEventListener('click', () => workEditDialog.close()));
document.querySelectorAll('[data-edition-edit-close]').forEach((button) => button.addEventListener('click', () => editionEditDialog.close()));
document.querySelectorAll('[data-copy-edit-close]').forEach((button) => button.addEventListener('click', () => copyEditDialog.close()));
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
    flash(error.message);
  }
});
document.querySelector('#tag-edit-id').addEventListener('change', fillTagEditForm);
document.querySelector('#tag-edit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const tagId = Number(document.querySelector('#tag-edit-id').value);
  const parent = document.querySelector('#tag-edit-parent').value;
  try {
    await request(`/api/tags/${tagId}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: document.querySelector('#tag-edit-name').value.trim(), parent_id: parent ? Number(parent) : null})
    });
    await loadTags(); await loadWorks(searchInput.value);
    flash('標籤已更新。');
  } catch (error) { flash(error.message); }
});
document.querySelector('#publisher-alias-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const publisherId = Number(document.querySelector('#publisher-target').value);
  const alias = document.querySelector('#publisher-alias').value.trim();
  if (!publisherId || !alias) return;
  try {
    await request(`/api/publishers/${publisherId}/aliases`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({alias})
    });
    document.querySelector('#publisher-alias').value = '';
    await loadPublishers(); await loadWorks(searchInput.value);
    flash('出版社名稱關聯已保存，後續錄入會自動識別。');
  } catch (error) { flash(error.message); }
});
document.querySelector('#work-edit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const editForm = event.currentTarget;
  try {
    activeWork = await request(`/api/works/${activeWork.id}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        title: editForm.elements.namedItem('title').value.trim(),
        subtitle: editForm.elements.namedItem('subtitle').value.trim(),
        authors: editForm.elements.namedItem('authors').value.trim(),
        scripts: editForm.elements.namedItem('scripts').value.trim(), tag_ids: [],
        tag_names: splitTerms(editForm.elements.namedItem('tag_names').value)
      })
    });
    workEditDialog.close();
    renderWorkDetail(activeWork);
    await loadWorks(searchInput.value);
    flash('作品資料已更新。');
  } catch (error) { flash(error.message); }
});
document.querySelector('#edition-edit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const editForm = event.currentTarget;
  const get = (name) => editForm.elements.namedItem(name).value.trim();
  const year = get('publication_year');
  try {
    activeWork = await request(`/api/editions/${activeEdition.id}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        version: get('version'), identifier: get('identifier'), publisher: get('publisher'),
        publisher_id: activeEdition.edition.publisher_id, publisher_canonical: activeEdition.edition.publisher_canonical,
        publication_year: year ? Number(year) : null, translator: get('translator'),
        translation_script: get('translation_script'), other_title: get('other_title'),
        translated_title: get('translated_title'), translated_subtitle: get('translated_subtitle')
      })
    });
    editionEditDialog.close();
    renderWorkDetail(activeWork);
    await loadPublishers(); await loadWorks(searchInput.value);
    flash('版本資料已更新。');
  } catch (error) { flash(error.message); }
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
  } catch (error) { flash(error.message); }
});
document.querySelector('#edit-copy-button').addEventListener('click', () => {
  const editForm = document.querySelector('#copy-edit-form');
  for (const [key, value] of Object.entries(activeBook.copy)) editForm.elements.namedItem(key).value = value ?? '';
  copyEditDialog.showModal();
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
    flash(error.message);
  } finally {
    saveButton.disabled = false;
  }
});

Promise.all([loadTags(), loadPublishers(), loadWorks()]).catch((error) => flash(error.message));
