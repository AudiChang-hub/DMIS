(() => {
  // 以事件委派處理排序連結：頁籤局部替換列表後，新的排序連結也能使用。
  document.addEventListener('click', event => {
    const link = event.target.closest('[data-order-sort-key], [data-sort-clear]');
    const controls = document.querySelector('[data-order-sort]');
    if (!link || !controls) return;
    if (event.ctrlKey || event.metaKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    const key = link.dataset.orderSortKey;
    const current = controls.dataset.orderSort.split(',').filter(Boolean);
    const existing = current.find(token => token.replace(/^-/, '') === key);
    const next = existing === key ? '-' + key : key;
    let tokens = [];
    if (key) {
      tokens = existing ? current.map(token => token === existing ? next : token) : [...current, next];
    }
    const url = new URL(location.href);
    url.searchParams.delete('page');
    if (tokens.length) url.searchParams.set('sort', tokens.join(','));
    else url.searchParams.delete('sort');
    // 全部訂單有局部載入（order-tabs.js）時不整頁重新載入、不跳回頁首。
    if (globalThis.DMISOrderResults) globalThis.DMISOrderResults.load(url.toString());
    else location.assign(url.toString());
  });
})();
