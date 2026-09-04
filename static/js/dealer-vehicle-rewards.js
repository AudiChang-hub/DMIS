(() => {
  const rows = document.querySelector("[data-reward-rows]");
  const template = document.querySelector("[data-reward-template]");
  const total = document.getElementById("id_reward_items-TOTAL_FORMS");
  const effectiveFrom = document.getElementById("id_effective_from");
  const catalogDataElement = document.getElementById("dealer-reward-catalog-data");
  if (!rows || !template || !total) return;

  let catalog = {};
  try {
    catalog = JSON.parse(catalogDataElement?.textContent || "{}");
  } catch (_error) {
    catalog = {};
  }

  function money(value) {
    return `$${new Intl.NumberFormat("zh-TW", {
      maximumFractionDigits: 2,
    }).format(value)}`;
  }

  function resolveCost(item, onDate) {
    if (!item || !onDate) return null;
    const version = item.costs.find(
      (candidate) => candidate.from <= onDate && (!candidate.to || candidate.to >= onDate),
    );
    return version ? Number(version.amount) : null;
  }

  function updateSummary(row, preserveSnapshot = false) {
    const select = row.querySelector("[data-reward-catalog]");
    const quantity = row.querySelector('[name$="-quantity"]');
    const summary = row.querySelector("[data-reward-cost-summary]");
    if (!select || !quantity || !summary) return;
    const item = catalog[select.value];
    const unitLabel = summary.querySelector("[data-reward-catalog-unit]");
    const unitCostLabel = summary.querySelector("[data-reward-unit-cost]");
    const totalCostLabel = summary.querySelector("[data-reward-total-cost]");
    if (!item) {
      unitLabel.textContent = "選擇品項後顯示";
      unitCostLabel.textContent = "—";
      totalCostLabel.textContent = "—";
      return;
    }
    const snapshot = preserveSnapshot && summary.dataset.unitCostSnapshot
      ? Number(summary.dataset.unitCostSnapshot)
      : null;
    const unitCost = snapshot ?? resolveCost(item, effectiveFrom?.value || "");
    const amount = Number(quantity.value);
    const hasQuantity = quantity.value.trim() !== "" && Number.isFinite(amount);
    unitLabel.textContent = `${item.type}／${item.unit}`;
    unitCostLabel.textContent = unitCost === null ? "該日期尚未維護成本" : money(unitCost);
    totalCostLabel.textContent = unitCost === null || !hasQuantity
      ? "—"
      : money(unitCost * amount);
  }

  function bind(row) {
    row.querySelector("[data-remove-reward]")?.addEventListener("click", () => {
      const deletion = row.querySelector('[name$="-DELETE"]');
      if (deletion) deletion.checked = true;
      row.hidden = true;
    });
    row.querySelector("[data-reward-catalog]")?.addEventListener("change", () => {
      row.querySelector("[data-reward-cost-summary]").dataset.unitCostSnapshot = "";
      updateSummary(row);
    });
    row.querySelector('[name$="-quantity"]')?.addEventListener("input", () => {
      updateSummary(row, true);
    });
    updateSummary(row, true);
  }

  rows.querySelectorAll("[data-reward-row]").forEach(bind);
  effectiveFrom?.addEventListener("change", () => {
    rows.querySelectorAll("[data-reward-row]:not([hidden])").forEach((row) => {
      row.querySelector("[data-reward-cost-summary]").dataset.unitCostSnapshot = "";
      updateSummary(row);
    });
  });
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
