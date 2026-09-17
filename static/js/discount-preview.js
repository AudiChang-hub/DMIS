(() => {
  document.querySelectorAll('[data-discount-total]').forEach(form => {
    const mode = form.querySelector('[name="mode"]');
    const amount = form.querySelector('[name="amount"]');
    const rate = form.querySelector('[name="rate"]');
    const output = form.querySelector('[data-discount-preview]');
    const total = Number(form.dataset.discountTotal);
    const refresh = () => {
      const byRate = mode.value === 'rate';
      amount.disabled = byRate;
      rate.disabled = !byRate;
      amount.closest('[data-discount-field]').hidden = byRate;
      rate.closest('[data-discount-field]').hidden = !byRate;
      const value = Number(byRate ? rate.value : amount.value);
      const discounted = byRate ? Math.round(total * value / 10) : total - value;
      const valid = Number.isFinite(value) && value > 0 && (byRate ? value < 10 : value <= total);
      output.textContent = valid ? `試算優惠 ${(total-discounted).toLocaleString('zh-TW')} 元，折扣後總價 ${discounted.toLocaleString('zh-TW')} 元；核准前不套用。` : '請輸入有效的折數或減少金額。';
    };
    form.addEventListener('input', refresh);
    form.addEventListener('change', refresh);
    refresh();
  });
})();
