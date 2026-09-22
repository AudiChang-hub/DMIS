(() => {
  const panel = document.getElementById('create-dealer-account');
  const trigger = document.querySelector('[data-open-dealer]');
  if (!panel || !trigger) return;
  trigger.addEventListener('click', (event) => {
    event.preventDefault();
    panel.open = true;
    panel.querySelector('select')?.focus({ preventScroll: true });
    panel.scrollIntoView({ block: 'center', behavior: 'auto' });
  });
})();
