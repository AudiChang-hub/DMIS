(function () {
  "use strict";

  function createProgress(form) {
    const row = form.closest(".registration-document-row, [data-upload-row]") || form;
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
    if (value === null || state === "error") {
      if (value === null) meter.removeAttribute("value");
      else meter.value = 0;
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
        updateProgress(panel, 100, "上傳完成，正在更新清單…", "complete");
        settle(form, panel, payload.redirect_url, payload.message || "上傳完成");
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

  function sendOne(form, file, onProgress) {
    // 逐檔上傳：代理伺服器限制單次請求大小，多個附件分開送才不會整批失敗。
    return new Promise((resolve) => {
      const formData = new FormData();
      form.querySelectorAll("input:not([type=file]), textarea, select").forEach((field) => {
        if (field.name) formData.append(field.name, field.value);
      });
      formData.append(form.querySelector('input[type="file"]').name, file);
      const request = new XMLHttpRequest();
      request.open("POST", form.action, true);
      request.responseType = "json";
      request.timeout = 120000;
      request.setRequestHeader("Accept", "application/json");
      request.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      const csrfToken = form.querySelector('[name="csrfmiddlewaretoken"]');
      if (csrfToken) request.setRequestHeader("X-CSRFToken", csrfToken.value);
      request.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) onProgress(event.loaded / event.total);
      });
      request.addEventListener("load", () => {
        const payload = request.response || {};
        let message = payload.message;
        if (!message && request.status === 413) message = "檔案太大，請縮小檔案後再試。";
        if (!message && request.status === 403) message = "登入或安全憑證已失效，請重新整理頁面後再試。";
        resolve({ ok: request.status >= 200 && request.status < 300 && payload.ok, message, redirect: payload.redirect_url });
      });
      request.addEventListener("timeout", () => resolve({ ok: false, message: "上傳逾時，請確認網路後再試一次。" }));
      request.addEventListener("error", () => resolve({ ok: false, message: "網路中斷，檔案尚未上傳，請再試一次。" }));
      request.send(formData);
    });
  }

  async function uploadEach(form) {
    if (form.dataset.uploading === "true" || !form.reportValidity()) return;
    const fileInput = form.querySelector('input[type="file"]');
    const files = Array.from(fileInput?.files || []);
    if (!files.length) return;
    form.dataset.uploading = "true";
    form.classList.add("is-uploading");
    form.setAttribute("aria-busy", "true");
    const panel = createProgress(form);
    let redirect = null;
    for (let index = 0; index < files.length; index += 1) {
      const prefix = files.length > 1 ? `第 ${index + 1}／${files.length} 個：` : "";
      updateProgress(panel, (index / files.length) * 100, `${prefix}${files[index].name}`);
      form.querySelectorAll("input, button").forEach((control) => { control.disabled = true; });
      const result = await sendOne(form, files[index], (ratio) => {
        updateProgress(panel, ((index + ratio) / files.length) * 100, `${prefix}${files[index].name}`);
      });
      if (!result.ok) {
        restoreForm(form);
        fileInput.value = "";
        fileInput.dispatchEvent(new Event("change"));
        const done = index ? `前 ${index} 個已上傳；` : "";
        const reason = `${done}${result.message || "上傳失敗，請確認檔案後再試一次。"}`;
        updateProgress(panel, 0, reason, "error");
        // 已上傳的檔案原地補進清單；失敗原因改用提示保留，不重新整理頁面。
        if (index) settle(form, panel, result.redirect || redirect, reason, "error");
        return;
      }
      redirect = result.redirect || redirect;
    }
    updateProgress(panel, 100, `已上傳 ${files.length} 個附件，正在更新清單…`, "complete");
    settle(form, panel, redirect, `已上傳 ${files.length} 個附件`);
  }

  // 上傳成功後不重新整理：取回導回頁面，只換掉有變動的區塊（inplace-regions.js），畫面與焦點留在原處。
  function settle(form, panel, redirectUrl, message, level = "success") {
    const inplace = window.DMISInplace;
    const url = new URL(redirectUrl || window.location.href, window.location.href);
    if (!inplace || url.pathname !== window.location.pathname) {
      window.location.assign(url.href);
      return;
    }
    inplace.refresh(url.href, {source: form})
      .then(() => {
        inplace.toast(level, message);
        if (form.isConnected) {
          restoreForm(form);
          form.querySelector('input[type="file"]').value = "";
          if (level !== "error") window.setTimeout(() => { panel.hidden = true; }, 1600);
        }
      })
      .catch(() => {
        if (form.isConnected) restoreForm(form);
        updateProgress(panel, 100, `${message}；清單未能自動更新，請重新整理頁面查看。`, "error");
      });
  }

  function bind(root) {
    // 歸類到已有檔案的文件格時先確認，避免不小心替換掉原檔。
    root.querySelectorAll("[data-classify-form]:not([data-upload-bound])").forEach((form) => {
      form.dataset.uploadBound = "";
      form.addEventListener("submit", (event) => {
        const option = form.querySelector("select")?.selectedOptions[0];
        if (!option?.dataset.replace) return;
        const name = form.dataset.fileName || "這個檔案";
        const target = option.textContent.replace("（已有，將替換）", "");
        if (!window.confirm(`「${target}」已經有檔案，歸類「${name}」後會替換原檔案，確定嗎？`)) event.preventDefault();
      });
    });

    // 全部下載：伺服器打包需要幾秒，期間顯示提示並避免重複點擊。
    root.querySelectorAll("[data-zip-download]:not([data-upload-bound])").forEach((link) => {
      link.dataset.uploadBound = "";
      const label = link.querySelector("[data-zip-label]");
      const initial = label ? label.textContent : "";
      link.addEventListener("click", () => {
        if (link.classList.contains("is-preparing")) return;
        link.classList.add("is-preparing");
        link.setAttribute("aria-busy", "true");
        if (label) label.textContent = "正在打包，下載即將開始…";
        window.setTimeout(() => {
          link.classList.remove("is-preparing");
          link.removeAttribute("aria-busy");
          if (label) label.textContent = initial;
        }, 8000);
      });
    });

    root.querySelectorAll("form[data-document-upload]:not([data-upload-bound])").forEach((form) => {
      const input = form.querySelector('input[type="file"]');
      if (!input) return;
      form.dataset.uploadBound = "";
      if (form.hasAttribute("data-auto-upload")) {
        input.addEventListener("change", () => upload(form));
      }
      // 多檔上傳區：顯示已選的檔案，拖曳進來時加上提示樣式。
      const summary = form.querySelector("[data-file-summary]");
      if (summary) {
        const initial = summary.textContent;
        const drop = input.closest("label");
        input.addEventListener("change", () => {
          const names = Array.from(input.files || []).map((file) => file.name);
          summary.textContent = names.length
            ? `已選 ${names.length} 個：${names.slice(0, 3).join("、")}${names.length > 3 ? "…" : ""}`
            : initial;
        });
        ["dragenter", "dragover"].forEach((type) => input.addEventListener(type, () => drop?.classList.add("is-dragging")));
        ["dragleave", "drop"].forEach((type) => input.addEventListener(type, () => drop?.classList.remove("is-dragging")));
      }
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (form.hasAttribute("data-upload-each")) uploadEach(form);
        else upload(form);
      });
    });
  }

  bind(document);
  document.addEventListener("inplace:updated", (event) => {
    event.detail.regions.forEach((region) => bind(region));
  });
})();
