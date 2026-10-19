// 共用側邊把手導覽：依頁面上的 [data-side-nav-section] 產生目錄、捲動時標示目前段落；
// 左側滑出、寬螢幕可釘選常駐（每種頁面各自記住，第一次預設釘選）；點了段落未釘選就收起。
(() => {
  // 目前段落：頂端已越過判定線（固定標頭下方一小段）的最後一個段落；已捲到頁底時改取最後一個看得到的段落，
  // 頁尾的短段落（如營運總表的庫存概況）頂端永遠到不了判定線，也要能被標示。tops 為各段落相對視窗的頂端，隱藏的段落為 null。
  function pickCurrent(tops, { line, viewport, atBottom }) {
    let current = -1;
    tops.forEach((top, index) => { if (top !== null && top <= line) current = index; });
    if (atBottom) tops.forEach((top, index) => { if (top !== null && top < viewport) current = index; });
    return current >= 0 ? current : tops.findIndex((top) => top !== null);
  }
  if (typeof window === "undefined" || typeof document === "undefined") {
    module.exports = { pickCurrent };
    return;
  }

  const root = document.querySelector("[data-side-nav]");
  if (!root) return;
  const key = root.dataset.sideNavKey || "page";
  const toggle = root.querySelector("[data-side-nav-toggle]");
  const panel = root.querySelector("[data-side-nav-panel]");
  const backdrop = root.querySelector("[data-side-nav-backdrop]");
  const pin = root.querySelector("[data-side-nav-pin]");
  const list = root.querySelector("[data-side-nav-list]");
  const PIN_KEY = `dmis:side-nav-pinned:${key}`;
  const canPin = () => window.matchMedia("(min-width: 1100px)").matches;
  const readPinned = () => {
    try { const value = localStorage.getItem(PIN_KEY); return value === null ? true : value === "1"; } catch (error) { return true; }
  };
  const writePinned = (value) => { try { localStorage.setItem(PIN_KEY, value ? "1" : "0"); } catch (error) { /* 無痕模式：不記住 */ } };
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let pinned = false;

  // ---- 目錄 ----
  const sections = [...document.querySelectorAll("[data-side-nav-section]")].filter((el) => !el.closest("[data-side-nav]"));
  const links = new Map();
  sections.forEach((section, index) => {
    if (!section.id) section.id = `side-nav-section-${index + 1}`;
    const label = section.dataset.sideNavSection || section.querySelector("h2, h3")?.textContent.trim() || `第 ${index + 1} 段`;
    const link = document.createElement("a");
    link.className = "side-nav__link";
    link.href = `#${section.id}`;
    link.innerHTML = '<span class="side-nav__dot" aria-hidden="true"></span><span class="side-nav__label"></span>';
    link.querySelector(".side-nav__label").textContent = label;
    if (section.dataset.sideNavNote) {
      const note = document.createElement("small");
      note.textContent = section.dataset.sideNavNote;
      link.querySelector(".side-nav__label").append(note);
    }
    if (section.dataset.sideNavAttention !== undefined) link.classList.add("is-attention");
    list.append(link);
    links.set(section, link);
  });
  if (!sections.length) list.hidden = true;
  if (!sections.length && !panel.querySelector(".side-nav__body > :not([data-side-nav-list])")) { root.hidden = true; return; }

  const setCurrent = (section) => {
    links.forEach((link, item) => {
      const current = item === section;
      link.classList.toggle("is-current", current);
      if (current) link.setAttribute("aria-current", "location"); else link.removeAttribute("aria-current");
    });
  };
  // 捲動標示：每次捲動依段落位置重算。點目錄後鎖定點選的段落，直到捲動停下、使用者再自己捲動才放開，
  // 平滑捲動途中經過的段落與頁底捲不上去的短段落都不會把標示搶走。
  let held = null;
  let settled = false;
  let settleTimer = 0;
  let frame = 0;
  const refresh = () => {
    frame = 0;
    if (held) return;
    const margin = parseFloat(getComputedStyle(sections[0]).scrollMarginTop) || 0;
    const viewport = window.innerHeight;
    const tops = sections.map((section) => (section.getClientRects().length ? section.getBoundingClientRect().top : null));
    const index = pickCurrent(tops, {
      line: margin + Math.min(viewport * 0.2, 160),
      viewport,
      atBottom: window.scrollY > 0 && Math.ceil(window.scrollY + viewport) >= document.documentElement.scrollHeight - 2,
    });
    if (index >= 0) setCurrent(sections[index]);
  };
  const schedule = () => { if (!frame) frame = requestAnimationFrame(refresh); };
  const settle = () => { clearTimeout(settleTimer); settled = true; };
  const release = () => { held = null; settled = false; clearTimeout(settleTimer); schedule(); };
  if (sections.length) {
    window.addEventListener("scroll", () => {
      if (!held) { schedule(); return; }
      if (settled) { release(); return; }
      clearTimeout(settleTimer);
      settleTimer = setTimeout(settle, 160);
    }, { passive: true });
    window.addEventListener("scrollend", () => { if (held && !settled) settle(); });
    // 平滑捲動途中使用者自己滾輪、觸控或按鍵捲動，就交還給捲動標示。
    ["wheel", "touchstart"].forEach((type) => window.addEventListener(type, () => { if (held) release(); }, { passive: true }));
    document.addEventListener("keydown", (event) => {
      if (held && ["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key)) release();
    });
    window.addEventListener("resize", schedule);
    refresh();
  }
  list.addEventListener("click", (event) => {
    const link = event.target.closest(".side-nav__link");
    if (!link) return;
    event.preventDefault();
    const section = document.getElementById(link.hash.slice(1));
    if (section.tagName === "DETAILS") section.open = true;
    held = section;
    settled = false;
    setCurrent(section);
    // 全站 html 設了 scroll-behavior: smooth，減少動態時要明確用 instant 才會瞬間定位。
    section.scrollIntoView({ block: "start", behavior: reduceMotion.matches ? "instant" : "smooth" });
    history.replaceState(history.state, "", link.hash);
    clearTimeout(settleTimer);
    settleTimer = setTimeout(settle, 160);
    if (!pinned) setOpen(false, { focus: false });
  });

  // ---- 開關與釘選 ----
  document.body.classList.add("has-side-nav");
  function setOpen(open, { focus = true } = {}) {
    root.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    if (open) panel.removeAttribute("inert"); else panel.setAttribute("inert", "");
    if (open && focus) panel.querySelector(".is-current, .side-nav__link, button, a")?.focus({ preventScroll: true });
    if (!open && focus && panel.contains(document.activeElement)) toggle.focus({ preventScroll: true });
  }
  const applyPinned = (value) => {
    pinned = value && canPin();
    document.body.classList.toggle("is-side-nav-pinned", pinned);
    root.classList.toggle("is-pinned", pinned);
    pin.setAttribute("aria-pressed", String(pinned));
    pin.textContent = pinned ? "取消釘選" : "釘選";
    setOpen(pinned, { focus: false });
  };
  toggle.addEventListener("click", () => setOpen(!root.classList.contains("is-open")));
  root.querySelector("[data-side-nav-close]").addEventListener("click", () => {
    if (pinned) { applyPinned(false); writePinned(false); }
    setOpen(false);
  });
  backdrop.addEventListener("click", () => setOpen(false));
  pin.addEventListener("click", () => { const next = !pinned; applyPinned(next); writePinned(next); });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && root.classList.contains("is-open") && !pinned) { setOpen(false); return; }
    const typing = event.target.closest && event.target.closest("input, textarea, select, [contenteditable='true']");
    if (event.key === "[" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      setOpen(!root.classList.contains("is-open"));
    }
  });
  window.matchMedia("(min-width: 1100px)").addEventListener("change", () => applyPinned(readPinned()));
  applyPinned(readPinned());
})();
