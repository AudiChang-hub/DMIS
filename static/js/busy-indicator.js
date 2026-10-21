/* 全站操作回饋：換頁、送出表單與按下功能後的背景請求，都在畫面頂端顯示進度條，
   稍久時再顯示「正在處理」提示，讓使用者知道操作已被接收。
   上傳檔案時顯示實際百分比；只有一段時間沒有任何進度時才提醒不要關閉頁面。 */
(() => {
  const SHOW_BAR_AFTER = 120;      // 很快完成的操作不閃爍
  const SHOW_STATUS_AFTER = 600;   // 超過才顯示文字提示
  const SLOW_AFTER = 8000;         // 這麼久沒有任何進度時改成請勿關閉頁面
  const GIVE_UP_AFTER = 20000;     // 這麼久沒有任何進度（被瀏覽器攔下等）時自動收起
  const INTERACTION_WINDOW = 1500; // 只追蹤使用者操作後發出的背景請求
  const WATCH_EVERY = 400;
  // 伺服器回傳下載檔時設這個短效 cookie（config/middleware.py）；看到就表示下載已開始，頁面不會換頁。
  const DOWNLOAD_COOKIE = "dmis_download";

  function isTrackedLink(anchor, event, currentUrl) {
    if (!anchor || event.defaultPrevented || event.button !== 0) return false;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    if (anchor.hasAttribute("download") || anchor.dataset.noBusy !== undefined) return false;
    const target = (anchor.getAttribute("target") || "").toLowerCase();
    if (target && target !== "_self") return false;
    const href = anchor.getAttribute("href");
    if (!href || href.startsWith("#") || /^(javascript|mailto|tel):/i.test(href)) return false;
    let url;
    try { url = new URL(anchor.href, currentUrl); } catch (error) { return false; }
    const current = new URL(currentUrl);
    if (url.origin !== current.origin) return false;
    if (url.pathname === current.pathname && url.search === current.search && url.hash) return false;
    return true;
  }

  function isTrackedForm(form, submitter) {
    if (!form || form.dataset.noBusy !== undefined) return false;
    const target = (submitter?.getAttribute("formtarget") || form.getAttribute("target") || "").toLowerCase();
    if (target && target !== "_self") return false;
    return form.dataset.download !== "true";
  }

  // 打字輸入不算「按下功能」，避免定時輪詢剛好碰上而閃爍。
  function isActivationKey(event) {
    if (event.key !== "Enter" && event.key !== " ") return false;
    const target = event.target;
    if (!target || typeof target.closest !== "function") return event.key === "Enter";
    if (target.closest("textarea")) return false;
    return event.key === "Enter" || Boolean(target.closest("button, a, [role=button], [role=switch], input[type=checkbox], input[type=radio], summary"));
  }

  function megabytes(bytes) {
    const value = bytes / (1024 * 1024);
    return value >= 10 ? value.toFixed(0) : value.toFixed(1);
  }

  function messageFor(kind, slow, progress = null) {
    if (kind === "upload") {
      const sent = Boolean(progress && progress.total && progress.loaded >= progress.total);
      if (slow) return sent ? "仍在處理，請稍候，不要關閉或重新整理頁面…" : "網路較慢，仍在上傳，請不要關閉或重新整理頁面…";
      if (!progress || !progress.total) return "正在上傳檔案…";
      if (sent) return "檔案已上傳，系統處理中…";
      const percent = Math.min(99, Math.floor((progress.loaded / progress.total) * 100));
      return `正在上傳 ${percent}%（${megabytes(progress.loaded)}／${megabytes(progress.total)} MB）…`;
    }
    if (slow) return "仍在處理，請稍候，不要關閉或重新整理頁面…";
    if (kind === "navigate") return "正在開啟頁面…";
    if (kind === "submit") return "正在送出，請稍候…";
    return "處理中，請稍候…";
  }

  function hasDownloadCookie(cookieText) {
    return String(cookieText || "").split(";").some((part) => part.trim().startsWith(`${DOWNLOAD_COOKIE}=`));
  }

  if (typeof window === "undefined" || typeof document === "undefined") {
    module.exports = {isTrackedLink, isTrackedForm, isActivationKey, messageFor, hasDownloadCookie};
    return;
  }

  let bar = null;
  let status = null;
  let kind = "";
  let pending = 0;
  let uploads = 0;
  let progress = null;
  let startedAt = 0;
  let lastActivity = 0;
  let timers = [];
  let watcher = null;
  let lastInteraction = 0;

  function ensureElements() {
    if (bar) return;
    bar = document.createElement("div");
    bar.className = "busy-bar";
    bar.setAttribute("aria-hidden", "true");
    status = document.createElement("div");
    status.className = "busy-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.innerHTML = '<span class="busy-status__spinner" aria-hidden="true"></span><span class="busy-status__text"></span>';
    document.body.append(bar, status);
  }

  function clearTimers() {
    timers.forEach((timer) => window.clearTimeout(timer));
    timers = [];
    if (watcher) window.clearInterval(watcher);
    watcher = null;
  }

  function setText(text) {
    const node = status.querySelector(".busy-status__text");
    if (node.textContent !== text) node.textContent = text;
  }

  function clearDownloadCookie() {
    document.cookie = `${DOWNLOAD_COOKIE}=; Max-Age=0; path=/; SameSite=Lax`;
  }

  // 依「最後一次有進度」計時：上傳持續有進度就不會出現請勿關閉，也不會被自動收起。
  function watch() {
    if ((kind === "navigate" || kind === "submit") && hasDownloadCookie(document.cookie)) {
      clearDownloadCookie();
      stop();
      return;
    }
    const idle = Date.now() - lastActivity;
    if (idle >= GIVE_UP_AFTER) {
      stop();
      return;
    }
    setText(messageFor(kind, idle >= SLOW_AFTER, progress));
  }

  function start(nextKind) {
    ensureElements();
    if (kind === "navigate" || kind === "submit") return; // 已在換頁，維持原提示
    if (kind === "upload" && nextKind === "request") return; // 上傳中維持百分比
    const continuing = Boolean(kind);
    kind = nextKind;
    lastActivity = Date.now();
    if (nextKind === "navigate" || nextKind === "submit") clearDownloadCookie();
    setText(messageFor(kind, false, progress));
    if (continuing) return;
    clearTimers();
    startedAt = Date.now();
    timers.push(window.setTimeout(() => bar.classList.add("is-active"), SHOW_BAR_AFTER));
    timers.push(window.setTimeout(() => status.classList.add("is-visible"), SHOW_STATUS_AFTER));
    watcher = window.setInterval(watch, WATCH_EVERY);
    document.documentElement.setAttribute("aria-busy", "true");
  }

  function stop() {
    clearTimers();
    kind = "";
    pending = 0;
    uploads = 0;
    progress = null;
    if (!bar) return;
    bar.classList.remove("is-active");
    status.classList.remove("is-visible");
    document.documentElement.removeAttribute("aria-busy");
  }

  function settle() {
    if (pending === 0 && uploads === 0 && (kind === "request" || kind === "upload")) stop();
  }

  function markInteraction(event) {
    if (event.type === "keydown" && !isActivationKey(event)) return;
    lastInteraction = Date.now();
  }
  ["pointerdown", "keydown", "change", "submit"].forEach((type) => document.addEventListener(type, markInteraction, true));

  document.addEventListener("click", (event) => {
    const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!anchor) return;
    // 讓頁面自己的點擊處理（例如原地更新）先決定是否攔下。
    window.setTimeout(() => {
      if (isTrackedLink(anchor, event, window.location.href)) start("navigate");
    }, 0);
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    window.setTimeout(() => {
      if (!event.defaultPrevented && isTrackedForm(form, event.submitter)) start("submit");
    }, 0);
  });

  // 使用者操作後發出的背景請求（快速切換、原地篩選等）也顯示進度；定時輪詢不顯示。
  if (typeof window.fetch === "function") {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (...args) => {
      const tracked = Date.now() - lastInteraction < INTERACTION_WINDOW && !(args[1] && args[1].busy === false);
      if (!tracked) return originalFetch(...args);
      pending += 1;
      start("request");
      return originalFetch(...args).finally(() => {
        pending = Math.max(0, pending - 1);
        lastActivity = Date.now();
        settle();
      });
    };
  }

  // 有進度的上傳：用 XHR 送出 FormData，畫面顯示百分比與 MB；回傳值可像 fetch 的 Response 一樣讀取。
  function upload(url, body, {method = "POST", headers = {}, timeout = 120000} = {}) {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open(method, url, true);
      request.timeout = timeout;
      Object.entries(headers).forEach(([name, value]) => request.setRequestHeader(name, value));
      uploads += 1;
      progress = {loaded: 0, total: 0};
      start("upload");
      request.upload.addEventListener("progress", (event) => {
        if (!event.lengthComputable) return;
        progress = {loaded: event.loaded, total: event.total};
        lastActivity = Date.now();
        if (kind === "upload") setText(messageFor(kind, false, progress));
      });
      request.upload.addEventListener("load", () => {
        if (progress) progress = {loaded: progress.total || 1, total: progress.total || 1};
        lastActivity = Date.now();
        if (kind === "upload") setText(messageFor(kind, false, progress));
      });
      request.addEventListener("loadend", () => {
        uploads = Math.max(0, uploads - 1);
        lastActivity = Date.now();
        settle();
      });
      request.addEventListener("load", () => {
        const text = request.responseText || "";
        resolve({
          ok: request.status >= 200 && request.status < 300,
          status: request.status,
          url: request.responseURL,
          headers: {get: (name) => request.getResponseHeader(name)},
          text: async () => text,
          json: async () => JSON.parse(text),
        });
      });
      request.addEventListener("timeout", () => reject(new Error("上傳逾時，請確認網路後再試。")));
      request.addEventListener("error", () => reject(new Error("網路連線中斷，檔案未上傳完成，請再試一次。")));
      request.addEventListener("abort", () => reject(new Error("上傳已取消。")));
      request.send(body);
    });
  }

  window.dmisBusy = {upload};

  // 從上一頁返回（bfcache）或分頁回到前景時，收起殘留的提示。
  window.addEventListener("pageshow", stop);
})();
