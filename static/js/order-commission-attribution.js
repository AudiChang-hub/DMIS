(() => {
  const form = document.querySelector('[data-commission-attribution-form]');
  if (!form) return;
  const editor = form.closest('details');
  const cancel = form.querySelector('[data-cancel-attribution]');
  const select = form.querySelector('select');
  document.querySelector('[data-open-attribution]')?.addEventListener('click', (event) => {
    event.preventDefault();
    editor.open = true;
    editor.scrollIntoView({behavior: 'instant', block: 'start'});
    (form.querySelector('.searchable-select__input') || select).focus({preventScroll: true});
  });
  cancel.hidden = false;
  cancel.addEventListener('click', () => {
    form.reset();
    select.dispatchEvent(new Event('change', {bubbles: true}));
    editor.open = false;
    editor.querySelector('summary').focus({preventScroll: true});
  });
  form.addEventListener('invalid', () => { editor.open = true; }, true);
})();
