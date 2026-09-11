(() => {
  const form = document.querySelector('[data-access-form]');
  if (!form) return;
  const rows = [...form.querySelectorAll('[data-access-row]')];
  const search = document.querySelector('[data-access-search]');
  const filter = document.querySelector('[data-access-filter]');
  let dirty = false;
  function refresh() {
    for (const row of rows) {
      const checks = [...row.querySelectorAll('input[type="checkbox"]')];
      const changed = checks.some(input => input.checked !== (input.dataset.before === '1'));
      row.classList.toggle('is-changed', changed);
      row.hidden = !row.dataset.label.toLowerCase().includes(search.value.trim().toLowerCase()) ||
        (filter.value === 'selected' && !checks.some(input => input.checked)) || (filter.value === 'changed' && !changed);
    }
  }
  form.addEventListener('change', event => {
    const input = event.target;
    if (!input.matches('input[type="checkbox"]')) return;
    const row = input.closest('[data-access-row]');
    const view = row.querySelector('[data-action="view"]');
    if (input === view && !view.checked) row.querySelectorAll('input[type="checkbox"]').forEach(box => { box.checked = false; });
    else if (input.checked) view.checked = true;
    dirty = true;
    refresh();
  });
  search.addEventListener('input', refresh);
  filter.addEventListener('change', refresh);
  document.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  refresh();
})();
