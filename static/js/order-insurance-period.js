/* 強制險期間（T-333，使用者 2026-11-28）：建單與訂單頁都看得到、可改。
   可選年期依車型：油車一、兩年；微電車固定三年；電動類取品牌固定規則有的年期（views._vehicle_rate_data 的 insurance_periods，
   與伺服器 registration_period_for 同一組規則），沒有規則就不限制（照舊）。只有一種年期時下拉隱藏、改顯示唯讀文字，
   下拉仍隨表單送出。油車選到三年改回一年、微電車一律三年，與原本前端行為相同；電動類既有訂單的值不在規則年期內時，
   只有使用者換了車型或動力類型才換成規則有的年期，載入頁面或改其他欄位都照原值。
   T-339（使用者 2026-11-28）：可選年期只列規則有設定的；微電車一律三年。既有訂單存的年期跟畫面不同或不在規則內時，
   欄位下方說明原值與存檔後的結果（note），微電車已交車／匯入的單存三年但保留完成時的牌險、強制險金額。 */
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
  // note：說明文字元素；completed：已交車（完成後修正），決定微電車舊單存檔後牌險是保留還是重新試算。
  function apply(select, {energyType = '', periods = [], basis = '', keepExisting = false, fixedInput = null, label = null,
                          note = null, completed = false} = {}) {
    let allowed = allowedPeriods(energyType, periods);
    const current = Number(select.value);
    const previous = select.dataset.insurancePeriodBasis;
    select.dataset.insurancePeriodBasis = basis;
    if (select.dataset.insurancePeriodInitialBasis === undefined) select.dataset.insurancePeriodInitialBasis = basis;
    const sameVehicle = previous === undefined || previous === basis;
    // 資料庫存的值＝伺服器輸出時選取的選項。
    const stored = Number([...select.options].find(option => option.defaultSelected)?.value || 0);
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
    let message = '';
    const initialVehicle = select.dataset.insurancePeriodInitialBasis === basis;
    if (keepExisting && initialVehicle && stored && LABELS[stored]) {
      if (energyType === 'micro_electric' && stored !== 3) {
        message = `這張單原本存${LABELS[stored]}（舊資料）；微電車一律三年，存檔時改存三年，`
          + (completed ? '牌險、強制險保留完成時的金額。' : '牌險依規則重新試算。');
      } else if (keepCurrent && Number(select.value) === stored) {
        message = `這張單存的${LABELS[stored]}不在此車型規則的年期內；改選其他年期後就只能選規則有的年期。`;
      }
    }
    if (note) {
      note.textContent = message;
      note.hidden = !message;
    }
    return {allowed, fixed, value: select.value, note: message};
  }

  const api = {LABELS, allowedPeriods, apply};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.DmisInsurancePeriod = api;
})(globalThis);
