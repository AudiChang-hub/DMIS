(() => {
  const form = document.querySelector('[data-bonus-rule-form]');
  if (!form) return;
  const rows = form.querySelector('[data-bonus-tiers]');
  const total = form.querySelector('[name="tiers-TOTAL_FORMS"]');
  const template = form.querySelector('[data-bonus-tier-template]');
  const status = form.querySelector('[data-bonus-tier-status]');
  const update = message => {
    const count = [...rows.querySelectorAll('[data-bonus-tier]')].filter(row => !row.hidden).length;
    status.textContent = `${message}目前 ${count} 段門檻。`;
  };
  const remove = row => {
    row.querySelector('[name$="-DELETE"]').checked = true;
    row.querySelectorAll('input:not([name$="-DELETE"]):not([type="hidden"])').forEach(input => { input.disabled = true; });
    row.hidden = true;
  };
  rows.querySelectorAll('[data-bonus-tier][hidden]').forEach(remove);
  form.querySelector('[data-add-bonus-tier]').addEventListener('click', () => {
    const index = Number(total.value);
    if (!Number.isInteger(index) || index >= 1000) return;
    const fragment = document.createElement('template');
    fragment.innerHTML = template.innerHTML.replaceAll('__prefix__', String(index));
    rows.append(fragment.content);
    total.value = String(index + 1);
    update('已新增。');
    rows.lastElementChild.querySelector('input[type="number"]').focus({preventScroll: true});
  });
  rows.addEventListener('click', event => {
    const button = event.target.closest('[data-remove-bonus-tier]');
    if (!button) return;
    remove(button.closest('[data-bonus-tier]'));
    update('已移除，儲存規則後生效。');
  });
  update('');
})();
