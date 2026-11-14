/* 配件與工資批次修改（T-178）：直接在清單上改，有改到的列才送出；勾選多筆可一次加入／移出類別或改啟用狀態。
   一個配件可屬於多個類別（T-179）：每列的類別是一組勾選框，摘要顯示目前勾選的類別。
   伺服器沿用單筆表單驗證，任一筆有錯就都不存，畫面會把輸入值帶回來。 */
(() => {
  const form = document.querySelector("[data-accessory-bulk]");
  if (!form) return;
  const rows = [...form.querySelectorAll("[data-bulk-row]")];
  const pickAll = form.querySelector("[data-pick-all]");
  const pickedCount = form.querySelector("[data-picked-count]");
  const dirtyCount = form.querySelector("[data-dirty-count]");
  const categorySelect = form.querySelector("[data-bulk-category]");
  const categoryActions = [...form.querySelectorAll("[data-bulk-category-action]")];
  const activeButtons = [...form.querySelectorAll("[data-bulk-active]")];
  const saveButton = form.querySelector("[data-bulk-save]");
  let submitting = false;

  const fields = row => [...row.querySelectorAll("[data-original]")];
  const current = control => (control.type === "checkbox" ? (control.checked ? "1" : "0") : control.value.trim());
  const same = control => {
    const now = current(control);
    const original = control.dataset.original;
    if (control.type === "number" && now !== "" && original !== "") return Number(now) === Number(original);
    return now === original;
  };
  const isDirty = row => fields(row).some(control => !same(control));
  const picked = () => rows.filter(row => row.querySelector("[data-pick]").checked);

  function summarize(row) {
    const summary = row.querySelector("[data-cats-summary]");
    if (!summary) return;
    const names = [...row.querySelectorAll('input[name$="-categories"]:checked')].map(box => box.dataset.categoryName);
    summary.textContent = names.length ? names.join("、") : "未分類";
  }

  function refresh() {
    let dirty = 0;
    for (const row of rows) {
      summarize(row);
      const changed = isDirty(row);
      row.classList.toggle("is-dirty", changed);
      for (const control of fields(row)) control.classList.toggle("is-changed", !same(control));
      if (changed) dirty += 1;
    }
    dirtyCount.textContent = dirty ? `已修改 ${dirty} 項` : "還沒有修改";
    saveButton.disabled = dirty === 0;
    const count = picked().length;
    pickedCount.textContent = count ? `已勾選 ${count} 項` : "尚未勾選";
    for (const row of rows) row.classList.toggle("is-picked", row.querySelector("[data-pick]").checked);
    for (const button of categoryActions) button.disabled = count === 0 || categorySelect.selectedIndex <= 0;
    for (const button of activeButtons) button.disabled = count === 0;
    if (pickAll) {
      pickAll.checked = count > 0 && count === rows.length;
      pickAll.indeterminate = count > 0 && count < rows.length;
    }
    return dirty;
  }

  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  pickAll?.addEventListener("change", () => {
    for (const row of rows) row.querySelector("[data-pick]").checked = pickAll.checked;
    refresh();
  });
  for (const button of categoryActions) {
    button.addEventListener("click", () => {
      const add = button.dataset.bulkCategoryAction === "add";
      for (const row of picked()) {
        const box = row.querySelector(`input[name$="-categories"][value="${categorySelect.value}"]`);
        if (box) box.checked = add;
      }
      refresh();
    });
  }
  for (const button of activeButtons) {
    button.addEventListener("click", () => {
      for (const row of picked()) row.querySelector('input[type="checkbox"][name$="-active"]').checked = button.dataset.bulkActive === "1";
      refresh();
    });
  }

  form.addEventListener("submit", event => {
    if (refresh() === 0) {
      event.preventDefault();
      return;
    }
    // 只送有改到的列；沒改的整列停用，不會被送出。
    for (const row of rows) {
      if (isDirty(row)) continue;
      for (const control of row.querySelectorAll("input, select")) control.disabled = true;
    }
    submitting = true;
  });
  window.addEventListener("pageshow", () => {
    submitting = false;
    for (const control of form.querySelectorAll("[data-bulk-row] :disabled")) control.disabled = false;
    refresh();
  });
  window.addEventListener("beforeunload", event => {
    if (submitting || !rows.some(isDirty)) return;
    event.preventDefault();
    event.returnValue = "";
  });

  refresh();
})();
