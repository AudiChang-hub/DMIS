// 匯出訂單（T-232）：群組全選／清除、已選欄數、改了欄位就要重新預覽才能匯出。
// 每次打開都從預設欄位（＝舊「匯出營運資料」那組，Q9）開始，不記上次的選擇。
(function () {
  const form = document.querySelector('[data-order-export]');
  if (!form) return;
  const boxes = () => Array.from(form.querySelectorAll('input[type=checkbox][name=cols]:not(:disabled)'));
  const chosen = () => boxes().filter((box) => box.checked).map((box) => box.value);
  const required = Array.from(form.querySelectorAll('input[type=hidden][name=cols]')).map((input) => input.value);
  const count = form.querySelector('[data-selected-count]');
  const preview = document.querySelector('[data-previewed]');
  const download = document.querySelector('[data-download-button]');
  const staleNote = document.querySelector('[data-stale-note]');
  const hint = form.querySelector('[data-savebar-hint]');
  const defaults = boxes().filter((box) => box.defaultChecked).map((box) => box.value);

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
  // 換分類就重新載入範圍：已預覽過就連預覽一起更新，還沒預覽就只更新張數。
  const scopeTab = document.querySelector('[data-scope-tab]');
  if (scopeTab) {
    scopeTab.addEventListener('change', () => {
      const previewFlag = form.querySelector('input[name=preview]');
      if (previewFlag) previewFlag.disabled = !preview;
      form.submit();
    });
  }

  form.addEventListener('submit', (event) => {
    if (!chosen().length && !required.length) event.preventDefault();
  });

  // 按「預覽」後網址帶 #preview：直接停在預覽表格，不慢慢捲過整串欄位（全站 html 是 smooth，瞬間定位要寫 instant）。
  if (preview && window.location.hash === '#preview') {
    if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';
    window.addEventListener('load', () => preview.scrollIntoView({ behavior: 'instant', block: 'start' }), { once: true });
  }
  refresh();
})();
