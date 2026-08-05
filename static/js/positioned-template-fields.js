(() => {
  const section = document.querySelector("[data-positioned-fields]");
  if (!section) return;
  const list = section.querySelector("[data-form-list]");
  const template = section.querySelector("template[data-empty-form]");
  const total = section.querySelector('[name$="-TOTAL_FORMS"]');
  const add = section.querySelector("[data-add-form]");
  if (!list || !template || !total || !add) return;
  add.addEventListener("click", () => {
    const index = Number(total.value);
    const html = template.innerHTML.replaceAll("__prefix__", String(index));
    list.insertAdjacentHTML("beforeend", html);
    total.value = String(index + 1);
    list.lastElementChild?.querySelector("select, input")?.focus();
  });
})();
