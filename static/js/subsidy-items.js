document.addEventListener("DOMContentLoaded", () => {
  const section = document.querySelector("[data-subsidy-items]");
  if (!section) return;
  const list = section.querySelector("[data-form-list]");
  const template = section.querySelector("[data-empty-form]");
  const total = section.querySelector("input[name$='-TOTAL_FORMS']");
  section.querySelector("[data-add-form]")?.addEventListener("click", () => {
    const index = Number(total.value);
    const fragment = template.content.cloneNode(true);
    fragment.querySelectorAll("[name],[id],[for]").forEach(element => {
      for (const attribute of ["name", "id", "for"]) {
        if (element.hasAttribute(attribute)) {
          element.setAttribute(attribute, element.getAttribute(attribute).replaceAll("__prefix__", String(index)));
        }
      }
    });
    list.append(fragment);
    total.value = index + 1;
  });
  list.addEventListener("change", event => {
    if (!event.target.matches("input[name$='-DELETE']")) return;
    event.target.closest("[data-form-row]")?.classList.toggle("is-deleted", event.target.checked);
  });
});
