// 調車簽收選車：即時搜尋與已選台數。
(() => {
  const form = document.querySelector("[data-transfer-select]");
  if (!form) return;
  const items = [...form.querySelectorAll("[data-transfer-item]")];
  const search = form.querySelector("[data-transfer-search]");
  const empty = form.querySelector("[data-transfer-empty]");
  const counts = form.querySelectorAll("[data-transfer-count]");

  const updateCount = () => {
    const total = form.querySelectorAll('input[name="vehicles"]:checked').length;
    counts.forEach((node) => { node.textContent = total; });
  };
  const filter = () => {
    const terms = (search.value || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
    let visible = 0;
    for (const item of items) {
      const text = item.dataset.search || "";
      // 已勾選的車一律保留顯示，避免搜尋後看不到已選的車。
      const checked = item.querySelector("input").checked;
      const match = checked || terms.every((term) => text.includes(term));
      item.hidden = !match;
      if (match) visible += 1;
    }
    if (empty) empty.hidden = visible > 0;
  };

  form.addEventListener("change", (event) => {
    if (event.target.name === "vehicles") updateCount();
  });
  if (search) {
    search.addEventListener("input", filter);
    // 在搜尋框按 Enter 不送出表單。
    search.addEventListener("keydown", (event) => { if (event.key === "Enter") event.preventDefault(); });
  }
  updateCount();
})();
