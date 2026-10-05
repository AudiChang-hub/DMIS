(() => {
  "use strict";

  // 車輛來源：只有「經銷商調車」才顯示並要求填寫調車來源。
  const TRANSFER = "dealer_transfer";

  const groupOf = (element) =>
    element.closest("[data-acquisition-group]") || element.closest("form");

  const selectedType = (group) => {
    const select = group.querySelector("select[data-acquisition-type]");
    if (select) return select.value;
    const checked = group.querySelector("input[data-acquisition-type]:checked");
    return checked ? checked.value : "";
  };

  const sync = (group) => {
    const input = group.querySelector("[data-transfer-source]");
    if (!input) return;
    const isTransfer = selectedType(group) === TRANSFER;
    const container = input.closest("[data-field-container]") || input;
    container.hidden = !isTransfer;
    input.required = isTransfer;
    if (!isTransfer) input.value = "";
  };

  const syncAll = (root = document) => {
    root.querySelectorAll("[data-acquisition-group]").forEach(sync);
    const form = root.querySelector("form:has(input[data-acquisition-type])");
    if (form && !form.querySelector("[data-acquisition-group]")) sync(form);
  };

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.matches("[data-acquisition-type]")) {
      sync(groupOf(target));
    }
  });

  // 快速進車新增列時同步新列的顯示狀態。
  const rows = document.getElementById("quick-entry-rows");
  if (rows) {
    new MutationObserver(() => syncAll(rows)).observe(rows, { childList: true });
  }
  syncAll();
})();
