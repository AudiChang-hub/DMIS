(() => {
  const periodRange = (type, year, period) => {
    year = Number(year); period = Number(period);
    if (!['month', 'quarter'].includes(type) || !Number.isInteger(year) || year < 1900 || year > 9999 || !Number.isInteger(period) || period < 1 || period > (type === 'month' ? 12 : 4)) return null;
    const first = type === 'month' ? period : (period - 1) * 3 + 1;
    const last = type === 'month' ? first : first + 2;
    const pad = value => String(value).padStart(2, '0');
    return [`${year}-${pad(first)}-01`, `${year}-${pad(last)}-${pad(new Date(Date.UTC(year, last, 0)).getUTCDate())}`];
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = {periodRange};
  if (typeof document === 'undefined') return;
  const form = document.querySelector('[data-bonus-rule-form]');
  if (!form) return;
  const year = form.querySelector('[name="period_year"]');
  const month = form.querySelector('[name="period_month"]');
  const quarter = form.querySelector('[name="period_quarter"]');
  const starts = form.querySelector('[name="starts_on"]');
  const ends = form.querySelector('[name="ends_on"]');
  const summary = form.querySelector('[data-period-summary]');
  const updatePeriod = () => {
    const type = form.querySelector('[name="period_type"]:checked')?.value || 'custom';
    const custom = type === 'custom';
    form.querySelector('[data-period-presets]').hidden = custom;
    form.querySelector('[data-period-custom]').hidden = !custom;
    form.querySelector('[data-period-month]').hidden = type !== 'month';
    form.querySelector('[data-period-quarter]').hidden = type !== 'quarter';
    year.disabled = custom; month.disabled = type !== 'month'; quarter.disabled = type !== 'quarter';
    starts.required = ends.required = custom;
    year.required = !custom; month.required = type === 'month'; quarter.required = type === 'quarter';
    if (!custom) {
      const range = periodRange(type, year.value, type === 'month' ? month.value : quarter.value);
      if (!range) { starts.value = ends.value = ''; summary.textContent = '請選擇完整的年份與月份／季度。'; return; }
      [starts.value, ends.value] = range;
    }
    summary.textContent = starts.value && ends.value ? `統計期間：${starts.value.replaceAll('-', '/')} ～ ${ends.value.replaceAll('-', '/')}（含首尾日）` : '請填寫完整的自訂期間。';
  };
  [year, month, quarter, starts, ends, ...form.querySelectorAll('[name="period_type"]')].forEach(field => field.addEventListener('change', updatePeriod));
  year.addEventListener('input', updatePeriod);
  updatePeriod();
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
