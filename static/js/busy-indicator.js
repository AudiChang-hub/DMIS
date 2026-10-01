/* 全站操作回饋：換頁、送出表單與按下功能後的背景請求，都在畫面頂端顯示進度條，
   稍久時再顯示「正在處理」提示，讓使用者知道操作已被接收。 */
(() => {
  const SHOW_BAR_AFTER = 120;      // 很快完成的操作不閃爍
  const SHOW_STATUS_AFTER = 600;   // 超過才顯示文字提示
  const SLOW_AFTER = 8000;         // 太久時改成請勿關閉頁面
  const GIVE_UP_AFTER = 20000;     // 下載或被瀏覽器攔下時自動收起
  const INTERACTION_WINDOW = 1500; // 只追蹤使用者操作後發出的背景請求

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

  function messageFor(kind, slow) {
    if (slow) return "仍在處理，請稍候，不要關閉或重新整理頁面…";
    if (kind === "navigate") return "正在開啟頁面…";
    if (kind === "submit") return "正在送出，請稍候…";
    return "處理中，請稍候…";
  }

  if (typeof window === "undefined" || typeof document === "undefined") {
    module.exports = {isTrackedLink, isTrackedForm, messageFor};
    return;
  }

  let bar = null;
  let status = null;
  let kind = "";
  let pending = 0;
  let timers = [];
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
  }

  function start(nextKind) {
    ensureElements();
    if (kind === "navigate" || kind === "submit") return; // 已在換頁，維持原提示
    kind = nextKind;
    clearTimers();
    status.querySelector(".busy-status__text").textContent = messageFor(kind, false);
    timers.push(window.setTimeout(() => bar.classList.add("is-active"), SHOW_BAR_AFTER));
    timers.push(window.setTimeout(() => status.classList.add("is-visible"), SHOW_STATUS_AFTER));
    timers.push(window.setTimeout(() => {
      status.querySelector(".busy-status__text").textContent = messageFor(kind, true);
    }, SLOW_AFTER));
    timers.push(window.setTimeout(stop, GIVE_UP_AFTER));
    document.documentElement.setAttribute("aria-busy", "true");
  }

  function stop() {
    clearTimers();
    kind = "";
    pending = 0;
    if (!bar) return;
    bar.classList.remove("is-active");
    status.classList.remove("is-visible");
    document.documentElement.removeAttribute("aria-busy");
  }

  function markInteraction() { lastInteraction = Date.now(); }
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

  // 使用者操作後發出的背景請求（快速切換、原地篩選、上傳等）也顯示進度；定時輪詢不顯示。
  if (typeof window.fetch === "function") {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (...args) => {
      const tracked = Date.now() - lastInteraction < INTERACTION_WINDOW && !(args[1] && args[1].busy === false);
      if (!tracked) return originalFetch(...args);
      pending += 1;
      if (pending === 1) start("request");
      return originalFetch(...args).finally(() => {
        pending = Math.max(0, pending - 1);
        if (pending === 0 && kind === "request") stop();
      });
    };
  }

  // 從上一頁返回（bfcache）或分頁回到前景時，收起殘留的提示。
  window.addEventListener("pageshow", stop);
})();
