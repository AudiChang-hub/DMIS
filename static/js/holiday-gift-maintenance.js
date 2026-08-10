(() => {
  const root = document.querySelector("[data-gift-maintenance]");
  if (!root) return;

  const search = root.querySelector("[data-gift-search]");
  const rows = [...root.querySelectorAll("[data-gift-row]")];
  const selectedCount = document.querySelector("[data-gift-selected-count]");
  const filterStatus = root.querySelector("[data-gift-filter-status]");
  const noResult = root.querySelector("[data-gift-no-result]");

  function normalize(value) {
    return (value || "").toLocaleLowerCase("zh-Hant").replace(/[\s-]+/g, "");
  }

  function visibleRows() {
    return rows.filter((row) => !row.hidden);
  }

  function updateSelectedCount() {
    const count = root.querySelectorAll("[data-gift-checkbox]:checked").length;
    if (selectedCount) selectedCount.textContent = `${count} 家`;
  }

  function applySearch() {
    const keyword = normalize(search?.value);
    let visibleCount = 0;
    rows.forEach((row) => {
      const matches = !keyword || normalize(row.dataset.search).includes(keyword);
      row.hidden = !matches;
      if (matches) visibleCount += 1;
    });
    if (filterStatus) {
      filterStatus.textContent = keyword
        ? `搜尋結果共 ${visibleCount} 家；批次勾選只會套用到目前顯示的車行。`
        : `目前顯示全部 ${visibleCount} 家合作車行。`;
    }
    if (noResult) noResult.hidden = visibleCount !== 0;
  }

  function setVisibleChecked(checked) {
    visibleRows().forEach((row) => {
      const checkbox = row.querySelector("[data-gift-checkbox]");
      if (checkbox) checkbox.checked = checked;
    });
    updateSelectedCount();
  }

  search?.addEventListener("input", applySearch);
  root.querySelector("[data-gift-select-visible]")?.addEventListener("click", () => setVisibleChecked(true));
  root.querySelector("[data-gift-clear-visible]")?.addEventListener("click", () => setVisibleChecked(false));
  root.addEventListener("change", (event) => {
    if (event.target.matches("[data-gift-checkbox]")) updateSelectedCount();
  });

  applySearch();
  updateSelectedCount();
})();
