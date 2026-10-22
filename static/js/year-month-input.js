// 6 碼年月輸入（YYYYMM，例 201309）：只留數字、下方即時換算或提示錯誤（使用者 2026-10-22 T-93）。
// 未完成或不合理時設 customValidity，訂單頁自動儲存會等到格式正確才送出；伺服器端由 YearMonthDateField 再驗一次。
(() => {
  const MIN_YEAR = 1950;
  const EMPTY_HINT = '6 碼數字，例 201309';

  function evaluate(value, today = new Date()) {
    if (!value) return {state: 'empty', text: EMPTY_HINT, error: ''};
    if (value.length < 6) {
      const text = `還差 ${6 - value.length} 碼，例 201309`;
      return {state: 'partial', text, error: text};
    }
    const year = Number(value.slice(0, 4));
    const month = Number(value.slice(4));
    let error = '';
    if (month < 1 || month > 12) error = '月份要在 01 到 12 之間';
    else if (year < MIN_YEAR || year > today.getFullYear()) error = `年份要在 ${MIN_YEAR} 年到今年之間`;
    else if (year * 12 + month > today.getFullYear() * 12 + today.getMonth() + 1) error = '出廠年月不能晚於本月';
    if (error) return {state: 'error', text: error, error};
    return {state: 'ok', text: `${year} 年 ${month} 月・民國 ${year - 1911} 年`, error: ''};
  }

  function hintOf(input) {
    return document.getElementById(`${input.id}_ym`) || input.parentElement?.querySelector('[data-year-month-hint]');
  }

  function render(input, {settled = false} = {}) {
    const result = evaluate(input.value);
    input.setCustomValidity(result.error);
    // 打字途中還差幾碼只當提示；離開欄位或已打滿 6 碼才標成錯誤。
    const showError = result.state === 'error' || (result.state === 'partial' && settled);
    const hint = hintOf(input);
    if (hint) {
      hint.textContent = result.text;
      hint.dataset.state = showError ? 'error' : result.state;
    }
    input.closest('[data-field-container]')?.classList.toggle('has-year-month-error', showError);
    // 自動儲存的 input 監聽會清掉 aria-invalid，排到這次事件的所有監聽之後再設定。
    setTimeout(() => {
      if (showError) input.setAttribute('aria-invalid', 'true');
      else input.removeAttribute('aria-invalid');
    }, 0);
  }

  function onInput(event) {
    const input = event.target;
    if (!input.matches?.('[data-year-month]')) return;
    const digits = input.value.replace(/\D/g, '').slice(0, 6);
    if (digits !== input.value) input.value = digits;
    render(input);
  }

  document.addEventListener('input', onInput, true);
  document.addEventListener('focusout', event => {
    if (event.target.matches?.('[data-year-month]')) render(event.target, {settled: true});
  });
  // 欄位可能是自動儲存局部更新後換上的新節點，載入與更新後都重新同步一次。
  const sync = () => document.querySelectorAll('[data-year-month]').forEach(input => render(input, {settled: true}));
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', sync, {once: true});
  else sync();
  // workspace-saved 在表單上派送、不冒泡，用捕獲階段接。
  document.addEventListener('workspace-saved', () => setTimeout(sync, 0), true);
  document.addEventListener('inplace:updated', sync);

  window.DMISYearMonth = {evaluate};
})();
