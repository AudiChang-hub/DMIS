(() => {
  "use strict";

  // 現有台數表：點台數或整列展開／收起每台車明細；「展開每台車」一次切換全部（T-115）。
  const rows = () => [...document.querySelectorAll("tr[data-stock-row]")];

  const setOpen = (row, open) => {
    const detail = document.getElementById(row.dataset.stockRow);
    const toggle = row.querySelector(".stock-qty-toggle");
    if (!detail || !toggle) return;
    detail.hidden = !open;
    row.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  };

  const syncExpandAll = () => {
    const button = document.querySelector("[data-stock-expand-all]");
    if (!button) return;
    const all = rows();
    const allOpen = all.length > 0 && all.every((row) => row.classList.contains("is-open"));
    button.setAttribute("aria-pressed", allOpen ? "true" : "false");
    const label = button.querySelector("[data-stock-expand-label]");
    if (label) label.textContent = allOpen ? "收起每台車" : "展開每台車";
    button.hidden = all.length === 0;
  };

  document.addEventListener("click", (event) => {
    const expandAll = event.target.closest("[data-stock-expand-all]");
    if (expandAll) {
      const open = expandAll.getAttribute("aria-pressed") !== "true";
      rows().forEach((row) => setOpen(row, open));
      syncExpandAll();
      return;
    }
    const row = event.target.closest("tr[data-stock-row]");
    // 整列可點；列內的連結照常開啟，不切換。
    if (!row || (event.target.closest("a") && !event.target.closest(".stock-qty-toggle"))) return;
    setOpen(row, !row.classList.contains("is-open"));
    syncExpandAll();
  });

  syncExpandAll();
})();
