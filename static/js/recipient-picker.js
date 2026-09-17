"use strict";
document.querySelectorAll("[data-recipient-picker]").forEach(picker => {
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
