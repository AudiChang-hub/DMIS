(() => {
  // 原廠獎勵活動（T-161）：清單篩選自動套用、掃描既有訂單視窗、表單項目列、通路暫停提示與指定車行。

  // 篩選選了就自動套用（比照 T-142）：條件寫回網址，空值不寫。
  const paramsFrom = (form) => new URLSearchParams([...new FormData(form)].filter(([, value]) => String(value).trim() !== ''));

  function initFilters() {
    const form = document.querySelector('[data-campaign-filters]');
    const results = document.querySelector('[data-campaign-results]');
    if (!form || !results) return;
    let timer = null;
    let pending = null;
    async function load() {
      const url = new URL(location.pathname, location.href);
      url.search = paramsFrom(form).toString();
      pending?.abort();
      const controller = new AbortController();
      pending = controller;
      results.setAttribute('aria-busy', 'true');
      try {
        const response = await fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}, signal: controller.signal});
        if (!response.ok) throw new Error(String(response.status));
        results.innerHTML = await response.text();
        history.replaceState(null, '', url);
      } catch (error) {
        if (error.name !== 'AbortError') location.assign(url);
      } finally {
        if (pending === controller) results.removeAttribute('aria-busy');
      }
    }
    const schedule = (wait) => { clearTimeout(timer); timer = setTimeout(load, wait); };
    form.addEventListener('input', (event) => { if (event.target.type === 'search') schedule(350); });
    form.addEventListener('change', (event) => { if (event.target.tagName === 'SELECT') schedule(0); });
    form.addEventListener('submit', (event) => { event.preventDefault(); schedule(0); });
  }

  // 掃描既有訂單：讀取（GET 只讀）後在視窗中逐張勾選，送出才寫入。
  function initBackfill() {
    const dialog = document.querySelector('[data-backfill-dialog]');
    const body = dialog?.querySelector('[data-backfill-body]');
    if (!dialog || !body) return;
    const syncConfirm = (form) => {
      const flagged = form.querySelector('[data-backfill-row][data-flagged]:checked');
      if (flagged) form.dataset.confirm = form.dataset.flaggedConfirm;
      else delete form.dataset.confirm;
    };
    document.addEventListener('click', async (event) => {
      const opener = event.target.closest('[data-backfill-open]');
      if (opener) {
        body.innerHTML = '<p class="muted">掃描中…</p>';
        if (!dialog.open) dialog.showModal();
        try {
          const response = await fetch(opener.dataset.url, {headers: {'X-Requested-With': 'XMLHttpRequest'}});
          if (!response.ok) throw new Error(String(response.status));
          body.innerHTML = await response.text();
          const form = body.querySelector('[data-backfill-form]');
          if (form) syncConfirm(form);
          body.querySelector('h2')?.focus?.();
        } catch (_error) {
          body.innerHTML = '<p class="message error">掃描失敗，請稍後再試。</p><button type="button" class="button ghost" data-backfill-close>關閉</button>';
        }
        return;
      }
      if (event.target.closest('[data-backfill-close]')) dialog.close();
    });
    body.addEventListener('change', (event) => {
      const form = event.target.closest('[data-backfill-form]');
      if (!form) return;
      if (event.target.matches('[data-backfill-select-all]')) {
        form.querySelectorAll('[data-backfill-row]').forEach((box) => { box.checked = event.target.checked; });
      }
      syncConfirm(form);
    });
  }

  // 表單：項目列新增／移除、通路都不勾時提示暫停並在送出前確認、指定車行才顯示車行清單。
  function initForm() {
    const form = document.querySelector('[data-campaign-form]');
    if (!form) return;
    const rows = form.querySelector('[data-campaign-item-rows]');
    const template = form.querySelector('[data-campaign-item-template]');
    const total = form.querySelector('#id_items-TOTAL_FORMS');
    const bindRow = (row) => row.querySelector('[data-remove-campaign-item]')?.addEventListener('click', () => {
      const deletion = row.querySelector('[name$="-DELETE"]');
      if (deletion) deletion.checked = true;
      row.hidden = true;
    });
    rows?.querySelectorAll('[data-campaign-item-row]').forEach(bindRow);
    form.querySelector('[data-add-campaign-item]')?.addEventListener('click', () => {
      if (!rows || !template || !total) return;
      const index = Number(total.value);
      const wrapper = document.createElement('div');
      wrapper.innerHTML = template.innerHTML.replaceAll('__prefix__', index).trim();
      const row = wrapper.firstElementChild;
      rows.appendChild(row);
      total.value = index + 1;
      bindRow(row);
      row.querySelector('select')?.focus();
    });

    const sources = [...form.querySelectorAll('input[name="source_types"]')];
    const note = form.querySelector('[data-campaign-paused-note]');
    const syncPaused = () => {
      const paused = sources.length > 0 && !sources.some((input) => input.checked);
      if (note) note.hidden = !paused;
      if (paused) form.dataset.confirm = form.dataset.pausedConfirm;
      else delete form.dataset.confirm;
    };
    sources.forEach((input) => input.addEventListener('change', syncPaused));
    syncPaused();

    const modes = [...form.querySelectorAll('input[name="dealer_mode"]')];
    const picker = form.querySelector('[data-campaign-dealer-picker]');
    const syncDealers = () => {
      const selected = modes.find((input) => input.checked)?.value === 'selected';
      if (picker) picker.hidden = !selected;
    };
    modes.forEach((input) => input.addEventListener('change', syncDealers));
    syncDealers();
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {paramsFrom};
  if (typeof document === 'undefined') return;
  initFilters();
  initBackfill();
  initForm();
})();
