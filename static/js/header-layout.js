(() => {
  const header = document.querySelector('.app-header');
  if (!header) return;
  let previous = 0;
  const measure = () => {
    const height = Math.ceil(header.getBoundingClientRect().height);
    const viewportHeight = window.visualViewport?.height || window.innerHeight;
    document.documentElement.style.setProperty('--data-menu-available-height', `${Math.max(0, viewportHeight - height - 12)}px`);
    if (height !== previous) {
      document.documentElement.style.setProperty('--app-header-height', `${height}px`);
      previous = height;
    }
  };
  measure();
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(measure).observe(header);
  window.addEventListener('resize', measure);
  window.visualViewport?.addEventListener('resize', measure);
  const menu = header.querySelector('.desktop-data-menu');
  if (menu) {
    menu.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      menu.querySelector('a')?.focus();
      menu.dataset.dismissed = 'true';
      event.preventDefault();
    });
    menu.addEventListener('pointerenter', () => { delete menu.dataset.dismissed; });
    menu.addEventListener('focusin', () => { delete menu.dataset.dismissed; });
  }
})();
