(() => {
  "use strict";

  // T-286：「車輛結算成本」新增頁選好機種後，金額帶入該機種目前的成本；使用者自己輸入過的金額不覆蓋。
  const formatAmount = (amount) => Number(amount).toLocaleString("en-US");

  // 回傳 {amount, message}；amount 為 null 表示金額欄維持原值。
  function prefillDecision({selected, entry, manual}) {
    if (!selected) return {amount: manual ? null : "", message: ""};
    if (manual) {
      return {
        amount: null,
        message: entry
          ? `已保留你輸入的金額；此機種目前成本為 ${formatAmount(entry.amount)}（${entry.from} 起版本）。`
          : "已保留你輸入的金額；此機種目前沒有生效中的成本。",
      };
    }
    if (!entry) return {amount: "", message: "此機種目前沒有生效中的成本，請輸入金額。"};
    return {
      amount: String(entry.amount),
      message: `已帶入此機種 ${entry.from} 起版本的成本；可直接修改，原版本不會被改動。`,
    };
  }

  function initCostPrefill(form, costs) {
    if (!form || !costs) return;
    const model = form.querySelector('[name="vehicle_model"]');
    const amount = form.querySelector('[name="amount"]');
    const note = form.querySelector("[data-cost-prefill-note]");
    if (!model || !amount) return;
    // 驗證失敗回填的金額是使用者送出的值，視為手動輸入；伺服器依 ?model= 帶入的不算。
    let manual = form.hasAttribute("data-cost-prefill-bound") && amount.value !== "";
    amount.addEventListener("input", () => { manual = amount.value !== ""; });
    model.addEventListener("change", () => {
      const decision = prefillDecision({selected: model.value, entry: costs[model.value], manual});
      if (decision.amount !== null) amount.value = decision.amount;
      if (note) {
        note.textContent = decision.message;
        note.hidden = !decision.message;
      }
    });
  }

  if (typeof module !== "undefined" && module.exports) module.exports = {prefillDecision, initCostPrefill};
  if (typeof document !== "undefined") {
    const data = document.getElementById("cost-prefill-data");
    initCostPrefill(document.querySelector("[data-cost-prefill]"), data ? JSON.parse(data.textContent) : null);
  }
})();
