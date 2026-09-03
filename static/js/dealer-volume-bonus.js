(() => {
  const periodRange = (type, year, period) => {
    year = Number(year); period = Number(period);
    if (!['month', 'quarter'].includes(type) || !Number.isInteger(year) || year < 1900 || year > 9999 || !Number.isInteger(period) || period < 1 || period > (type === 'month' ? 12 : 4)) return null;
    const first = type === 'month' ? period : (period - 1) * 3 + 1;
    const last = type === 'month' ? first : first + 2;
    const pad = value => String(value).padStart(2, '0');
    return [`${year}-${pad(first)}-01`, `${year}-${pad(last)}-${pad(new Date(Date.UTC(year, last, 0)).getUTCDate())}`];
  };
  const periodRanges = (type, year, selected) => [...new Set(selected.map(Number))].sort((a, b) => a - b).map(number => periodRange(type, year, number)).filter(Boolean);
  if (typeof module !== 'undefined' && module.exports) module.exports = {periodRange, periodRanges};
  if (typeof document === 'undefined') return;
  const form = document.querySelector('[data-bonus-rule-form]');
  if (!form) return;
  const year = form.querySelector('[name="period_year"]');
  const months = [...form.querySelectorAll('[name="period_months"]')];
  const quarters = [...form.querySelectorAll('[name="period_quarters"]')];
  const starts = form.querySelector('[name="starts_on"]');
  const ends = form.querySelector('[name="ends_on"]');
  const summary = form.querySelector('[data-period-summary]');
  const preview = form.querySelector('[data-period-preview]');
  const locked = form.hasAttribute('data-conditions-locked');
  const lockedValues = new Set(JSON.parse(form.querySelector('#bonus-locked-periods').textContent));
  if (locked) {
    const type = form.querySelector('[name="period_type"]:checked').value;
    (type === 'month' ? months : type === 'quarter' ? quarters : []).forEach(field => {
      if (!lockedValues.has(field.value)) return;
      field.dataset.periodLocked = '1';
      field.setAttribute('aria-disabled', 'true');
      const label = field.closest('label');
      label.classList.add('is-locked'); label.title = '已結算，不能取消';
      const hint = document.createElement('small'); hint.textContent = '已結算'; label.append(hint);
      field.addEventListener('click', event => event.preventDefault());
    });
  }
  const updatePeriod = () => {
    const type = form.querySelector('[name="period_type"]:checked')?.value || 'custom';
    const custom = type === 'custom';
    form.querySelector('[data-period-presets]').hidden = custom;
    form.querySelector('[data-period-custom]').hidden = !custom;
    form.querySelector('[data-period-month]').hidden = type !== 'month';
    form.querySelector('[data-period-quarter]').hidden = type !== 'quarter';
    year.disabled = custom || locked;
    months.forEach(field => { field.disabled = type !== 'month'; });
    quarters.forEach(field => { field.disabled = type !== 'quarter'; });
    starts.required = ends.required = custom && !locked;
    year.required = !custom && !locked;
    preview.replaceChildren();
    if (!custom) {
      const ranges = periodRanges(type, year.value, (type === 'month' ? months : quarters).filter(field => field.checked).map(field => field.value));
      if (!ranges.length) { if (!locked) starts.value = ends.value = ''; summary.textContent = '請至少選擇一個月份／季度，並填寫完整年份。'; return; }
      if (!locked) [starts.value, ends.value] = ranges[0];
      ranges.forEach(range => { const item = document.createElement('li'); item.textContent = range.map(value => value.replaceAll('-', '/')).join(' ～ '); preview.append(item); });
      summary.textContent = `已選 ${ranges.length} 個期間，各期獨立計算門檻與結算，不合併台數。`;
      return;
    }
    summary.textContent = starts.value && ends.value ? `統計期間：${starts.value.replaceAll('-', '/')} ～ ${ends.value.replaceAll('-', '/')}（含首尾日）` : '請填寫完整的自訂期間。';
  };
  [year, ...months, ...quarters, starts, ends, ...form.querySelectorAll('[name="period_type"]')].forEach(field => field.addEventListener('change', updatePeriod));
  form.querySelectorAll('[data-period-select-all], [data-period-clear]').forEach(button => button.addEventListener('click', () => {
    const name = button.dataset.periodSelectAll || button.dataset.periodClear;
    form.querySelectorAll(`[name="${name}"]:not(:disabled)`).forEach(field => { if (!field.dataset.periodLocked) field.checked = Boolean(button.dataset.periodSelectAll); });
    updatePeriod();
  }));
  year.addEventListener('input', updatePeriod);
  updatePeriod();
  if (locked) return;
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
