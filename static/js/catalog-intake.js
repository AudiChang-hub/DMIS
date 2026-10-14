/* 同頁更換選擇，不離開草稿、不清空車主資料。 */
(() => {
  const payment = document.getElementById('id_payment_type');
  const token = document.getElementById('id_catalog_selection');
  // 選車已定現金或分期：付款方式只留同一類（現金可改刷卡），互換要先按「更換車款／付款方案」。
  const allowed = (payment?.dataset?.catalogPayment || '').split(' ').filter(Boolean);
  const lockPayment = locked => {
    for (const option of payment.options || []) {
      option.disabled = locked && !!option.value && !allowed.includes(option.value);
    }
  };
  if (payment && token?.value && allowed.length) lockPayment(true);
  const button = document.querySelector('[data-catalog-change]');
  if (!button) return;
  button.addEventListener('click', () => {
    token.value = '';
    lockPayment(false);
    const hint = document.getElementById('id_payment_type_help');
    if (hint) hint.hidden = true;
    if (payment.value === 'installment') {
      // 重新選擇目前方案，避免舊期款留在畫面卻於送出時換價。
      for (const id of ['id_installment_company', 'id_installment_periods', 'id_installment_monthly', 'id_installment_opening_fee']) {
        document.getElementById(id).value = '';
      }
    }
    payment.dispatchEvent(new Event('change', {bubbles:true}));
    document.querySelector('[data-catalog-intake-summary]').hidden = true;
    for (const id of ['vehicle', 'payment']) document.getElementById(id).open = true;
    document.getElementById('vehicle').querySelector('summary').focus();
    token.dispatchEvent(new Event('input', {bubbles:true}));
  });
})();
