/* 收入與支出：即時小計、來源標籤與車行結算試算；只呈現，儲存仍走原表單。 */
(() => {
  const toAmount = raw => {
    const value = Number(String(raw ?? '').replace(/[,\s$]/g, ''));
    return Number.isFinite(value) ? Math.round(value) : 0;
  };
  const format = value => Math.abs(value).toLocaleString('zh-TW');
  if (typeof module !== 'undefined') module.exports = {toAmount};
  if (typeof document === 'undefined') return;
  const ledger = document.querySelector('[data-finance-ledger]');
  if (!ledger) return;
  const form = ledger.closest('form');
  const inputs = () => [...ledger.querySelectorAll('[data-ledger-input]')];
  let baseline = new Map(inputs().map(input => [input.name, toAmount(input.value)]));
  const sum = scope => [...scope.querySelectorAll('[data-ledger-input]')].reduce((total, input) => total + toAmount(input.value), 0);
  const setText = (nodes, value) => nodes.forEach(node => { node.textContent = format(value); });

  function settlement(commission) {
    document.querySelectorAll('[data-dealer-settlement]').forEach(card => {
      const total = toAmount(card.dataset.settlementBase) - commission;
      setText(card.querySelectorAll('[data-settlement-term="commission"]'), commission);
      const direction = total > 0 ? 'collect' : total < 0 ? 'pay' : 'none';
      card.classList.remove('is-collect', 'is-pay', 'is-none');
      card.classList.add(`is-${direction}`);
      const label = card.querySelector('[data-settlement-label]');
      if (label) label.textContent = {collect: '向車行收', pay: '付給車行', none: '無需收付'}[direction];
      const amount = card.querySelector('[data-settlement-amount]');
      if (amount) { amount.hidden = direction === 'none'; amount.textContent = `$${format(total)}`; }
    });
  }

  function refresh() {
    const totals = {};
    ledger.querySelectorAll('[data-ledger-block]').forEach(block => {
      const kind = block.dataset.ledgerBlock;
      totals[kind] = sum(block);
      block.querySelectorAll('[data-ledger-group]').forEach(group => {
        setText(group.querySelectorAll('[data-ledger-group-total]'), sum(group));
      });
      setText(block.querySelectorAll(`[data-ledger-total="${kind}"]`), totals[kind]);
    });
    const summary = document.querySelector('[data-finance-overview]');
    let dirty = false;
    inputs().forEach(input => {
      const changed = toAmount(input.value) !== baseline.get(input.name);
      dirty = dirty || changed;
      const row = input.closest('[data-ledger-row]');
      if (!row) return;
      row.classList.toggle('is-changed', changed);
      const tag = row.querySelector('[data-ledger-tag]');
      if (tag && row.dataset.ledgerSource === 'system') tag.textContent = changed ? '儲存後改為人工' : '系統帶入';
    });
    if (summary) {
      Object.entries(totals).forEach(([kind, value]) => setText(summary.querySelectorAll(`[data-ledger-summary="${kind}"]`), value));
      // 淨利只在已解鎖時由伺服器輸出；鎖定時頁面上沒有淨利節點可更新。
      const net = summary.querySelector('[data-ledger-net-card] [data-profit-value]');
      if (net && 'income' in totals && 'expense' in totals) {
        const value = totals.income - totals.expense;
        net.textContent = `$ ${value < 0 ? '-' : ''}${format(value)}`;
        net.classList.toggle('is-negative', value < 0);
      }
      const marker = summary.querySelector('[data-ledger-dirty]');
      if (marker) marker.hidden = !dirty;
    }
    const commission = ledger.querySelector('[name$="dealer_commission_expense"]');
    if (commission) settlement(toAmount(commission.value));
  }

  ledger.addEventListener('input', event => { if (event.target.matches('[data-ledger-input]')) refresh(); });
  ledger.addEventListener('change', event => { if (event.target.matches('[data-ledger-input]')) refresh(); });
  // 同頁儲存成功：伺服器已重繪總覽；已修改的「系統帶入」欄位依同一規則改標人工。
  form?.addEventListener('workspace-saved', () => {
    inputs().forEach(input => {
      const row = input.closest('[data-ledger-row]');
      const tag = row?.querySelector('[data-ledger-tag]');
      if (row?.dataset.ledgerSource === 'system' && toAmount(input.value) !== baseline.get(input.name)) {
        row.dataset.ledgerSource = 'manual';
        if (tag) { tag.textContent = '已人工調整'; tag.className = 'ledger-tag ledger-tag--manual'; }
      }
    });
    baseline = new Map(inputs().map(input => [input.name, toAmount(input.value)]));
    refresh();
  });
  refresh();
})();
