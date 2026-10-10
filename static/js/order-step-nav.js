// 訂單步驟側邊列：從左側滑出；寬螢幕可釘選常駐（記住選擇，第一次預設釘選）。點選步驟後未釘選就自動收起。
(() => {
  const root = document.querySelector("[data-order-nav]");
  if (!root) return;
  const toggle = root.querySelector("[data-order-nav-toggle]");
  const panel = root.querySelector("[data-order-nav-panel]");
  const backdrop = root.querySelector("[data-order-nav-backdrop]");
  const pin = root.querySelector("[data-order-nav-pin]");
  const PIN_KEY = "dmis:order-nav-pinned";
  const canPin = () => window.matchMedia("(min-width: 1100px)").matches;
  const readPinned = () => {
    try {
      const value = localStorage.getItem(PIN_KEY);
      return value === null ? true : value === "1";
    } catch (error) { return true; }
  };
  const writePinned = (value) => { try { localStorage.setItem(PIN_KEY, value ? "1" : "0"); } catch (error) { /* 無痕模式：不記住 */ } };
  let pinned = false;
  document.body.classList.add("has-order-nav");

  const setOpen = (open, { focus = true } = {}) => {
    root.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    if (open) panel.removeAttribute("inert"); else panel.setAttribute("inert", "");
    if (open && focus) panel.querySelector('[aria-selected="true"], .order-step-tab.is-active, .order-step-tab')?.focus({ preventScroll: true });
    if (!open && focus && panel.contains(document.activeElement)) toggle.focus({ preventScroll: true });
  };
  const applyPinned = (value) => {
    pinned = value && canPin();
    document.body.classList.toggle("is-order-nav-pinned", pinned);
    root.classList.toggle("is-pinned", pinned);
    pin.setAttribute("aria-pressed", String(pinned));
    pin.textContent = pinned ? "取消釘選" : "釘選";
    setOpen(pinned, { focus: false });
  };

  toggle.addEventListener("click", () => setOpen(!root.classList.contains("is-open")));
  root.querySelector("[data-order-nav-close]").addEventListener("click", () => {
    if (pinned) { applyPinned(false); writePinned(false); }
    setOpen(false);
  });
  backdrop.addEventListener("click", () => setOpen(false));
  pin.addEventListener("click", () => { const next = !pinned; applyPinned(next); writePinned(next); });
  // 點了步驟：未釘選時收起面板，讓內容回到眼前。
  panel.addEventListener("click", (event) => {
    if (!pinned && event.target.closest(".order-step-tab")) setOpen(false, { focus: false });
  });
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
