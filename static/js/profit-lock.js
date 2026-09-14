(() => {
  const until = Number(document.body.dataset.profitUntil || 0);
  if (!until) return;
  const mask = () => {
    if (Date.now() < until) return;
    document.querySelectorAll('[data-profit-value]').forEach(el => el.replaceChildren(document.createTextNode('已鎖定')));
    document.querySelectorAll('[data-order-sort-key="profit"]').forEach(el => {
      el.removeAttribute('href'); el.removeAttribute('data-order-sort-key'); el.textContent = '淨利 · 解鎖後可排序';
    });
    document.querySelectorAll('.profit-control[data-profit-until]').forEach(el => {
      const message = document.createElement('span'); message.textContent = '淨利已到期鎖定；未儲存的表單內容仍保留。';
      const link = document.createElement('a'); link.textContent = '重新解鎖'; link.className = 'button ghost small';
      link.href = '/account/profit/unlock/?next=' + encodeURIComponent(location.pathname + location.search);
      el.replaceChildren(message, link);
    });
  };
  setTimeout(mask, Math.max(0, until - Date.now()));
  document.addEventListener('visibilitychange', mask);
  window.addEventListener('pageshow', mask);
})();
