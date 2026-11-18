// 匯出訂單（T-232）：群組全選／清除、已選欄數、上次選擇（只存本機）、改了欄位就要重新預覽才能匯出。
(function () {
  const form = document.querySelector('[data-order-export]');
  if (!form) return;
  const STORAGE_KEY = 'dmis.orderExport.columns';
  const boxes = () => Array.from(form.querySelectorAll('input[type=checkbox][name=cols]:not(:disabled)'));
  const chosen = () => boxes().filter((box) => box.checked).map((box) => box.value);
  const required = Array.from(form.querySelectorAll('input[type=hidden][name=cols]')).map((input) => input.value);
  const count = form.querySelector('[data-selected-count]');
  const preview = document.querySelector('[data-previewed]');
  const download = document.querySelector('[data-download-button]');
  const staleNote = document.querySelector('[data-stale-note]');
  const hint = form.querySelector('[data-savebar-hint]');
  const defaults = boxes().filter((box) => box.defaultChecked).map((box) => box.value);

  function remember(keys) {
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(keys)); } catch (error) { /* 私密視窗等情況不記也沒關係 */ }
  }
  function recall() {
    try { return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null'); } catch (error) { return null; }
  }

  function refresh() {
    const keys = chosen();
    if (count) count.textContent = String(new Set([...required, ...keys]).size);
    if (!preview || !download) return;
    const previewed = preview.dataset.previewed.split(',').filter(Boolean).sort().join(',');
    const now = [...new Set([...required, ...keys])].sort().join(',');
    const stale = previewed !== now;
    if (!download.dataset.blocked) download.dataset.blocked = download.disabled ? '1' : '0';
    download.disabled = stale || download.dataset.blocked === '1';
    if (staleNote) staleNote.hidden = !stale;
    if (hint) hint.textContent = stale ? '欄位已變更，請按「預覽」重新預覽後再匯出。' : '已預覽；改了欄位要重新預覽才能匯出。';
  }

  // 沒帶欄位進來（第一次打開）時，套用這台電腦上次的選擇。
  if (!new URLSearchParams(window.location.search).has('cols')) {
    const saved = recall();
    if (Array.isArray(saved) && saved.length) {
      boxes().forEach((box) => { box.checked = saved.includes(box.value); });
    }
  }

  form.addEventListener('change', (event) => {
    if (event.target.matches('input[name=cols]')) refresh();
  });
  form.addEventListener('click', (event) => {
    const all = event.target.closest('[data-group-all]');
    const none = event.target.closest('[data-group-none]');
    if (all || none) {
      const group = event.target.closest('[data-export-group]');
      group.querySelectorAll('input[type=checkbox][name=cols]:not(:disabled)').forEach((box) => { box.checked = Boolean(all); });
      refresh();
    }
    if (event.target.closest('[data-reset-default]')) {
      boxes().forEach((box) => { box.checked = defaults.includes(box.value); });
      refresh();
    }
  });
  form.addEventListener('submit', (event) => {
    if (!chosen().length && !required.length) {
      event.preventDefault();
      return;
    }
    remember(chosen());
  });

  // 按「預覽」後網址帶 #preview：直接停在預覽表格，不慢慢捲過整串欄位（全站 html 是 smooth，瞬間定位要寫 instant）。
  if (preview && window.location.hash === '#preview') {
    if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';
    window.addEventListener('load', () => preview.scrollIntoView({ behavior: 'instant', block: 'start' }), { once: true });
  }
  refresh();
})();
