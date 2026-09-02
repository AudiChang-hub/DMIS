(() => {
  const optionsNode = document.getElementById("assignment-district-options");
  let districtOptions = {};
  try {
    districtOptions = JSON.parse(optionsNode?.textContent || "{}");
  } catch (_error) {
    districtOptions = {};
  }

  const bulkCity = document.querySelector("[data-bulk-city]");
  const bulkDistrict = document.querySelector("[data-bulk-district]");
  if (bulkCity && bulkDistrict) {
    bulkCity.addEventListener("change", () => {
      const city = bulkCity.value;
      bulkDistrict.replaceChildren(new Option("整個縣市", ""));
      (districtOptions[city] || []).forEach(district => {
        bulkDistrict.add(new Option(district, district));
      });
      bulkDistrict.disabled = !city;
    });
  }

  const rows = () => Array.from(document.querySelectorAll("[data-assignment-row]"));
  const assigneeValue = row => row.querySelector("[data-assignee-select]")?.value || "";
  const orderInput = row => row.querySelector("[data-order-input]");

  function renumberAssignee(value) {
    if (!value) return;
    rows().filter(row => assigneeValue(row) === value).forEach((row, index) => {
      const input = orderInput(row);
      if (input) input.value = String(index + 1);
    });
  }

  document.addEventListener("change", event => {
    const select = event.target.closest("[data-assignee-select]");
    if (!select) return;
    const row = select.closest("[data-assignment-row]");
    const input = orderInput(row);
    if (!input) return;
    input.disabled = !select.value;
    if (!select.value) {
      input.value = "";
      return;
    }
    const existingOrders = rows()
      .filter(candidate => candidate !== row && assigneeValue(candidate) === select.value)
      .map(candidate => Number(orderInput(candidate)?.value || 0));
    if (!Number(input.value)) input.value = String(Math.max(0, ...existingOrders) + 1);
  });

  document.addEventListener("click", event => {
    const moveButton = event.target.closest("[data-move]");
    if (moveButton) {
      const row = moveButton.closest("[data-assignment-row]");
      const value = assigneeValue(row);
      if (!value) return;
      const matchingRows = rows().filter(candidate => assigneeValue(candidate) === value);
      const currentIndex = matchingRows.indexOf(row);
      const targetIndex = moveButton.dataset.move === "up" ? currentIndex - 1 : currentIndex + 1;
      const target = matchingRows[targetIndex];
      if (!target) return;
      const body = row.parentElement;
      if (moveButton.dataset.move === "up") body.insertBefore(row, target);
      else body.insertBefore(target, row);
      renumberAssignee(value);
      row.querySelector("[data-order-input]")?.focus({preventScroll: true});
      return;
    }

    const renumberButton = event.target.closest("[data-renumber-visible]");
    if (renumberButton) {
      const assignees = new Set(rows().map(assigneeValue).filter(Boolean));
      assignees.forEach(renumberAssignee);
    }
  });
})();
