/* 保留連結作為無 JS 後援；頁籤切換不發送請求。 */
document.querySelectorAll('[data-news-tabs]').forEach(nav => {
  const tabs = [...nav.querySelectorAll('a[data-panel]')];
  const show = tab => {
    tabs.forEach(item => {
      const active = item === tab;
      item.setAttribute('aria-selected', String(active));
      item.tabIndex = active ? 0 : -1;
      if (active) item.setAttribute('aria-current', 'page');
      else item.removeAttribute('aria-current');
      document.getElementById(item.dataset.panel).hidden = !active;
    });
  };
  nav.setAttribute('role', 'tablist');
  tabs.forEach(tab => {
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', tab.dataset.panel);
    const panel = document.getElementById(tab.dataset.panel);
    panel.setAttribute('role', 'tabpanel');
    panel.setAttribute('aria-labelledby', tab.id);
    tab.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      show(tab);
      const url = new URL(location.href);
      url.searchParams.set('news', tab.dataset.panel.replace('news-', ''));
      history.replaceState(null, '', url);
    });
    tab.addEventListener('keydown', event => {
      const index = tabs.indexOf(tab);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
        : event.key === 'ArrowRight' ? (index + 1) % tabs.length
        : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : -1;
      if (next >= 0) { event.preventDefault(); tabs[next].focus(); tabs[next].click(); }
    });
  });
  show(tabs.find(tab => tab.hasAttribute('aria-current')) || tabs[0]);
});
