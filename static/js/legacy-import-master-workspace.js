(() => {
  const openDialog = (button) => {
    const dialog = document.getElementById(button.dataset.masterDialog || "");
    if (!dialog) return;
    const sourceValue = button.dataset.sourceValue || "";
    dialog.querySelectorAll("[data-master-source-input]").forEach((input) => {
      input.value = sourceValue;
    });
    dialog.querySelectorAll("[data-master-source-label]").forEach((label) => {
      label.textContent = sourceValue;
    });

    if (dialog.id === "vehicle-model-create-dialog") {
      const modelNumber = dialog.querySelector("#id_model-create-model_number");
      const modelName = dialog.querySelector("#id_model-create-name");
      const colors = dialog.querySelector("#id_model-create-colors");
      if (modelNumber) modelNumber.value = sourceValue;
      if (modelName) modelName.value = sourceValue;
      if (colors) colors.value = button.dataset.colors || "";
    }
    if (dialog.id === "sales-source-create-dialog") {
      const sourceName = dialog.querySelector("#id_source-create-name");
      if (sourceName) sourceName.value = sourceValue;
    }

    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  };

  document.querySelectorAll("[data-master-dialog]").forEach((button) => {
    button.addEventListener("click", () => openDialog(button));
  });
  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog")?.close());
  });
  document.querySelectorAll(".import-master-dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });
})();
