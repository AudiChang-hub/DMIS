(function () {
  "use strict";

  function createProgress(form) {
    const row = form.closest(".registration-document-row") || form;
    let panel = row.querySelector("[data-document-upload-progress]");
    if (panel) return panel;

    panel = document.createElement("div");
    panel.className = "document-upload-progress";
    panel.dataset.documentUploadProgress = "";
    panel.setAttribute("role", "status");
    panel.setAttribute("aria-live", "polite");
    panel.hidden = true;

    const summary = document.createElement("div");
    summary.className = "document-upload-progress__summary";
    const label = document.createElement("span");
    label.dataset.uploadProgressLabel = "";
    const percent = document.createElement("strong");
    percent.dataset.uploadProgressPercent = "";
    summary.append(label, percent);

    const meter = document.createElement("progress");
    meter.max = 100;
    meter.value = 0;
    meter.dataset.uploadProgressMeter = "";
    panel.append(summary, meter);
    row.append(panel);
    return panel;
  }

  function updateProgress(panel, value, label, state) {
    panel.hidden = false;
    panel.classList.toggle("is-complete", state === "complete");
    panel.classList.toggle("is-error", state === "error");
    const meter = panel.querySelector("[data-upload-progress-meter]");
    const percent = panel.querySelector("[data-upload-progress-percent]");
    if (value === null) {
      meter.removeAttribute("value");
      percent.textContent = "";
    } else {
      const normalized = Math.max(0, Math.min(100, Math.round(value)));
      meter.value = normalized;
      percent.textContent = `${normalized}%`;
    }
    panel.querySelector("[data-upload-progress-label]").textContent = label;
  }

  function restoreForm(form) {
    form.classList.remove("is-uploading");
    form.removeAttribute("aria-busy");
    form.querySelectorAll("input, button").forEach((control) => {
      control.disabled = false;
    });
    form.dataset.uploading = "";
  }

  function upload(form) {
    if (form.dataset.uploading === "true" || !form.reportValidity()) return;
    const fileInput = form.querySelector('input[type="file"]');
    if (!fileInput || !fileInput.files.length) return;
    const formData = new FormData(form);

    form.dataset.uploading = "true";
    form.classList.add("is-uploading");
    form.setAttribute("aria-busy", "true");
    form.querySelectorAll("input, button").forEach((control) => {
      control.disabled = true;
    });

    const panel = createProgress(form);
    updateProgress(panel, 0, "準備上傳…");

    const request = new XMLHttpRequest();
    request.open("POST", form.action, true);
    request.responseType = "json";
    request.timeout = 120000;
    request.setRequestHeader("Accept", "application/json");
    request.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    const csrfToken = form.querySelector('[name="csrfmiddlewaretoken"]');
    if (csrfToken) request.setRequestHeader("X-CSRFToken", csrfToken.value);

    request.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) {
        updateProgress(panel, null, "正在上傳檔案…");
        return;
      }
      updateProgress(panel, (event.loaded / event.total) * 100, "正在上傳檔案…");
    });
    request.upload.addEventListener("load", () => {
      updateProgress(panel, 100, "檔案已傳送，系統處理中…");
    });
    request.addEventListener("load", () => {
      const payload = request.response || {};
      if (request.status >= 200 && request.status < 300 && payload.ok) {
        updateProgress(panel, 100, payload.message || "上傳完成", "complete");
        window.setTimeout(() => {
          window.location.assign(payload.redirect_url || window.location.href);
        }, 250);
        return;
      }
      restoreForm(form);
      fileInput.value = "";
      const traceId = request.getResponseHeader("X-Request-ID");
      let fallback = "上傳失敗，請確認檔案後再試一次。";
      if (request.status === 403) {
        fallback = "登入或安全憑證已失效，請重新整理頁面後再試。";
      } else if (request.status === 413) {
        fallback = "檔案太大，請縮小檔案後再試。";
      } else if (request.status >= 500 && traceId) {
        fallback = `系統暫時無法完成上傳（查修編號：${traceId}），請稍後再試。`;
      }
      updateProgress(
        panel,
        0,
        payload.message || fallback,
        "error"
      );
    });
    request.addEventListener("timeout", () => {
      restoreForm(form);
      fileInput.value = "";
      updateProgress(panel, 0, "上傳逾時，請確認網路後再試一次。", "error");
    });
    request.addEventListener("error", () => {
      restoreForm(form);
      fileInput.value = "";
      updateProgress(panel, 0, "網路中斷，檔案尚未上傳，請再試一次。", "error");
    });
    request.send(formData);
  }

  document.querySelectorAll("form[data-document-upload]").forEach((form) => {
    const input = form.querySelector('input[type="file"]');
    if (!input) return;
    if (form.hasAttribute("data-auto-upload")) {
      input.addEventListener("change", () => upload(form));
    }
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      upload(form);
    });
  });
})();
