// 調車簽收選車：依車型、車色、位置篩選與即時搜尋，並顯示已選台數。
(() => {
  const form = document.querySelector("[data-transfer-select]");
  if (!form) return;
  const items = [...form.querySelectorAll("[data-transfer-item]")];
  const search = form.querySelector("[data-transfer-search]");
  const filters = [...form.querySelectorAll("[data-transfer-filter]")];
  const empty = form.querySelector("[data-transfer-empty]");
  const counts = form.querySelectorAll("[data-transfer-count]");

  const updateCount = () => {
    const total = form.querySelectorAll('input[name="vehicles"]:checked').length;
    counts.forEach((node) => { node.textContent = total; });
  };
  const apply = () => {
    const terms = (search?.value || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
    const wanted = Object.fromEntries(filters.map((select) => [select.dataset.transferFilter, select.value]));
    let visible = 0;
    for (const item of items) {
      // 已勾選的車一律保留顯示，避免篩選後看不到已選的車。
      const checked = item.querySelector("input").checked;
      const text = item.dataset.search || "";
      const match = checked || (
        terms.every((term) => text.includes(term))
        && Object.entries(wanted).every(([key, value]) => !value || item.dataset[key] === value)
      );
      item.hidden = !match;
      if (match) visible += 1;
    }
    if (empty) empty.hidden = visible > 0;
  };

  form.addEventListener("change", (event) => {
    if (event.target.name === "vehicles") updateCount();
    if (event.target.matches("[data-transfer-filter]")) apply();
  });
  if (search) {
    search.addEventListener("input", apply);
    // 在搜尋框按 Enter 不送出表單。
    search.addEventListener("keydown", (event) => { if (event.key === "Enter") event.preventDefault(); });
  }
  updateCount();
})();
