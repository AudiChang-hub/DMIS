(() => {
  const form = document.querySelector('[data-order-permission]');
  if (form) {
    const options = form.querySelector('[data-custom-permissions]');
    const update = () => { options.disabled = form.querySelector('[name="mode"]:checked')?.value !== 'custom'; };
    form.querySelectorAll('[name="mode"]').forEach(input => input.addEventListener('change', update));
    update();
  }
  let dirty = false;
  document.querySelectorAll('form[method="post"]').forEach(form => {
    form.addEventListener('change', () => { dirty = true; });
    form.addEventListener('submit', () => { dirty = false; });
  });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
})();
