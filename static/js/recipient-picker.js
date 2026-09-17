"use strict";
document.querySelectorAll("[data-recipient-picker]").forEach(picker => {
  const audience = picker.closest('form')?.querySelector('[name="audience"]');
  if (audience && picker.dataset.audience) {
    const syncAudience = () => { picker.hidden = audience.value !== picker.dataset.audience; };
    audience.addEventListener('change', syncAudience);
    syncAudience();
  }
  const search = picker.querySelector("[data-recipient-search]");
  const boxes = [...picker.querySelectorAll('input[type="checkbox"]')];
  search.addEventListener("input", () => {
    const query = search.value.trim().toLocaleLowerCase();
    boxes.forEach(box => { box.closest("label").parentElement.hidden = !box.closest("label").textContent.toLocaleLowerCase().includes(query); });
  });
  picker.querySelectorAll("[data-recipient-select]").forEach(button => button.addEventListener("click", () => {
    boxes.filter(box => !box.closest("label").parentElement.hidden).forEach(box => { box.checked = button.dataset.recipientSelect === "yes"; });
  }));
});
