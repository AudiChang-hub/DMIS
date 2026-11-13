/* 單一正式畫布 + 保留原驗證表單；預覽資料不落地。 */
function designerScale(mode, width, height, availableWidth, availableHeight) {
  if (mode === 'fit') return Math.min(1, Math.max(0.1, availableWidth / width));
  if (mode === 'page') return Math.min(1, Math.max(0.05, Math.min(availableWidth / width, availableHeight / height)));
  return Math.max(0.1, Math.min(2, Number(mode) || 1));
}
/* T-164「自動」：電腦上至少用 1180 px 排版（與讀者桌機看到的雙欄一致），畫布夠寬時直接以實際大小顯示；
   手機等窄畫面直接以實際寬度顯示手機版面，不把桌機版面縮到看不清楚。 */
const DESIGNER_DESKTOP_WIDTH = 1180, DESIGNER_NARROW_WIDTH = 700;
function designerCanvasWidth(choice, availableWidth) {
  const target = Number(choice);
  if (Number.isFinite(target) && target > 0) return target;
  const available = Math.max(320, Math.round(availableWidth));
  return available < DESIGNER_NARROW_WIDTH ? available : Math.max(DESIGNER_DESKTOP_WIDTH, available);
}
/* 條件標籤文字：最多列 3 項，其餘以「等 N 項」摘要，與報表頁「目前篩選」一致。 */
function designerChipText(values) {
  const list = values.filter(Boolean);
  return list.length > 3 ? `${list.slice(0, 3).join('、')} 等 ${list.length} 項` : list.join('、');
}
if (typeof module !== 'undefined') module.exports = {designerScale, designerCanvasWidth, designerChipText};
if (typeof document !== 'undefined') (() => {
  'use strict';
  const editor = document.querySelector('[data-report-editor]');
  if (!editor) return;
  document.body.classList.add('report-designer-shell');
  const bench = editor.querySelector('[data-workbench]'), forms = editor.querySelector('[data-report-cards]');
  const canvas = editor.querySelector('[data-design-canvas]'), viewport = canvas.parentElement;
  const status = editor.querySelector('[data-canvas-status]'), chartSwitch = editor.querySelector('[data-chart-switch]');
  const widthControl = editor.querySelector('[data-canvas-width]'), zoomLabel = editor.querySelector('[data-zoom-label]');
  const settings = editor.querySelector('[data-more-settings]'), scopeDialog = editor.querySelector('[data-scope-dialog]');
  const interactionHelp = editor.querySelector('[data-interaction-help]');
  const frame = document.createElement('iframe'); frame.title = '完整報表畫布（尚未發布）';
  frame.setAttribute('sandbox', 'allow-scripts allow-downloads allow-modals'); canvas.append(frame);
  const panels = () => [...forms.querySelectorAll('[data-report-card]')].filter(el => !el.hidden);
  const field = (panel, name) => panel?.querySelector(`[name$="-${name}"]`);
  let selected, mode = 'edit', channel = '', snapshot, controller, timer;
  let sequence = 0, generation = 0, height = 900;
  const bridgeControllers = new Set(), bridgeRequests = new Map();
  bench.hidden = false;
  function send(type, extra = {}) { frame.contentWindow?.postMessage({channel, type, ...extra}, '*'); }
  function resizeCanvas() {
    const available = viewport.clientWidth - 32;
    const width = designerCanvasWidth(widthControl.value, available);
    const scale = designerScale('fit', width, height, available, viewport.clientHeight - 32);
    frame.style.width = `${width}px`; frame.style.height = `${height}px`; frame.style.transform = `scale(${scale})`;
    canvas.style.width = `${width * scale}px`; canvas.style.height = `${height * scale}px`;
    zoomLabel.hidden = scale >= 0.995; zoomLabel.textContent = `顯示比例 ${Math.round(scale * 100)}%`;
  }
  new ResizeObserver(resizeCanvas).observe(viewport);

  /* ── 條件標籤：「這份報表只算」與「這張圖另外只算」 ───────────────── */
  function scopeEntries(container) {
    return [...container.querySelectorAll('.report-field')].map(wrapper => {
      const label = wrapper.querySelector(':scope>label')?.textContent.trim() || '';
      const boxes = [...wrapper.querySelectorAll('input[type="checkbox"]')];
      const text = wrapper.querySelector('textarea');
      const values = text ? text.value.split('\n').map(line => line.trim()).filter(Boolean)
        : boxes.filter(box => box.checked).map(box => box.closest('label')?.querySelector('span')?.textContent.trim() || box.value);
      const clear = () => {
        if (text) { text.value = ''; text.dispatchEvent(new Event('input', {bubbles:true})); text.dispatchEvent(new Event('change', {bubbles:true})); return; }
        boxes.forEach(box => { box.checked = false; });
        boxes[0]?.dispatchEvent(new Event('change', {bubbles:true}));
      };
      return {label: label.replace(/（[^）]*）$/, ''), values, clear};
    }).filter(entry => entry.values.length);
  }
  function renderChips(target, container) {
    if (!target || !container) return;
    const entries = scopeEntries(container);
    target.replaceChildren();
    if (!entries.length) {
      const empty = document.createElement('span'); empty.className = 'designer-chips__empty'; empty.textContent = target.dataset.emptyText || '不限';
      target.append(empty); return;
    }
    entries.forEach(entry => {
      const chip = document.createElement('span'); chip.className = 'designer-chip';
      const name = document.createElement('span'); name.className = 'designer-chip__label'; name.textContent = entry.label;
      const value = document.createElement('span'); value.className = 'designer-chip__value'; value.textContent = designerChipText(entry.values);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'designer-chip__remove';
      remove.setAttribute('aria-label', `移除「${entry.label}」條件`); remove.textContent = '×';
      remove.addEventListener('click', () => { entry.clear(); });
      chip.append(name, value, remove); target.append(chip);
    });
  }
  let chipFrame = 0;
  function refreshChips() {
    cancelAnimationFrame(chipFrame);
    chipFrame = requestAnimationFrame(() => {
      renderChips(editor.querySelector('[data-scope-chips]'), scopeDialog);
      panels().forEach(panel => renderChips(panel.querySelector('[data-card-scope-chips]'), panel.querySelector('.report-card-scope')));
    });
  }
  function openScope() {
    if (!scopeDialog.open) scopeDialog.showModal();
    scopeDialog.querySelector('summary, input, select, textarea')?.focus();
  }
  editor.querySelector('[data-open-scope]')?.addEventListener('click', openScope);
  chartSwitch.addEventListener('change', () => { const index = Number(chartSwitch.value); select(panels()[index]); send('reveal', {index}); });
  scopeDialog.addEventListener('click', event => {
    if (event.target === scopeDialog || event.target.closest('[data-close-scope]')) scopeDialog.close();
  });
  scopeDialog.addEventListener('close', () => editor.querySelector('[data-open-scope]')?.focus());

  /* 只對大數據分析群組顯示「依勾選車型各一張圖」；已勾選的舊設定照樣顯示，避免看不到卻被送出。 */
  function syncPerModel() {
    const analysis = editor.querySelector('[name="navigation_group"]')?.value === 'analysis';
    forms.querySelectorAll('[name$="-per_model"]').forEach(input => {
      const wrapper = input.closest('.report-field'); if (wrapper) wrapper.hidden = !analysis && !input.checked;
    });
  }

  /* 依什麼分／再細分選到「車種類別」時，提示類別在哪裡管理。 */
  function syncHints() {
    panels().forEach(panel => {
      const hint = panel.querySelector('[data-motor-type-hint]');
      if (hint) hint.hidden = ![field(panel, 'dimension'), field(panel, 'series')].some(input => input?.value === 'legacy_motor_type');
    });
  }

  function select(panel) {
    selected = panel;
    panels().forEach(item => { item.dataset.selected = String(item === panel); });
    chartSwitch.value = String(panels().indexOf(panel));
    send('state', {mode, selected: panels().indexOf(selected)});
  }
  function sync() {
    // 圖表切換：畫布上點圖表即可選取，這裡提供鍵盤與總覽用的清單。
    chartSwitch.replaceChildren(...panels().map((panel, index) => {
      const chart = field(panel, 'chart')?.selectedOptions[0]?.text;
      return new Option(`圖表 ${index + 1}：${field(panel, 'title').value || '新圖表'}${chart ? `（${chart}）` : ''}`, String(index));
    }));
    select(panels().includes(selected) ? selected : panels()[0]);
    syncPerModel(); syncHints(); refreshChips();
  }
  function setMode(next) {
    mode = next;
    bench.dataset.mode = mode;
    editor.querySelectorAll('.designer-mode [data-designer-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.designerMode === mode)));
    editor.querySelector('[data-mode-help]').textContent = mode === 'edit' ? '點一下圖表，右側就會出現它的設定；拖曳圖表左上角的標籤可以排序，拖曳右下角可以調整大小。' : '這是讀者看到的樣子：可以滑入看數字、點選分類連動、查看明細及匯出，不會修改任何資料。';
    interactionHelp.hidden = mode !== 'preview';
    forms.hidden = mode === 'preview';
    send('state', {mode, selected: panels().indexOf(selected)});
  }
  async function requestPreview(body, signal) {
    const response = await fetch(editor.getAttribute('action') || location.href, {method:'POST', body, credentials:'same-origin', signal, busy:false});
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
    status.textContent = '正在更新預覽…'; status.dataset.state = 'busy'; canvas.setAttribute('aria-busy', 'true');
    const body = new FormData(editor); body.set('action', 'canvas'); body.set('preview_channel', nextChannel);
    try {
      const payload = await requestPreview(body, own.signal);
      if (id !== sequence || version !== generation) return;
      if (payload.status >= 400) throw new Error('報表設定或篩選無法預覽，請檢查後再試。');
      snapshot = body; channel = nextChannel; frame.srcdoc = payload.document;
      status.textContent = '預覽已是最新（尚未儲存）'; status.dataset.state = 'ready';
    } catch (error) { if (id === sequence && version === generation) { status.textContent = `預覽未更新：${error.name === 'AbortError' ? '查詢逾時，請按「重新整理預覽」。' : error.message}`; status.dataset.state = 'error'; } }
    finally { clearTimeout(timeout); if (id === sequence) canvas.setAttribute('aria-busy', 'false'); }
  }
  function changed() {
    generation++; controller?.abort(); sync(); status.textContent = '設定已變更，馬上更新預覽…'; status.dataset.state = 'busy';
    clearTimeout(timer); timer = setTimeout(refresh, 650);
  }
  window.addEventListener('message', async event => {
    const msg = event.data;
    if (event.source !== frame.contentWindow || !msg || msg.channel !== channel || !channel) return;
    if (msg.type === 'ready') send('state', {mode, selected: panels().indexOf(selected)});
    if (msg.type === 'notice' && typeof msg.message === 'string') status.textContent = msg.message;
    if (msg.type === 'cancel') bridgeRequests.get(msg.id)?.abort();
    if (msg.type === 'height' && Number.isFinite(msg.height)) { height = Math.max(300, Math.min(100000, msg.height)); resizeCanvas(); }
    if (msg.type === 'select' && Number.isInteger(msg.index)) { select(panels()[msg.index]); forms.closest('.report-property-panel').scrollTop = 0; }
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
    if (button.hasAttribute('data-focus-workbench')) button.setAttribute('aria-pressed', String(document.body.classList.toggle('designer-focused')));
    if (button.matches('[data-add-card],[data-card-up],[data-card-down],[data-card-delete]')) { changed(); if (button.matches('[data-add-card]')) select(panels().at(-1)); }
  });
  editor.addEventListener('invalid', event => {
    const target = event.target;
    if (scopeDialog.contains(target)) { target.closest('details')?.setAttribute('open', ''); openScope(); return; }
    const panel = target.closest('[data-report-card]');
    if (panel) { setMode('edit'); target.closest('details')?.setAttribute('open', ''); select(panel); }
    else if (settings.contains(target)) settings.open = true;
  }, true);
  widthControl.addEventListener('change', resizeCanvas);
  matchMedia('(max-width:1100px)').addEventListener('change', event => {
    if (event.matches) { document.body.classList.remove('designer-focused'); editor.querySelector('[data-focus-workbench]').setAttribute('aria-pressed','false'); }
  });
  editor.querySelector('[data-refresh-canvas]').addEventListener('click', refresh);
  window.addEventListener('pagehide', () => { controller?.abort(); clearTimeout(timer); bridgeControllers.forEach(c => c.abort()); });
  sync(); setMode('edit'); resizeCanvas(); refresh();
  // 伺服器驗證失敗時，直接打開出錯的位置。
  if (scopeDialog.querySelector('.errorlist')) { scopeDialog.querySelectorAll('details').forEach(item => { if (item.querySelector('.errorlist')) item.open = true; }); openScope(); }
  if (settings.querySelector('.errorlist')) settings.open = true;
  const invalidPanel = panels().find(panel => panel.querySelector('.errorlist'));
  if (invalidPanel) { invalidPanel.querySelectorAll('details').forEach(item => { if (item.querySelector('.errorlist')) item.open = true; }); select(invalidPanel); }
})();
