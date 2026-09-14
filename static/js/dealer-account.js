(() => {
  const form = document.querySelector('[data-dealer-account]');
  if (!form) return;
  form.querySelector('[data-suggest-username]')?.addEventListener('click', event => {
    const input = form.querySelector('[data-dealer-username]');
    input.value = event.currentTarget.dataset.suggestUsername;
    input.focus();
  });
  form.querySelectorAll('[data-feature-all]').forEach(button => button.addEventListener('click', () => {
    button.closest('[data-feature-group]').querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = button.dataset.featureAll === '1'; });
  }));
  const submit = form.querySelector('[name="can_submit_orders"]');
  const view = form.querySelector('[name="can_view_orders"]');
  submit.addEventListener('change', () => { if (submit.checked) view.checked = true; });
  view.addEventListener('change', () => { if (!view.checked) submit.checked = false; });
})();
