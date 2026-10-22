// 交車區塊會隨原地更新整塊換新（使用者 2026-10-22 T-92）：每張交車表單只綁一次，換新後再綁新的表單。
function bindDeliveryForms(scope = document) {
  const forms = Array.from(scope.querySelectorAll(".delivery-completion-form:not([data-delivery-bound])"));
  forms.forEach((form) => { form.dataset.deliveryBound = ""; });
  // 交車收尾款（使用者 2026-10-22 T-75）：應收大於 0 時，實收金額大於或等於應收才能按「收尾款並完成交車」；
  // 應收為 0 不卡。交車條件不符（原因清單有內容）時照舊停用。送出時後端再用同一規則驗證。
  forms.forEach((form) => {
    const fieldset = document.getElementById("delivery-balance");
    const amount = form.elements.namedItem("balance-received_amount");
    const button = form.querySelector('.delivery-completion-actions button[type="submit"]');
    if (!fieldset || !amount || !button) return;
    const due = Number(fieldset.dataset.deliveryDue || 0);
    const hint = fieldset.querySelector("[data-balance-hint]");
    const blockers = form.querySelector("[data-delivery-blockers]");
    // 對帳單右欄（使用者 2026-10-22 T-76）：實收與尚差跟著輸入即時更新。
    const summary = fieldset.querySelector("[data-balance-summary]");
    const money = (value) => `$${Math.round(value).toLocaleString("zh-TW")}`;
    const syncSummary = () => {
      if (!summary) return;
      const received = Number(amount.value || 0);
      const filled = amount.value !== "";
      const gap = due - received;
      summary.dataset.state = !filled ? "empty" : gap > 0 ? "short" : "ok";
      summary.querySelector("[data-balance-received]").textContent = filled ? money(received) : "—";
      summary.querySelector("[data-balance-gap-label]").textContent = gap > 0 || !filled ? "尚差" : gap < 0 ? "多收" : "差額";
      summary.querySelector("[data-balance-gap]").textContent = money(Math.abs(filled ? gap : due));
      summary.querySelector("[data-balance-state]").textContent = !filled
        ? "填入實收金額，足額後即可收尾款並完成交車。"
        : gap > 0 ? `還差 ${money(gap)}，補足後才能完成交車。` : "已足額，可以收尾款並完成交車。";
    };
    const sync = () => {
      syncSummary();
      const short = due > 0 && !(Number(amount.value || 0) >= due);
      button.dataset.balanceShort = short ? "1" : "";
      const blocked = Boolean(blockers && !blockers.hidden);
      button.disabled = short || blocked;
      button.setAttribute("aria-disabled", String(button.disabled));
      hint?.classList.toggle("is-warning", short && amount.value !== "");
    };
    amount.addEventListener("input", sync);
    amount.addEventListener("change", sync);
    new MutationObserver(sync).observe(blockers || button, {attributes: true, attributeFilter: ["hidden"]});
    sync();
  });

  // 交付核對四項可一次全部勾選；再按一次取消，方便發現漏看時重來。
  forms.forEach((form) => {
    const button = form.querySelector("[data-delivery-check-all]");
    const count = form.querySelector("[data-delivery-checklist-count]");
    const checks = ["condition_checked", "documents_checked", "keys_checked", "accessories_checked", "vehicle_control_checked"]
      .map((name) => form.querySelector(`[name="${name}"]`))
      .filter(Boolean);
    if (!button || !checks.length) return;

    const sync = () => {
      const done = checks.filter((input) => input.checked).length;
      const all = done === checks.length;
      button.textContent = all ? "取消全部勾選" : "全部已核對";
      button.setAttribute("aria-pressed", String(all));
      if (count) count.textContent = `已核對 ${done}／${checks.length} 項`;
    };

    button.addEventListener("click", () => {
      const target = !checks.every((input) => input.checked);
      checks.forEach((input) => {
        input.checked = target;
        input.dispatchEvent(new Event("change", {bubbles: true}));
      });
    });
    checks.forEach((input) => input.addEventListener("change", sync));
    sync();
  });

  forms.forEach((form) => {
    const conditionInputs = Array.from(
      form.querySelectorAll('[name="vehicle_condition_note"]')
    );
    const damageDetails = form.querySelector("[data-delivery-damage-details]");
    if (!conditionInputs.length || !damageDetails) return;

    const syncDamageDetails = () => {
      const selected = conditionInputs.find((input) => input.checked);
      damageDetails.hidden = selected?.value !== "發現刮傷或損壞";
    };

    conditionInputs.forEach((input) => {
      input.addEventListener("change", syncDamageDetails);
    });
    syncDamageDetails();
  });
}

document.addEventListener("DOMContentLoaded", () => bindDeliveryForms());
document.addEventListener("inplace:updated", (event) => event.detail.regions.forEach((region) => bindDeliveryForms(region)));
