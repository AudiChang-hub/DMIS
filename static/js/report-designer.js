/* 單一正式畫布 + 保留原驗證表單；預覽資料不落地。 */
function designerScale(mode, width, height, availableWidth, availableHeight) {
  if (mode === 'fit') return Math.min(1, Math.max(0.1, availableWidth / width));
  if (mode === 'page') return Math.min(1, Math.max(0.05, Math.min(availableWidth / width, availableHeight / height)));
  return Math.max(0.1, Math.min(2, Number(mode) || 1));
}
if (typeof module !== 'undefined') module.exports = {designerScale};
if (typeof document !== 'undefined') (() => {
  'use strict';
  const editor = document.querySelector('[data-report-editor]');
  if (!editor) return;
  document.body.classList.add('report-designer-shell');
  const bench = editor.querySelector('[data-workbench]'), forms = editor.querySelector('[data-report-cards]');
  const canvas = editor.querySelector('[data-design-canvas]'), viewport = canvas.parentElement;
  const status = editor.querySelector('[data-canvas-status]'), list = editor.querySelector('[data-designer-chart-list]');
  const widthControl = editor.querySelector('[data-canvas-width]'), zoomControl = editor.querySelector('[data-canvas-zoom]');
  const frame = document.createElement('iframe'); frame.title = '完整報表畫布（尚未發布）';
  frame.setAttribute('sandbox', 'allow-scripts allow-downloads allow-modals'); canvas.append(frame);
  const panels = () => [...forms.querySelectorAll('[data-report-card]')].filter(el => !el.hidden);
  const field = (panel, name) => panel?.querySelector(`[name$="-${name}"]`);
  let selected, tab = 'data', mode = 'edit', channel = '', snapshot, controller, timer;
  let sequence = 0, generation = 0, height = 900;
  const bridgeControllers = new Set(), bridgeRequests = new Map();
  bench.hidden = false;
  const settings = document.createElement('details'); settings.className = 'report-panel report-page-settings';
  const summary = document.createElement('summary'); summary.textContent = '整份報表設定、固定範圍、附表與資料字典'; settings.append(summary);
  [...editor.children].filter(el => el.matches('section.report-panel,details.report-panel')).forEach(el => settings.append(el));
  editor.insertBefore(settings, bench); if (settings.querySelector('.errorlist')) settings.open = true;
  function send(type, extra = {}) { frame.contentWindow?.postMessage({channel, type, ...extra}, '*'); }
  function resizeCanvas() {
    const width = Number(widthControl.value), scale = designerScale(zoomControl.value, width, height, viewport.clientWidth - 32, viewport.clientHeight - 32);
    frame.style.width = `${width}px`; frame.style.height = `${height}px`; frame.style.transform = `scale(${scale})`;
    canvas.style.width = `${width * scale}px`; canvas.style.height = `${height * scale}px`;
    editor.querySelector('[data-zoom-label]').textContent = `${Math.round(scale * 100)}%`;
  }
  new ResizeObserver(resizeCanvas).observe(viewport);
  function propertyGroup(name) {
    if (['show_tooltip', 'cross_filter'].includes(name)) return 'interaction';
    if (['width', 'height'].includes(name)) return 'layout';
    if (['chart', 'title', 'font_size', 'title_align', 'palette', 'show_legend'].includes(name)) return 'style';
    return 'data';
  }
  function select(panel) {
    selected = panel;
    panels().forEach(item => {
      item.dataset.selected = String(item === panel);
      item.querySelectorAll('.report-form-grid > .report-field').forEach(wrapper => {
        const input = wrapper.querySelector('[name]'); if (!input || wrapper.closest('.report-card-scope')) return;
        wrapper.style.display = propertyGroup(input.name.split('-').slice(2).join('-')) === tab ? '' : 'none';
      });
      const scope = item.querySelector('.report-card-scope'); if (scope) scope.style.display = tab === 'data' ? '' : 'none';
    });
    [...list.children].forEach((button, index) => button.setAttribute('aria-pressed', String(panels()[index] === panel)));
    editor.querySelector('[data-interaction-help]').hidden = tab !== 'interaction';
    send('state', {mode, selected: panels().indexOf(selected)});
  }
  function sync() {
    list.replaceChildren();
    panels().forEach((panel, index) => {
      const button = document.createElement('button'); button.type = 'button'; button.dataset.selectChart = '';
      button.textContent = `${index + 1}. ${field(panel, 'title').value || '新圖表'}`;
      button.addEventListener('click', () => { select(panel); send('reveal', {index}); }); list.append(button);
    });
    select(panels().includes(selected) ? selected : panels()[0]);
  }
  function setTab(next) {
    tab = next;
    editor.querySelectorAll('[data-property-tab]').forEach(button => { button.setAttribute('aria-selected', String(button.dataset.propertyTab === tab)); button.tabIndex = button.dataset.propertyTab === tab ? 0 : -1; });
    select(selected);
  }
  function setMode(next) {
    mode = next;
    editor.querySelectorAll('[data-designer-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.designerMode === mode)));
    editor.querySelector('[data-mode-help]').textContent = mode === 'edit' ? '選取圖表後在右側設定；拖曳選取框標題排序、右下角調整大小，也可用上移／下移與尺寸欄位。' : '與正式報表相同的操作：滑入顯示細項、點選分類連動、Ctrl／⌘ 複選、查看明細及匯出；不會修改原始資料。';
    send('state', {mode, selected: panels().indexOf(selected)});
  }
  async function requestPreview(body, signal) {
    const response = await fetch(editor.getAttribute('action') || location.href, {method:'POST', body, credentials:'same-origin', signal});
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('登入逾時或伺服器暫時無法回應；輸入仍保留，請確認登入後重試。');
    const payload = await response.json();
    if (!response.ok) {
      const messages = [];
      const collect = value => { if (typeof value === 'string') messages.push(value); else if (Array.isArray(value)) value.forEach(collect); else if (value && typeof value === 'object') { if (value.message) messages.push(value.message); else Object.values(value).forEach(collect); } };
      collect(payload.errors); throw new Error(messages.slice(0, 6).join('；') || '請檢查必填欄位及圖表設定。');
    }
    return payload;
  }
  async function refresh() {
    clearTimeout(timer); controller?.abort(); controller = new AbortController();
    bridgeControllers.forEach(c => c.abort());
    const own = controller, id = ++sequence, version = generation, nextChannel = crypto.randomUUID();
    const timeout = setTimeout(() => own.abort(), 30000);
    status.textContent = '正在產生與正式報表相同的整頁預覽…'; canvas.setAttribute('aria-busy', 'true');
    const body = new FormData(editor); body.set('action', 'canvas'); body.set('preview_channel', nextChannel);
    try {
      const payload = await requestPreview(body, own.signal);
      if (id !== sequence || version !== generation) return;
      if (payload.status >= 400) throw new Error('報表設定或篩選無法預覽，請檢查後再試。');
      snapshot = body; channel = nextChannel; frame.srcdoc = payload.document;
      status.textContent = `已更新 ${panels().length} 張圖表及整頁版面。尚未儲存／發布；內容寬度是報表本體，不含導覽列。`;
    } catch (error) { if (id === sequence && version === generation) status.textContent = `預覽未更新：${error.name === 'AbortError' ? '查詢逾時，可按更新預覽重試。' : error.message}`; }
    finally { clearTimeout(timeout); if (id === sequence) canvas.setAttribute('aria-busy', 'false'); }
  }
  function changed() {
    generation++; controller?.abort(); sync(); status.textContent = '設定已變更，正在排程更新；尚未儲存或發布。';
    clearTimeout(timer); timer = setTimeout(refresh, 650);
  }
  window.addEventListener('message', async event => {
    const msg = event.data;
    if (event.source !== frame.contentWindow || !msg || msg.channel !== channel || !channel) return;
    if (msg.type === 'ready') send('state', {mode, selected: panels().indexOf(selected)});
    if (msg.type === 'notice' && typeof msg.message === 'string') status.textContent = msg.message;
    if (msg.type === 'cancel') bridgeRequests.get(msg.id)?.abort();
    if (msg.type === 'height' && Number.isFinite(msg.height)) { height = Math.max(300, Math.min(100000, msg.height)); resizeCanvas(); }
    if (msg.type === 'select' && Number.isInteger(msg.index)) select(panels()[msg.index]);
    if (msg.type === 'resize' && mode === 'edit') {
      const panel = panels()[msg.index]; if (!panel) return;
      field(panel, 'height').value = String(Math.max(320, Math.min(1200, Math.round(Number(msg.height) || 520))));
      field(panel, 'width').value = msg.width === 12 ? '12' : '6';
      editor.dispatchEvent(new Event('report-layout-change')); changed();
    }
    if (msg.type === 'move' && mode === 'edit') {
      const all = panels(), panel = all[msg.index], target = all[msg.target]; if (!panel || !target || panel === target) return;
      forms.insertBefore(panel, msg.index < msg.target ? target.nextSibling : target);
      editor.dispatchEvent(new Event('report-layout-change')); changed();
    }
    if (msg.type === 'request' && typeof msg.id === 'string' && typeof msg.url === 'string' && snapshot) {
      if (bridgeRequests.size >= 3) { send('response', {id:msg.id, error:'預覽查詢進行中，請稍後重試。'}); return; }
      const ownChannel = channel, bridge = new AbortController(); bridgeControllers.add(bridge);
      bridgeRequests.set(msg.id, bridge);
      const timeout = setTimeout(() => bridge.abort(), 30000);
      try {
        const url = new URL(msg.url, location.origin);
        if (url.origin !== location.origin || !url.pathname.startsWith('/reports/')) throw new Error('預覽不支援此連結。');
        const body = new FormData(); for (const [key, value] of snapshot) body.append(key, value);
        body.set('preview_url', url.pathname + url.search);
        const payload = await requestPreview(body, bridge.signal);
        if (channel === ownChannel) send('response', {id:msg.id, ...payload});
      } catch (error) { if (channel === ownChannel) send('response', {id:msg.id, error:error.name === 'AbortError' ? '預覽查詢逾時，請重試。' : error.message}); }
      finally { clearTimeout(timeout); bridgeControllers.delete(bridge); if (bridgeRequests.get(msg.id) === bridge) bridgeRequests.delete(msg.id); }
    }
  });
  editor.addEventListener('input', event => { if (event.target.name) changed(); });
  editor.addEventListener('change', event => { if (event.target.name) changed(); });
  editor.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button) return;
    if (button.dataset.designerMode) setMode(button.dataset.designerMode);
    if (button.dataset.propertyTab) setTab(button.dataset.propertyTab);
    if (button.hasAttribute('data-focus-workbench')) button.setAttribute('aria-pressed', String(document.body.classList.toggle('designer-focused')));
    if (button.matches('[data-add-card],[data-card-up],[data-card-down],[data-card-delete]')) { changed(); if (button.matches('[data-add-card]')) select(panels().at(-1)); }
    for (const [attr, cls] of [['data-toggle-navigator','is-nav-hidden'],['data-toggle-properties','is-properties-hidden']]) if (button.hasAttribute(attr)) button.setAttribute('aria-expanded', String(!bench.classList.toggle(cls)));
  });
  editor.querySelector('.designer-property-tabs').addEventListener('keydown', event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault(); const tabs = [...editor.querySelectorAll('[data-property-tab]')], index = tabs.indexOf(document.activeElement);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    setTab(tabs[next].dataset.propertyTab); tabs[next].focus();
  });
  editor.addEventListener('invalid', event => { const panel = event.target.closest('[data-report-card]'); if (panel) { bench.classList.remove('is-properties-hidden'); setTab(propertyGroup(event.target.name.split('-').slice(2).join('-'))); select(panel); } else settings.open = true; }, true);
  widthControl.addEventListener('change', resizeCanvas); zoomControl.addEventListener('change', resizeCanvas);
  matchMedia('(max-width:1100px)').addEventListener('change', event => {
    if (event.matches) { document.body.classList.remove('designer-focused'); editor.querySelector('[data-focus-workbench]').setAttribute('aria-pressed','false'); }
  });
  editor.querySelector('[data-refresh-canvas]').addEventListener('click', refresh);
  window.addEventListener('pagehide', () => { controller?.abort(); clearTimeout(timer); bridgeControllers.forEach(c => c.abort()); });
  sync(); setTab('data'); resizeCanvas(); refresh();
  const invalidPanel = panels().find(panel => panel.querySelector('.errorlist'));
  if (invalidPanel) {
    const invalidField = invalidPanel.querySelector('.errorlist')?.closest('.report-field')?.querySelector('[name]');
    if (invalidField) setTab(propertyGroup(invalidField.name.split('-').slice(2).join('-')));
    select(invalidPanel);
  }
  if (window.innerWidth > 1100 && !editor.querySelector('.errorlist')) editor.querySelector('[data-focus-workbench]').click();
})();
