(() => {
  const OTHER_UNIT = "__other__";
  const rows = document.querySelector("[data-reward-rows]");
  const template = document.querySelector("[data-reward-template]");
  const total = document.getElementById("id_reward_items-TOTAL_FORMS");
  if (!rows || !template || !total) return;

  function parseOptions(unit, attribute) {
    try {
      return JSON.parse(unit.getAttribute(attribute) || "{}");
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

  function toggleOtherUnit(unit, shouldFocus = false) {
    const container = unit.closest("[data-field-container]");
    if (!container) return;
    let input = container.querySelector("[data-reward-unit-other]");
    if (!input) {
      input = document.createElement("input");
      input.type = "text";
      input.maxLength = 20;
      input.autocomplete = "off";
      input.className = "form-control dealer-reward-unit-other";
      input.placeholder = "請輸入其他單位";
      input.setAttribute("aria-label", "其他單位");
      input.setAttribute("data-reward-unit-other", "");
      input.name = unit.name.replace(/-unit$/, "-unit_other");
      input.value = unit.dataset.rewardUnitOtherValue || "";
      container.appendChild(input);
    }
    const shouldShow = unit.value === OTHER_UNIT;
    input.hidden = !shouldShow;
    input.required = shouldShow;
    if (shouldShow && shouldFocus) input.focus();
  }

  function syncUnitOptions(row, resetToDefault = false) {
    const type = row.querySelector("[data-reward-type]");
    const unit = row.querySelector("[data-reward-unit]");
    if (!type || !unit) return;
    const optionsByType = parseOptions(unit, "data-reward-units");
    const defaultsByType = parseOptions(unit, "data-reward-default-units");
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

    if (resetToDefault || !current) {
      unit.value = defaultsByType[type.value] || "";
    } else {
      unit.value = current;
    }
    toggleOtherUnit(unit);
  }

  function bind(row) {
    row.querySelector("[data-remove-reward]")?.addEventListener("click", () => {
      const deletion = row.querySelector('[name$="-DELETE"]');
      if (deletion) deletion.checked = true;
      row.hidden = true;
    });
    const type = row.querySelector("[data-reward-type]");
    const unit = row.querySelector("[data-reward-unit]");
    type?.addEventListener("change", () => syncUnitOptions(row, true));
    unit?.addEventListener("change", () => toggleOtherUnit(unit, true));
    syncUnitOptions(row);
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
