(() => {
  const header = document.querySelector('.app-header');
  if (!header) return;
  let previous = 0;
  const measure = () => {
    const height = Math.ceil(header.getBoundingClientRect().height);
    if (height !== previous) {
      document.documentElement.style.setProperty('--app-header-height', `${height}px`);
      previous = height;
    }
  };
  measure();
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(measure).observe(header);
  window.addEventListener('resize', measure);
})();
