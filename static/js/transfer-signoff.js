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
  // 每個篩選器記住完整選項；選了車型後，車色與位置只列出該車型還有車的選項（並附台數），反之亦然。
  const allValues = new Map(filters.map((select) => [
    select, [...select.options].map((option) => option.value).filter(Boolean),
  ]));
  const allLabels = new Map(filters.map((select) => [select, select.options[0].textContent]));
  const searchTerms = () => (search?.value || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  const matches = (item, terms, wanted, skip) => terms.every((term) => (item.dataset.search || "").includes(term))
    && Object.entries(wanted).every(([key, value]) => key === skip || !value || item.dataset[key] === value);
  const narrow = (terms) => {
    for (const select of filters) {
      const key = select.dataset.transferFilter;
      const wanted = Object.fromEntries(filters.map((other) => [other.dataset.transferFilter, other.value]));
      const counts = new Map();
      for (const item of items) {
        if (matches(item, terms, wanted, key)) counts.set(item.dataset[key], (counts.get(item.dataset[key]) || 0) + 1);
      }
      const current = select.value;
      const values = allValues.get(select).filter((value) => counts.has(value));
      const options = [new Option(allLabels.get(select), "")];
      for (const value of values) options.push(new Option(`${value}（${counts.get(value)}）`, value));
      select.replaceChildren(...options);
      // 原本的選擇在新條件下已沒有車時，改回「全部」。
      select.value = values.includes(current) ? current : "";
    }
  };
  const apply = () => {
    const terms = searchTerms();
    narrow(terms);
    const wanted = Object.fromEntries(filters.map((select) => [select.dataset.transferFilter, select.value]));
    let visible = 0;
    for (const item of items) {
      // 已勾選的車一律保留顯示，避免篩選後看不到已選的車。
      const checked = item.querySelector("input").checked;
      const match = checked || matches(item, terms, wanted, null);
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
  narrow([]);
})();
