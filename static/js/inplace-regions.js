/* 原地更新（使用者 2026-10-19）：上傳檔案、刪除或歸類附件後，不重新整理、不捲動。
   伺服器照舊驗證、寫稽核並導回原頁；前端把導回頁面的同 id 區塊（data-inplace-region）換進目前畫面，
   畫面位置以送出表單所在區塊為錨點維持不動，焦點留在原處，伺服器訊息改成浮動提示。
   沒有 JavaScript 時表單照常整頁送出（fallback）。 */
(function () {
  "use strict";

  const REGION = "[data-inplace-region]";
  // 由前端控制的狀態（目前分頁、進場動畫、固定頁首），換入伺服器版本時保留。
  const CLIENT_CLASSES = new Set(["is-active", "is-entering", "is-stuck", "is-just-updated"]);

  // 同一張表單在新舊畫面中的識別：送出網址＋非 CSRF 的隱藏欄位（例如文件類型）。
  function formKey(form) {
    if (!form) return "";
    const hidden = Array.from(form.querySelectorAll('input[type="hidden"]'))
      .filter((field) => field.name && field.name !== "csrfmiddlewaretoken")
      .map((field) => `${field.name}=${field.value}`)
      .sort();
    return [form.getAttribute("action") || "", ...hidden].join("|");
  }

  // 新狀態 class 取伺服器版本，前端狀態 class 沿用目前畫面。
  function mergeClassNames(current, fresh) {
    const keep = String(current || "").split(/\s+/).filter((name) => CLIENT_CLASSES.has(name));
    const next = String(fresh || "").split(/\s+/).filter((name) => name && !CLIENT_CLASSES.has(name));
    return [...next, ...keep].join(" ");
  }

  function sameDocument(a, b) {
    return String(a).split("#")[0] === String(b).split("#")[0];
  }

  // 判斷導回結果：Django 成功時一律導回；同網址重新顯示（200）表示驗證失敗；錯誤訊息表示未完成。
  function classify({status, contentType, requestUrl, responseUrl, currentPath, hasErrorMessage, hasSuccessMessage = false}) {
    if (status === 0) return "network";
    const finalUrl = new URL(responseUrl || requestUrl, requestUrl);
    // 登入逾時會被導到登入頁；不跟著換頁，免得還沒送出的輸入不見。
    if (/\/login\/?$/.test(finalUrl.pathname)) return "login";
    if (!String(contentType || "").includes("text/html")) return "failed";
    if (status >= 400) return status === 400 || status === 409 ? "invalid" : "failed";
    // 表單送回自己的網址（例如編輯頁存好後導回同頁）時看不出有沒有導回，改看伺服器的成功訊息。
    const redirected = !sameDocument(finalUrl.href, new URL(requestUrl).href);
    if (!redirected && !(hasSuccessMessage && !hasErrorMessage)) return "invalid";
    if (finalUrl.pathname !== currentPath) return "navigate";
    return hasErrorMessage ? "rejected" : "saved";
  }

  function failureText(status, traceId) {
    if (status === 0) return "網路中斷，資料尚未送出，請再試一次。";
    if (status === 403) return "登入或安全憑證已失效，請另開分頁登入後再試；目前的輸入都還在。";
    if (status === 413) return "檔案太大，請縮小檔案後再試。";
    if (status >= 500 && traceId) return `系統暫時無法完成（查修編號：${traceId}），請稍後再試。`;
    return "未能完成，請確認內容後再試一次。";
  }

  if (typeof module !== "undefined") module.exports = {formKey, mergeClassNames, classify, failureText, sameDocument};
  if (typeof document === "undefined") return;

  function parse(html) {
    return new DOMParser().parseFromString(html, "text/html");
  }

  function fieldKey(field) {
    const form = field.form || field.closest("form");
    const index = form ? Array.from(form.elements).filter((item) => item.name === field.name).indexOf(field) : 0;
    return field.id ? `#${field.id}` : `${formKey(form)}::${field.name}::${index}`;
  }

  function findField(root, key) {
    if (key.startsWith("#")) return root.querySelector(`[id="${CSS.escape(key.slice(1))}"]`);
    return Array.from(root.querySelectorAll("input, select, textarea")).find((field) => field.name && fieldKey(field) === key) || null;
  }

  // 其他區塊裡打到一半的文字與選項不因換入新版而消失；驗證失敗時連已選的檔案也保留。
  // 成功送出的那張表單不帶（伺服器已存好，換成乾淨的新表單）。
  function carryInputs(from, to, {files, skipKey = ""}) {
    from.querySelectorAll("input, select, textarea").forEach((field) => {
      if (!field.name || field.type === "hidden" || field.name === "csrfmiddlewaretoken") return;
      if (skipKey && formKey(field.form) === skipKey) return;
      const target = findField(to, fieldKey(field));
      if (!target || target.type !== field.type) return;
      if (field.type === "file") {
        if (files && field.files?.length) {
          try { target.files = field.files; } catch (_error) { /* 舊版瀏覽器不能指定檔案，請使用者重選 */ }
        }
        return;
      }
      if (field.type === "checkbox" || field.type === "radio") {
        if (field.checked !== field.defaultChecked) target.checked = field.checked;
      } else if (field instanceof HTMLSelectElement) {
        const changed = Array.from(field.options).some((option) => option.selected !== option.defaultSelected);
        if (changed) target.value = field.value;
      } else if (field.value !== field.defaultValue) {
        target.value = field.value;
      }
    });
  }

  function syncSteps(doc) {
    document.querySelectorAll("[data-step-key][id]").forEach((step) => {
      const fresh = doc.getElementById(step.id);
      if (!fresh) return;
      step.className = mergeClassNames(step.className, fresh.className);
      [".order-step__marker", ".order-step__heading", ".order-step__state"].forEach((selector) => {
        const now = step.querySelector(`:scope > .order-step__header ${selector}`);
        const next = fresh.querySelector(`:scope > .order-step__header ${selector}`);
        if (now && next && now.outerHTML !== next.outerHTML) now.replaceWith(document.importNode(next, true));
      });
    });
    document.querySelectorAll("[data-step-link]").forEach((tab) => {
      const fresh = tab.id ? doc.getElementById(tab.id) : null;
      if (!fresh) return;
      tab.className = mergeClassNames(tab.className, fresh.className);
      [".order-step-tab__marker", ".order-step-tab__state"].forEach((selector) => {
        const now = tab.querySelector(selector);
        const next = fresh.querySelector(selector);
        if (now && next && now.innerHTML !== next.innerHTML) now.innerHTML = next.innerHTML;
      });
    });
  }

  function flash(node) {
    if (!node || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    node.classList.remove("is-just-updated");
    void node.offsetWidth;
    node.classList.add("is-just-updated");
    window.setTimeout(() => node.classList.remove("is-just-updated"), 1600);
  }

  // 已載好的檔案縮圖（document-previews.js）直接搬進新區塊，避免縮圖重新載入時版面先縮後撐。
  function reusePreviews(from, to) {
    const built = Array.from(from.querySelectorAll("a[data-preview-name][data-preview-ready]"));
    to.querySelectorAll("a[data-preview-name]").forEach((link) => {
      const old = built.find((item) => item.getAttribute("href") === link.getAttribute("href") && item.dataset.previewName === link.dataset.previewName);
      const card = old?.parentElement?.classList.contains("document-card") ? old.parentElement : null;
      if (card) link.replaceWith(card);
    });
  }

  // 錨點區塊維持在原本的螢幕位置；上方內容沒變時 scrollY 完全不動。
  // 新檔案的縮圖稍後才載入，短時間內版面再變動時持續對齊，使用者一捲動就交還控制。
  function holdPosition(anchorId, anchorTop, scrollY) {
    const align = () => {
      const anchor = anchorId ? document.getElementById(anchorId) : null;
      const top = anchor && anchorTop !== null ? window.scrollY + anchor.getBoundingClientRect().top - anchorTop : scrollY;
      if (Math.abs(top - window.scrollY) >= 1) window.scrollTo({top, behavior: "instant"});
    };
    align();
    if (!("ResizeObserver" in window)) return;
    const observer = new ResizeObserver(align);
    const events = ["wheel", "touchstart", "keydown", "pointerdown"];
    const stop = () => {
      observer.disconnect();
      events.forEach((type) => window.removeEventListener(type, stop, true));
    };
    observer.observe(document.body);
    events.forEach((type) => window.addEventListener(type, stop, {capture: true, passive: true}));
    window.setTimeout(stop, 2000);
  }

  /* 把導回頁面的同 id 區塊換進目前畫面。only：只換送出表單所在的區塊（驗證失敗時）。 */
  function swap(doc, {source = null, only = false, keepFiles = false} = {}) {
    const sourceRegion = source?.closest?.(REGION) || null;
    const anchor = sourceRegion || source;
    const anchorId = anchor?.id || "";
    const anchorTop = anchor?.isConnected ? anchor.getBoundingClientRect().top : null;
    const sourceKey = formKey(source?.closest?.("form") || source);
    const active = document.activeElement;
    const activeKey = active && active !== document.body && active.name ? fieldKey(active) : "";
    const activeRegion = active?.closest?.(REGION)?.id || "";
    const scrollY = window.scrollY;

    const swapped = [];
    document.querySelectorAll(REGION).forEach((region) => {
      if (!region.id || (only && region !== sourceRegion)) return;
      const fresh = doc.getElementById(region.id);
      if (!fresh || !fresh.matches(REGION)) return;
      const imported = document.importNode(fresh, true);
      if (region.isEqualNode(imported)) return;
      carryInputs(region, imported, {files: keepFiles, skipKey: keepFiles ? "" : sourceKey});
      reusePreviews(region, imported);
      region.replaceWith(imported);
      swapped.push(imported);
    });
    if (!only) {
      syncSteps(doc);
      if (doc.title && doc.title !== document.title) document.title = doc.title;
    }

    holdPosition(anchorId, anchorTop, scrollY);

    // 焦點：原本在被換掉的區塊裡，就移到新版同一個欄位；上傳中控制項停用而失去焦點時，回到同一張表單。
    const counterpart = sourceKey
      ? swapped.flatMap((region) => Array.from(region.querySelectorAll("form"))).find((form) => formKey(form) === sourceKey)
      : null;
    // 上傳表單回到選檔按鈕（不是 Django「清除」勾選框），其他表單回到第一個可操作的控制項。
    const firstControl = (root) => root?.querySelector('input[type=file]:not([disabled])')
      || root?.querySelector('button:not([disabled]), input:not([type=hidden]):not([type=checkbox]):not([disabled]), select:not([disabled])');
    let target = null;
    if (activeRegion && !active.isConnected) {
      const region = document.getElementById(activeRegion);
      target = (region && activeKey && findField(region, activeKey)) || firstControl(counterpart) || region;
    } else if ((!active || active === document.body || !active.isConnected) && sourceRegion) {
      target = firstControl(counterpart) || document.getElementById(sourceRegion.id);
    }
    if (target) {
      if (target.matches(REGION) && !target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
      target.focus({preventScroll: true});
    }
    if (counterpart) flash(counterpart.closest("[data-upload-row], .registration-document-row, .slot-row, article") || counterpart);
    document.dispatchEvent(new CustomEvent("inplace:updated", {detail: {regions: swapped, doc}}));
    return swapped;
  }

  function messagesContainer() {
    let container = document.querySelector("main .messages");
    if (!container) {
      container = document.createElement("div");
      container.className = "messages";
      container.setAttribute("aria-live", "polite");
      document.querySelector("main")?.prepend(container);
    }
    return container;
  }

  function toast(level, text) {
    if (!text) return;
    const node = document.createElement("div");
    node.className = `message ${level}`;
    node.dataset.messageToast = "";
    const span = document.createElement("span");
    span.className = "message-text";
    span.textContent = text;
    const close = document.createElement("button");
    close.className = "message-close";
    close.type = "button";
    close.setAttribute("aria-label", "關閉提示");
    close.dataset.messageClose = "";
    close.textContent = "×";
    node.append(span, close);
    messagesContainer().append(node);
    if (window.DMISToasts?.bind) window.DMISToasts.bind(node);
    else close.addEventListener("click", () => node.remove());
  }

  function showMessages(doc) {
    doc.querySelectorAll(".messages [data-message-toast]").forEach((item) => {
      const level = ["error", "warning", "success", "info"].find((name) => item.classList.contains(name)) || "info";
      toast(level, item.querySelector(".message-text")?.textContent.trim() || item.textContent.trim());
    });
  }

  function errorText(doc) {
    const items = Array.from(doc.querySelectorAll(".messages .message.error .message-text, .messages .message.error"));
    return items.map((item) => item.textContent.replace("×", "").trim()).find(Boolean) || "";
  }

  // 上傳或儲存狀態列：沿用文件上傳進度樣式，放在表單所屬的列或表單本身下方。
  function progressPanel(form) {
    const row = form.closest(".registration-document-row, [data-upload-row]") || form;
    let panel = row.querySelector(":scope > [data-document-upload-progress]");
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

  function setProgress(panel, value, label, state) {
    panel.hidden = false;
    panel.classList.toggle("is-complete", state === "complete");
    panel.classList.toggle("is-error", state === "error");
    panel.setAttribute("role", state === "error" ? "alert" : "status");
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

  // form-feedback.js 送出時鎖住按鈕等待換頁；原地送出完成後要解開。
  function release(form) {
    form.dataset.submitting = "false";
    form.removeAttribute("aria-busy");
    form.classList.remove("is-uploading");
    form.querySelectorAll(".is-submitting").forEach((button) => {
      button.classList.remove("is-submitting");
      button.removeAttribute("aria-disabled");
      if (button.dataset.originalLabel) button.textContent = button.dataset.originalLabel;
    });
  }

  async function refresh(url, options = {}) {
    const response = await fetch(url, {headers: {"X-Inplace-Refresh": "1", Accept: "text/html"}, credentials: "same-origin"});
    if (!response.ok || !String(response.headers.get("Content-Type")).includes("text/html")) throw new Error("refresh failed");
    const doc = parse(await response.text());
    const swapped = swap(doc, options);
    showMessages(doc);
    return swapped;
  }

  // 完成交車、訂金入帳等跨步驟的動作：整頁內容都會變（收款明細、鎖定狀態），
  // 重新載入後回到同一個畫面位置，不跳回頂端（order-workspace.js 讀取）。
  const RESTORE_KEY = "dmis:inplace-restore";
  const MESSAGES_KEY = "dmis:inplace-messages";
  // 導回頁面帶的訊息已被這次請求取走，存起來在換頁或重新載入後顯示。
  function stashMessages(doc, path) {
    const notes = doc ? Array.from(doc.querySelectorAll(".messages [data-message-toast]")).map((item) => ({
      level: ["error", "warning", "success", "info"].find((name) => item.classList.contains(name)) || "info",
      text: (item.querySelector(".message-text") || item).textContent.trim(),
    })) : [];
    try {
      if (notes.length) window.sessionStorage.setItem(MESSAGES_KEY, JSON.stringify({path, notes, at: Date.now()}));
    } catch (_error) { /* 無法暫存時略過提示 */ }
  }
  function reloadInPlace(source, doc = null) {
    stashMessages(doc, window.location.pathname);
    const anchor = source?.closest?.(REGION) || source?.closest?.("[id]");
    const tab = source?.closest?.("[data-step-key]")?.dataset.stepKey || "";
    try {
      window.sessionStorage.setItem(RESTORE_KEY, JSON.stringify({
        path: window.location.pathname, y: window.scrollY, tab,
        anchor: anchor?.id || "", offset: anchor ? anchor.getBoundingClientRect().top : 0, at: Date.now(),
      }));
    } catch (_error) { /* 無法暫存位置時仍照常重新載入 */ }
    const url = new URL(window.location.href);
    url.hash = "";
    window.location.replace(url.href);
  }
  function takeRestore() {
    try {
      const raw = window.sessionStorage.getItem(RESTORE_KEY);
      window.sessionStorage.removeItem(RESTORE_KEY);
      const data = raw ? JSON.parse(raw) : null;
      if (!data || data.path !== window.location.pathname || Date.now() - data.at > 30000) return null;
      return data;
    } catch (_error) {
      return null;
    }
  }

  function submit(form, submitter) {
    const data = new FormData(form);
    if (submitter?.name) data.append(submitter.name, submitter.value);
    const files = Array.from(form.querySelectorAll('input[type="file"]')).some((input) => input.files?.length);
    const panel = progressPanel(form);
    form.classList.add("is-uploading");
    form.setAttribute("aria-busy", "true");
    setProgress(panel, files ? 0 : null, files ? "正在上傳檔案…" : "正在儲存…");

    const requestUrl = new URL(form.getAttribute("action") || window.location.href, window.location.href).href;
    const request = new XMLHttpRequest();
    request.open((form.getAttribute("method") || "POST").toUpperCase(), requestUrl, true);
    request.responseType = "text";
    request.timeout = 120000;
    request.setRequestHeader("Accept", "text/html");
    request.setRequestHeader("X-Inplace-Form", "1");
    if (files) {
      request.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) setProgress(panel, (event.loaded / event.total) * 100, "正在上傳檔案…");
        else setProgress(panel, null, "正在上傳檔案…");
      });
      request.upload.addEventListener("load", () => setProgress(panel, 100, "檔案已傳送，系統處理中…"));
    }
    const fail = (text) => {
      release(form);
      setProgress(panel, 0, text, "error");
    };
    request.addEventListener("load", () => {
      const html = request.responseText || "";
      const doc = parse(html);
      const outcome = classify({
        status: request.status,
        contentType: request.getResponseHeader("Content-Type"),
        requestUrl,
        responseUrl: request.responseURL,
        currentPath: window.location.pathname,
        hasErrorMessage: Boolean(doc.querySelector(".messages .message.error")),
        hasSuccessMessage: Boolean(doc.querySelector(".messages .message.success")),
      });
      if (outcome === "navigate") {
        stashMessages(doc, new URL(request.responseURL).pathname);
        window.location.assign(request.responseURL);
        return;
      }
      if (outcome === "login") {
        fail("登入已逾時，請另開分頁重新登入後再送出；目前的輸入都還在。");
        return;
      }
      if (outcome === "rejected") {
        fail(errorText(doc) || failureText(request.status));
        return;
      }
      if (outcome === "invalid") {
        // 伺服器重新顯示含錯誤說明的表單：只換這個區塊，保留已填的值與已選的檔案。
        // 部分已存（伺服器帶警告，例如車色圖片連結下載失敗、其他設定已存）時不再帶回已選檔案，免得重複上傳。
        const partial = Boolean(doc.querySelector(".messages .message.warning"));
        const replaced = form.closest(REGION) && swap(doc, {source: form, only: true, keepFiles: !partial}).length;
        if (!replaced) fail(errorText(doc) || failureText(request.status, request.getResponseHeader("X-Request-ID")));
        else release(form);
        showMessages(doc);
        return;
      }
      if (outcome !== "saved") {
        fail(errorText(doc) || failureText(request.status, request.getResponseHeader("X-Request-ID")));
        return;
      }
      if (form.dataset.inplaceSuccess === "reload") {
        reloadInPlace(form, doc);
        return;
      }
      setProgress(panel, 100, "已完成", "complete");
      swap(doc, {source: form});
      showMessages(doc);
      if (form.isConnected) {
        release(form);
        form.querySelectorAll('input[type="file"]').forEach((input) => { input.value = ""; });
        window.setTimeout(() => { panel.hidden = true; }, 1600);
      }
    });
    request.addEventListener("timeout", () => fail("回應逾時，結果尚未確認；請稍候查看清單，勿重複送出。"));
    request.addEventListener("error", () => fail(failureText(0)));
    request.send(data);
  }

  // 掛在 window：在 form-feedback.js 的確認對話框（data-confirm）與重複送出鎖之後才接手。
  window.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches("form[data-inplace-form]") || event.defaultPrevented) return;
    event.preventDefault();
    submit(form, event.submitter);
  });

  document.addEventListener("DOMContentLoaded", () => {
    try {
      const raw = window.sessionStorage.getItem(MESSAGES_KEY);
      window.sessionStorage.removeItem(MESSAGES_KEY);
      const data = raw ? JSON.parse(raw) : null;
      if (data && data.path === window.location.pathname && Date.now() - data.at < 30000) {
        data.notes.forEach((note) => toast(note.level, note.text));
      }
    } catch (_error) { /* 沒有暫存的提示 */ }
  });

  window.DMISInplace = {swap, refresh, toast, showMessages, progressPanel, setProgress, release, reloadInPlace, takeRestore, formKey};
})();
