(() => {
  // 儲存後表單會原地換成伺服器新版（inplace-regions.js），新表單要重新綁定「新增定位欄位」。
  function init(root) {
    const section = root.querySelector("[data-positioned-fields]");
    if (!section || section.dataset.fieldsBound) return;
    const list = section.querySelector("[data-form-list]");
    const template = section.querySelector("template[data-empty-form]");
    const total = section.querySelector('[name$="-TOTAL_FORMS"]');
    const add = section.querySelector("[data-add-form]");
    if (!list || !template || !total || !add) return;
    section.dataset.fieldsBound = "1";
    add.addEventListener("click", () => {
      const index = Number(total.value);
      const html = template.innerHTML.replaceAll("__prefix__", String(index));
      list.insertAdjacentHTML("beforeend", html);
      total.value = String(index + 1);
      list.lastElementChild?.querySelector("select, input")?.focus();
    });
  }
  init(document);
  document.addEventListener("inplace:updated", () => init(document));
})();
