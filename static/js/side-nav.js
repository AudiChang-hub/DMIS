// 共用側邊把手導覽：依頁面上的 [data-side-nav-section] 產生目錄、捲動時標示目前段落；
// 左側滑出、寬螢幕可釘選常駐（每種頁面各自記住，第一次預設釘選）；點了段落未釘選就收起。
(() => {
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
  if (sections.length && "IntersectionObserver" in window) {
    const visible = new Set();
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => (entry.isIntersecting ? visible.add(entry.target) : visible.delete(entry.target)));
      const first = sections.find((section) => visible.has(section));
      if (first) setCurrent(first);
    }, { rootMargin: "-25% 0px -60% 0px" });
    sections.forEach((section) => observer.observe(section));
  }
  list.addEventListener("click", (event) => {
    const link = event.target.closest(".side-nav__link");
    if (!link) return;
    event.preventDefault();
    const section = document.getElementById(link.hash.slice(1));
    if (section.tagName === "DETAILS") section.open = true;
    section.scrollIntoView({ block: "start", behavior: reduceMotion.matches ? "auto" : "smooth" });
    history.replaceState(history.state, "", link.hash);
    setCurrent(section);
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
