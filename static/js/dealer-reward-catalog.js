(() => {
  const OTHER_UNIT = "__other__";
  const form = document.querySelector("[data-reward-catalog-form]");
  if (!form) return;

  const type = form.querySelector("[data-reward-type]");
  const unit = form.querySelector("[data-reward-unit]");

  function parseOptions(attribute) {
    try {
      return JSON.parse(unit?.getAttribute(attribute) || "{}");
    } catch (_error) {
      return {};
    }
  }

  function addOption(select, value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }

  function toggleOtherUnit(shouldFocus = false) {
    if (!unit) return;
    const container = unit.closest("[data-field-container]");
    if (!container) return;
    let input = container.querySelector("[data-reward-unit-other]");
    if (!input) {
      input = document.createElement("input");
      input.type = "text";
      input.name = "unit_other";
      input.maxLength = 20;
      input.autocomplete = "off";
      input.className = "form-control dealer-reward-unit-other";
      input.placeholder = "請輸入其他單位";
      input.setAttribute("aria-label", "其他單位");
      input.setAttribute("data-reward-unit-other", "");
      input.value = unit.dataset.rewardUnitOtherValue || "";
      container.appendChild(input);
    }
    const shouldShow = unit.value === OTHER_UNIT;
    input.hidden = !shouldShow;
    input.required = shouldShow;
    if (shouldShow && shouldFocus) input.focus();
  }

  function syncUnitOptions(resetToDefault = false) {
    if (!type || !unit) return;
    const optionsByType = parseOptions("data-reward-units");
    const defaultsByType = parseOptions("data-reward-default-units");
    const allowed = optionsByType[type.value] || [];
    const current = unit.value;
    const preserveCurrent = !resetToDefault && current && !allowed.includes(current);

    unit.replaceChildren();
    addOption(unit, "", "請選擇單位");
    allowed.forEach((value) => addOption(unit, value, value));
    if (preserveCurrent && current !== OTHER_UNIT) {
      addOption(unit, current, `目前單位：${current}`);
    }
    addOption(unit, OTHER_UNIT, "其他（自行輸入）");
    unit.value = resetToDefault || !current ? defaultsByType[type.value] || "" : current;
    toggleOtherUnit();
  }

  type?.addEventListener("change", () => syncUnitOptions(true));
  unit?.addEventListener("change", () => toggleOtherUnit(true));
  syncUnitOptions();

  const rows = form.querySelector("[data-cost-version-rows]");
  const template = form.querySelector("[data-cost-version-template]");
  const total = document.getElementById("id_cost_versions-TOTAL_FORMS");
  if (!rows || !template || !total) return;

  function bindCostRow(row) {
    row.querySelector("[data-remove-cost-version]")?.addEventListener("click", () => {
      const deletion = row.querySelector('[name$="-DELETE"]');
      if (deletion) deletion.checked = true;
      row.hidden = true;
    });
  }

  rows.querySelectorAll("[data-cost-version-row]").forEach(bindCostRow);
  form.querySelector("[data-add-cost-version]")?.addEventListener("click", () => {
    const index = Number(total.value);
    const wrapper = document.createElement("div");
    wrapper.innerHTML = template.innerHTML.replaceAll("__prefix__", index).trim();
    const row = wrapper.firstElementChild;
    rows.appendChild(row);
    total.value = index + 1;
    bindCostRow(row);
    row.querySelector("input, select")?.focus();
  });
})();
