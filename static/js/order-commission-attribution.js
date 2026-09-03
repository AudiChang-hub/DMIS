(() => {
  const form = document.querySelector('[data-commission-attribution-form]');
  if (!form) return;
  const editor = form.closest('details');
  const cancel = form.querySelector('[data-cancel-attribution]');
  const select = form.querySelector('select');
  cancel.hidden = false;
  cancel.addEventListener('click', () => {
    form.reset();
    select.dispatchEvent(new Event('change', {bubbles: true}));
    editor.open = false;
    editor.querySelector('summary').focus({preventScroll: true});
  });
  form.addEventListener('invalid', () => { editor.open = true; }, true);
})();
