(() => {
  const rows = document.querySelector("[data-reward-rows]");
  const template = document.querySelector("[data-reward-template]");
  const total = document.getElementById("id_reward_items-TOTAL_FORMS");
  if (!rows || !template || !total) return;
  function bind(row) {
    row.querySelector("[data-remove-reward]")?.addEventListener("click", () => {
      const deletion = row.querySelector('[name$="-DELETE"]');
      if (deletion) deletion.checked = true;
      row.hidden = true;
    });
    const type = row.querySelector('[name$="-reward_type"]');
    const unit = row.querySelector('[name$="-unit"]');
    type?.addEventListener("change", () => {
      if (!unit || unit.value.trim()) return;
      unit.value = { cash_gift: "元", voucher: "元", travel_points: "點", physical: "件" }[type.value] || "";
    });
  }
  rows.querySelectorAll("[data-reward-row]").forEach(bind);
  document.querySelector("[data-add-reward]")?.addEventListener("click", () => {
    const index = Number(total.value);
    const wrapper = document.createElement("div");
    wrapper.innerHTML = template.innerHTML.replaceAll("__prefix__", index).trim();
    const row = wrapper.firstElementChild;
    rows.appendChild(row);
    total.value = index + 1;
    bind(row);
    row.querySelector("select, input")?.focus();
  });
})();
