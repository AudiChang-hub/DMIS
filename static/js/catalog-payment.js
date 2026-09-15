/* 只更新公開方案摘要；金額與方案有效性由後端重新核對。 */
(() => {
  const summary = document.querySelector('[data-payment-summary]');
  if (!summary) return;
  const choices = document.querySelectorAll('[data-payment-label]');
  const update = () => {
    const checked = [...choices].find(input => input.checked);
    summary.textContent = checked?.dataset.paymentLabel || '請選擇付款方案';
  };
  choices.forEach(input => input.addEventListener('change', update));
  window.addEventListener('pageshow', update);
  update();
})();
