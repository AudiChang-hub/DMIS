// 其他補助文件一次多選、拖曳多檔上傳（使用者 2026-10-22 T-94）：選好就逐檔送出、各存一筆，
// 領牌步驟的「其他領牌相關資料」（T-101）共用同一個元件：form[data-multi-upload] 都適用。
// 每個檔案顯示進度與成功／失敗；全部傳完用 DMISInplace.refresh 原地換上新清單，不整頁重整、不跳位（比照 T-14）。
// 大小與格式先在這裡擋一次，伺服器仍逐檔檢查（20 MB、只收白名單格式，執行檔一律不收）。
(() => {
  const FORM = "form[data-multi-upload]";
  let state = null; // {queue, list, summary, items: [], running, done, failed}

  const formatSize = (bytes) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

  function precheck(input, file) {
    const max = Number(input.dataset.maxBytes || 0);
    if (!file.size) return "檔案是空的";
    if (max && file.size > max) return `超過 ${Math.round(max / 1048576)} MB 上限`;
    const accepted = (input.accept || "").split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);
    if (!accepted.length) return "";
    const name = file.name.toLowerCase();
    const type = (file.type || "").toLowerCase();
    const ok = accepted.some((rule) => (rule.startsWith(".") ? name.endsWith(rule) : type === rule));
    return ok ? "" : "格式不支援（可上傳圖片、PDF、Office 文件、文字檔）";
  }

  function ensureQueue(form) {
    if (state && state.form === form && state.queue.isConnected) return state;
    const queue = form.querySelector("[data-upload-queue]");
    const summary = document.createElement("p");
    summary.className = "upload-queue__summary";
    summary.setAttribute("role", "status");
    summary.setAttribute("aria-live", "polite");
    const list = document.createElement("ol");
    list.className = "upload-queue__list";
    queue.replaceChildren(summary, list);
    state = {form, queue, summary, list, items: [], running: false};
    return state;
  }

  function addItem(current, file, error) {
    const item = document.createElement("li");
    item.className = "upload-queue__item";
    const name = document.createElement("span");
    name.className = "upload-queue__name";
    name.textContent = file.name;
    name.title = file.name;
    const size = document.createElement("span");
    size.className = "upload-queue__size";
    size.textContent = formatSize(file.size);
    const meter = document.createElement("progress");
    meter.max = 100;
    meter.value = 0;
    meter.setAttribute("aria-label", `${file.name} 上傳進度`);
    const status = document.createElement("span");
    status.className = "upload-queue__status";
    item.append(name, size, meter, status);
    current.list.append(item);
    const entry = {file, item, meter, status, error};
    setItem(entry, error ? "error" : "waiting", error || "等待上傳");
    current.items.push(entry);
    return entry;
  }

  function setItem(entry, itemState, text, value) {
    entry.state = itemState;
    entry.item.dataset.state = itemState;
    entry.status.textContent = text;
    if (typeof value === "number") entry.meter.value = value;
    else if (itemState === "done") entry.meter.value = 100;
    else if (itemState === "uploading") entry.meter.removeAttribute("value");
  }

  function summarize(current) {
    const total = current.items.length;
    const done = current.items.filter((entry) => entry.state === "done").length;
    const failed = current.items.filter((entry) => entry.state === "error").length;
    const pending = total - done - failed;
    current.queue.hidden = total === 0;
    current.queue.dataset.state = pending ? "running" : failed ? "partial" : "complete";
    // 進度只算真的要送出的檔案；選檔時就擋下的（太大、格式不符）不算在「第幾個」裡。
    const sendable = current.items.filter((entry) => !entry.error);
    const finished = sendable.filter((entry) => entry.state === "done" || entry.state === "error").length;
    current.summary.textContent = pending
      ? `正在上傳第 ${finished + 1}／${sendable.length} 個檔案…`
      : failed
        ? `已上傳 ${done} 份，${failed} 份沒有上傳，請看下方原因`
        : `${done} 份文件都已上傳`;
  }

  function send(form, entry) {
    return new Promise((resolve) => {
      const data = new FormData();
      const token = form.querySelector("[name=csrfmiddlewaretoken]");
      if (token) data.append("csrfmiddlewaretoken", token.value);
      data.append("document_type", form.querySelector("[name=document_type]")?.value || "other");
      data.append("file", entry.file, entry.file.name);
      const request = new XMLHttpRequest();
      request.open("POST", form.action, true);
      request.timeout = 120000;
      request.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      request.setRequestHeader("Accept", "application/json");
      request.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) {
          const value = Math.round((event.loaded / event.total) * 100);
          setItem(entry, "uploading", `上傳中 ${value}%`, value);
        }
      });
      request.upload.addEventListener("load", () => setItem(entry, "uploading", "處理中…", 100));
      const finish = (ok, text) => { setItem(entry, ok ? "done" : "error", text); resolve(ok); };
      request.addEventListener("load", () => {
        if (/\/(accounts\/)?login/.test(request.responseURL || "")) return finish(false, "登入已逾時，請重新登入後再上傳");
        let payload = null;
        try { payload = JSON.parse(request.responseText); } catch (_error) { /* 不是 JSON：權限或伺服器錯誤 */ }
        if (request.status >= 200 && request.status < 300 && payload?.ok) return finish(true, "✓ 已上傳");
        const reason = (payload?.message || "").replace(/^[^：]*文件上傳失敗：/, "");
        finish(false, reason || (request.status === 403 ? "沒有權限或頁面已過期，請重新整理後再試" : `上傳失敗（${request.status || "連線中斷"}）`));
      });
      request.addEventListener("timeout", () => finish(false, "回應逾時，請稍候查看清單，確認沒有再重傳"));
      request.addEventListener("error", () => finish(false, "網路中斷，沒有上傳"));
      setItem(entry, "uploading", "上傳中 0%", 0);
      request.send(data);
    });
  }

  async function run(current) {
    if (current.running) return;
    current.running = true;
    current.form.setAttribute("aria-busy", "true");
    let uploaded = false;
    for (let entry = next(current); entry; entry = next(current)) {
      summarize(current);
      uploaded = (await send(current.form, entry)) || uploaded;
    }
    current.running = false;
    current.form.removeAttribute("aria-busy");
    summarize(current);
    if (uploaded) await refreshList(current);
  }
  const next = (current) => current.items.find((entry) => entry.state === "waiting");

  // 原地換上新清單：表單也在同一區塊裡，換完把這次的上傳結果搬到新表單，結果不會消失。
  async function refreshList(current) {
    const {queue} = current;
    // 選檔後焦點在選檔欄位；換區塊後放回新的上傳區，鍵盤使用者可以接著再選。
    const hadFocus = current.form.contains(document.activeElement);
    try {
      await window.DMISInplace?.refresh?.(window.location.href);
    } catch (_error) {
      current.summary.textContent += "（清單沒有自動更新，請重新整理頁面查看）";
    }
    const fresh = document.querySelector(`${FORM}#${current.form.id}`);
    if (fresh && fresh !== current.form) {
      fresh.querySelector("[data-upload-queue]")?.replaceWith(queue);
      current.form = fresh;
      ready(fresh);
      const active = document.activeElement;
      if (hadFocus && (!active || active === document.body)) fresh.querySelector('input[type="file"]')?.focus({preventScroll: true});
    }
    // 成功的列留一下讓人看到結果再收起；失敗的列保留，直到下次上傳。
    window.setTimeout(() => {
      current.items.filter((entry) => entry.state === "done").forEach((entry) => entry.item.classList.add("is-leaving"));
      window.setTimeout(() => {
        current.items = current.items.filter((entry) => {
          if (entry.state !== "done") return true;
          entry.item.remove();
          return false;
        });
        if (!current.running) summarize(current);
        if (!current.items.length) queue.hidden = true;
      }, 260);
    }, 3200);
  }

  function enqueue(form, files) {
    if (!files?.length) return;
    const input = form.querySelector('input[type="file"]');
    const current = ensureQueue(form);
    // 上一批失敗的列在新一批開始時清掉，畫面只留這一批的結果。
    if (!current.running) {
      current.items.filter((entry) => entry.state === "error").forEach((entry) => entry.item.remove());
      current.items = current.items.filter((entry) => entry.state !== "error");
    }
    Array.from(files).forEach((file) => addItem(current, file, precheck(input, file)));
    if (input) input.value = "";
    summarize(current);
    run(current);
  }

  function ready(form) {
    if (form.dataset.multiUploadReady) return;
    form.dataset.multiUploadReady = "true";
    const input = form.querySelector('input[type="file"]');
    if (input) input.required = false; // 選好就上傳，不需要瀏覽器的必填檢查
  }

  document.addEventListener("change", (event) => {
    const input = event.target;
    const form = input.closest?.(FORM);
    if (form && input.type === "file") enqueue(form, input.files);
  });
  document.addEventListener("submit", (event) => {
    const form = event.target.closest?.(FORM);
    if (!form) return;
    event.preventDefault();
    enqueue(form, form.querySelector('input[type="file"]')?.files);
  }, true);

  // 拖曳：整個上傳區都可放檔，拖進時亮起提示。
  let dragDepth = 0;
  const zoneOf = (event) => event.target.closest?.("[data-upload-dropzone]");
  const hasFiles = (event) => Array.from(event.dataTransfer?.types || []).includes("Files");
  document.addEventListener("dragenter", (event) => {
    const zone = zoneOf(event);
    if (!zone || !hasFiles(event)) return;
    event.preventDefault();
    dragDepth += 1;
    zone.classList.add("is-dragover");
  });
  document.addEventListener("dragover", (event) => {
    if (!zoneOf(event) || !hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  document.addEventListener("dragleave", (event) => {
    const zone = zoneOf(event);
    if (!zone) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) zone.classList.remove("is-dragover");
  });
  document.addEventListener("drop", (event) => {
    const zone = zoneOf(event);
    if (!zone) return;
    event.preventDefault();
    dragDepth = 0;
    zone.classList.remove("is-dragover");
    const form = zone.closest(FORM);
    if (form) enqueue(form, event.dataTransfer?.files);
  });

  const init = () => document.querySelectorAll(FORM).forEach(ready);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true});
  else init();
  document.addEventListener("inplace:updated", init);

  window.DMISMultiUpload = {precheck, formatSize, enqueue};
})();
