(() => {
  const controls = document.querySelector('[data-order-sort]');
  if (!controls) return;
  document.querySelectorAll('[data-order-sort-key], [data-sort-clear]').forEach(link => {
    link.addEventListener('click', event => {
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
      location.assign(url.toString());
    });
  });
})();
