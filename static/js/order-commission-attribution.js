(() => {
  const editor = document.querySelector('.commission-attribution__editor');
  if (!editor) return;
  const summary = editor.querySelector('summary');
  const form = editor.querySelector('[data-commission-attribution-form]');
  // 頁首右上角的浮層（使用者 2026-10-20、10-21）：Esc 或點浮層外關閉；歸屬表單有修改或提示時不自動收起。
  // 訂單來源兩欄屬於下方訂單表單，改了即自動儲存，收起浮層不影響。
  // 手機版（T-254）小卡收成一行小字、看不到小卡上的「變更車行」，焦點改回到頂端區塊的「變更車行」。
  const opener = () => (summary.getClientRects().length ? summary : document.querySelector('[data-compact-change]') || summary);
  const close = (restoreFocus) => {
    editor.open = false;
    if (restoreFocus) opener().focus({preventScroll: true});
  };
  let edited = false;
  const dirty = () => edited || Boolean(form?.querySelector('.note-box'));
  if (form) {
    const cancel = form.querySelector('[data-cancel-attribution]');
    const select = form.querySelector('select');
    form.addEventListener('input', () => { edited = true; });
    form.addEventListener('change', (event) => { if (event.isTrusted) edited = true; });
    cancel.hidden = false;
    cancel.addEventListener('click', () => {
      form.reset();
      select.dispatchEvent(new Event('change', {bubbles: true}));
      edited = false;
      close(true);
    });
    form.addEventListener('invalid', () => { editor.open = true; }, true);
  }
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && editor.open) close(true);
  });
  document.addEventListener('click', (event) => {
    // 頂端區塊的「變更車行」是打開浮層的入口（order-compact-bar.js），同一下點擊不能又把它關掉（T-254）。
    if (event.target.closest?.('[data-compact-change]')) return;
    if (editor.open && !editor.contains(event.target) && event.target.isConnected && !dirty()) close(false);
  });
  // 小卡上的來源摘要跟著選擇即時更新（實際儲存由訂單自動儲存處理）。
  const sourceType = document.getElementById('id_source_type');
  const source = document.getElementById('id_source');
  const summaryText = document.querySelector('[data-source-summary]');
  const refreshSummary = () => {
    if (!summaryText || !sourceType) return;
    const typeLabel = sourceType.selectedOptions[0]?.text || '';
    const name = source && source.value ? source.selectedOptions[0]?.text : '';
    // 與伺服器顯示一致：歸屬小卡寫「本店／承辦人」或車行名稱；網路平台寫「網路平台／平台名稱」。
    if (summaryText.dataset.sourceSummary === 'attribution' && sourceType.value !== 'store') {
      summaryText.textContent = name || '未設定';
    } else {
      summaryText.textContent = name ? `${typeLabel}／${name}` : typeLabel;
    }
  };
  [sourceType, source].forEach((field) => field?.addEventListener('change', refreshSummary));
})();
