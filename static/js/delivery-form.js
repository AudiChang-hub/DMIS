document.addEventListener("DOMContentLoaded", () => {
  // 交付核對四項可一次全部勾選；再按一次取消，方便發現漏看時重來。
  document.querySelectorAll(".delivery-completion-form").forEach((form) => {
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

  document.querySelectorAll(".delivery-completion-form").forEach((form) => {
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
});
