/* 強制險期間（T-333，使用者 2026-11-28）：建單與訂單頁都看得到、可改。
   可選年期依車型：油車一、兩年；微電車固定三年；電動類取品牌固定規則有的年期（views._vehicle_rate_data 的 insurance_periods，
   與伺服器 registration_period_for 同一組規則），沒有規則就不限制（照舊）。只有一種年期時下拉隱藏、改顯示唯讀文字，
   下拉仍隨表單送出。油車選到三年改回一年、微電車一律三年，與原本前端行為相同；電動類既有訂單的值不在規則年期內時，
   只有使用者換了車型或動力類型才換成規則有的年期，載入頁面或改其他欄位都照原值。 */
((root) => {
  const LABELS = {1: '一年', 2: '兩年', 3: '三年'};
  const ELECTRIC = ['electric', 'light_electric'];

  function allowedPeriods(energyType, periods) {
    if (energyType === 'gas') return [1, 2];
    if (energyType === 'micro_electric') return [3];
    if (ELECTRIC.includes(energyType) && Array.isArray(periods) && periods.length) {
      return [...new Set(periods.map(Number))].sort((a, b) => a - b);
    }
    return [];
  }

  // basis：車型＋動力類型；和上一次套用相同（含頁面載入的第一次）就不是「換車」，電動類的原值照留、金額不因此而變。
  // keepExisting：只有既有訂單（訂單頁）才保留原值；建單一律換成規則有的年期。
  function apply(select, {energyType = '', periods = [], basis = '', keepExisting = false, fixedInput = null, label = null} = {}) {
    let allowed = allowedPeriods(energyType, periods);
    const current = Number(select.value);
    const previous = select.dataset.insurancePeriodBasis;
    select.dataset.insurancePeriodBasis = basis;
    const sameVehicle = previous === undefined || previous === basis;
    const keepCurrent = keepExisting && sameVehicle && ELECTRIC.includes(energyType) && allowed.length && !allowed.includes(current);
    if (keepCurrent) allowed = [...allowed, current].sort((a, b) => a - b);
    [...select.options].forEach(option => {
      const blocked = allowed.length > 0 && !allowed.includes(Number(option.value));
      option.disabled = blocked;
      option.hidden = blocked;
    });
    if (allowed.length && !allowed.includes(Number(select.value))) select.value = String(allowed[0]);
    const fixed = allowed.length === 1;
    select.hidden = fixed;
    if (fixedInput) {
      fixedInput.hidden = !fixed;
      fixedInput.value = fixed ? (LABELS[allowed[0]] || '') : '';
    }
    if (label) label.htmlFor = fixed && fixedInput ? fixedInput.id : select.id;
    return {allowed, fixed, value: select.value};
  }

  const api = {LABELS, allowedPeriods, apply};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.DmisInsurancePeriod = api;
})(globalThis);
