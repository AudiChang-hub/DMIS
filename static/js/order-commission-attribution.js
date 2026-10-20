(() => {
  const form = document.querySelector('[data-commission-attribution-form]');
  if (!form) return;
  const editor = form.closest('details');
  const summary = editor.querySelector('summary');
  const cancel = form.querySelector('[data-cancel-attribution]');
  const select = form.querySelector('select');
  // 頁首右上角的浮層（使用者 2026-10-20）：Esc 或點浮層外關閉；有提示或已改內容時不自動收起。
  const close = (restoreFocus) => {
    editor.open = false;
    if (restoreFocus) summary.focus({preventScroll: true});
  };
  let edited = false;
  form.addEventListener('input', () => { edited = true; });
  form.addEventListener('change', (event) => { if (event.isTrusted) edited = true; });
  const dirty = () => edited || Boolean(form.querySelector('.note-box'));
  cancel.hidden = false;
  cancel.addEventListener('click', () => {
    form.reset();
    select.dispatchEvent(new Event('change', {bubbles: true}));
    edited = false;
    close(true);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && editor.open) close(true);
  });
  document.addEventListener('click', (event) => {
    if (editor.open && !editor.contains(event.target) && !dirty()) close(false);
  });
  form.addEventListener('invalid', () => { editor.open = true; }, true);
})();
