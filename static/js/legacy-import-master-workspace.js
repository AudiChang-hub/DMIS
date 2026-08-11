(() => {
  const progressCard = document.querySelector("[data-import-progress-url]");
  if (progressCard) {
    const progressBar = progressCard.querySelector("[data-import-progress-bar]");
    const progressPercent = progressCard.querySelector("[data-import-progress-percent]");
    const progressText = progressCard.querySelector("[data-import-progress-text]");
    const progressTrack = progressCard.querySelector("[role='progressbar']");
    let pollTimer;
    const poll = async () => {
      try {
        const response = await fetch(progressCard.dataset.importProgressUrl, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        if (!response.ok) throw new Error("無法讀取匯入進度");
        const data = await response.json();
        const percent = Math.max(0, Math.min(100, Number(data.percent) || 0));
        if (progressBar) progressBar.style.width = `${percent}%`;
        if (progressPercent) progressPercent.textContent = `${percent}%`;
        if (progressTrack) progressTrack.setAttribute("aria-valuenow", String(percent));
        if (progressText) {
          progressText.textContent = `已處理 ${data.completed}／${data.total} 筆，完成後畫面會自動更新。`;
        }
        if (data.finished) {
          window.location.reload();
          return;
        }
      } catch (_error) {
        if (progressText) progressText.textContent = "暫時無法更新進度，背景匯入仍會繼續；系統稍後會再試。";
      }
      pollTimer = window.setTimeout(poll, 2000);
    };
    pollTimer = window.setTimeout(poll, 1000);
    window.addEventListener("pagehide", () => window.clearTimeout(pollTimer), { once: true });
  }

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
    const previewTarget = dialog.querySelector("[data-master-preview-target]");
    if (previewTarget) {
      const previewTemplate = document.getElementById(button.dataset.masterPreviewId || "");
      previewTarget.replaceChildren();
      if (previewTemplate?.content) {
        previewTarget.append(previewTemplate.content.cloneNode(true));
      }
    }

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
