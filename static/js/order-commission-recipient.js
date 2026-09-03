(() => {
  const root = document.querySelector('[data-order-credit]');
  if (!root) return;
  const sourceType = document.getElementById('id_source_type');
  const source = document.getElementById('id_source');
  const enabled = root.querySelector('[name="assign_commission_to_other"]');
  const select = root.querySelector('select[name="commission_recipient"]');
  const toggle = root.querySelector('[data-credit-toggle]');
  const panel = root.querySelector('[data-credit-panel]');
  const summary = root.querySelector('[data-credit-summary]');
  const isEnabled = () => /^(true|1|on)$/i.test(enabled.value);
  const sync = () => {
    const isDealer = sourceType.value === 'dealer';
    const eligible = isDealer || sourceType.value === 'store';
    root.hidden = !eligible;
    if (!select) return; // 已結算：只顯示固定歸屬。
    const expanded = eligible && isEnabled();
    panel.hidden = !expanded;
    select.disabled = !expanded;
    select.required = expanded;
    toggle.setAttribute('aria-expanded', String(expanded));
    toggle.textContent = expanded ? (isDealer ? '取消指定，改回原車行' : '取消指定車行') : '＋ 這台算給其他車行';
    const chosen = select.selectedOptions[0];
    summary.textContent = select.value && chosen
      ? (isDealer ? `這台的台數、基礎傭金與台數獎金 → ${chosen.textContent.trim()}` : `台數與台數獎金 → ${chosen.textContent.trim()}；本店來源不變，不新增基礎傭金。`) : '請選擇這台算給哪間車行。';
  };
  toggle?.addEventListener('click', () => {
    enabled.value = isEnabled() ? 'False' : 'True';
    if (!isEnabled()) {
      select.value = '';
      select.dispatchEvent(new Event('change', {bubbles: true}));
    }
    sync();
    enabled.dispatchEvent(new Event('change', {bubbles: true}));
    if (isEnabled()) {
      // 搜尋選單會在 MutationObserver 中同步 disabled，待同步後再聚焦。
      requestAnimationFrame(() => {
        const input = root.querySelector('.searchable-select__input') || select;
        input.focus({preventScroll: true});
      });
    }
  });
  sourceType.addEventListener('change', () => {
    if (!['dealer', 'store'].includes(sourceType.value) && select) {
      enabled.value = 'False';
      select.value = '';
      select.dispatchEvent(new Event('change', {bubbles: true}));
      enabled.dispatchEvent(new Event('change', {bubbles: true}));
    }
    sync();
  });
  source.addEventListener('change', sync);
  select?.addEventListener('change', sync);
  window.addEventListener('pageshow', sync);
  sync();
})();
