(() => {
  const form = document.querySelector('[data-company-form]');
  if (!form) return;
  const update = () => form.querySelectorAll('[data-company-field]').forEach(input => {
    const preview = form.querySelector(`[data-company-preview="${input.dataset.companyField}"]`);
    if (preview) preview.textContent = input.value.trim() || '尚未填寫';
  });
  form.addEventListener('input', update);
  update();
})();
