(() => {
  const init = () => {
    const nav = document.querySelector("[data-model-workspace-tabs]");
    if (!nav) return;
    const list = nav.querySelector(".model-workspace-tabs__list");
    const hero = document.querySelector("[data-model-workspace-hero]");

    // 手機版分頁可水平捲動：目前分頁捲到可見處，兩側依可捲動方向淡出。
    const current = list.querySelector('[aria-current="page"]');
    if (current && list.scrollWidth > list.clientWidth) {
      const target = current.offsetLeft - (list.clientWidth - current.offsetWidth) / 2;
      list.scrollLeft = Math.max(0, target);
    }
    const refreshOverflow = () => {
      const max = list.scrollWidth - list.clientWidth;
      nav.toggleAttribute("data-overflow-start", list.scrollLeft > 2);
      nav.toggleAttribute("data-overflow-end", max - list.scrollLeft > 2);
    };
    refreshOverflow();
    list.addEventListener("scroll", refreshOverflow, { passive: true });
    window.addEventListener("resize", refreshOverflow);

    // 左右鍵在分頁之間移動焦點；Enter 開啟，與一般連結相同。
    const links = () => Array.from(list.querySelectorAll("a.model-workspace-tab"));
    list.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      const items = links();
      const index = items.indexOf(document.activeElement);
      if (index < 0) return;
      event.preventDefault();
      let next = index;
      if (event.key === "ArrowLeft") next = (index - 1 + items.length) % items.length;
      if (event.key === "ArrowRight") next = (index + 1) % items.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = items.length - 1;
      items[next].focus();
      items[next].scrollIntoView({ block: "nearest", inline: "nearest" });
    });

    // 桌面版分頁列固定在頁首下方；頁首捲出畫面後在分頁列左側帶出機種名稱。
    if (hero && "IntersectionObserver" in window) {
      const headerHeight = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--app-header-height")) || 72;
      const observer = new IntersectionObserver(([entry]) => {
        nav.classList.toggle("is-stuck", !entry.isIntersecting && entry.boundingClientRect.top < headerHeight);
      }, { rootMargin: `-${Math.round(headerHeight)}px 0px 0px 0px`, threshold: 0 });
      observer.observe(hero);
    }
  };
  // 左側機種清單：預設收起，需要時從左邊滑出蓋在內容上；可釘選常駐（記住選擇）。
  const initNavigator = () => {
    const root = document.querySelector("[data-model-nav]");
    if (!root) return;
    const toggle = root.querySelector("[data-model-nav-toggle]");
    const panel = root.querySelector("[data-model-nav-panel]");
    const backdrop = root.querySelector("[data-model-nav-backdrop]");
    const search = root.querySelector("[data-model-nav-search]");
    const pin = root.querySelector("[data-model-nav-pin]");
    const empty = root.querySelector("[data-model-nav-empty]");
    const PIN_KEY = "dmis:model-nav-pinned";
    const canPin = () => window.matchMedia("(min-width: 1100px)").matches;
    const readPinned = () => { try { return localStorage.getItem(PIN_KEY) === "1"; } catch (error) { return false; } };
    const writePinned = value => { try { localStorage.setItem(PIN_KEY, value ? "1" : "0"); } catch (error) { /* 無痕模式等：不記住即可 */ } };
    let pinned = false;
    document.body.classList.add("has-model-nav");

    const setOpen = (open, { focus = true } = {}) => {
      root.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", String(open));
      if (open) panel.removeAttribute("inert"); else panel.setAttribute("inert", "");
      if (open) {
        const current = panel.querySelector(".model-nav__year.is-current");
        if (current) current.scrollIntoView({ block: "center" });
        if (focus) search.focus({ preventScroll: true });
      } else if (focus && panel.contains(document.activeElement)) {
        toggle.focus({ preventScroll: true });
      }
    };
    const applyPinned = value => {
      pinned = value && canPin();
      document.body.classList.toggle("is-model-nav-pinned", pinned);
      root.classList.toggle("is-pinned", pinned);
      pin.setAttribute("aria-pressed", String(pinned));
      pin.textContent = pinned ? "取消釘選" : "釘選";
      if (pinned) setOpen(true, { focus: false });
    };

    toggle.addEventListener("click", () => setOpen(!root.classList.contains("is-open")));
    root.querySelector("[data-model-nav-close]").addEventListener("click", () => {
      if (pinned) { applyPinned(false); writePinned(false); }
      setOpen(false);
    });
    backdrop.addEventListener("click", () => setOpen(false));
    pin.addEventListener("click", () => {
      const next = !pinned;
      applyPinned(next);
      writePinned(next);
      if (!next) setOpen(false, { focus: false });
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && root.classList.contains("is-open") && !pinned) {
        setOpen(false);
        return;
      }
      // 快捷鍵 [ ：不在輸入框裡時開關清單。
      const target = event.target;
      const typing = target.closest && target.closest("input, textarea, select, [contenteditable='true']");
      if (event.key === "[" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        if (pinned) search.focus(); else setOpen(!root.classList.contains("is-open"));
      }
    });

    // 搜尋：比對品牌、機種、型號與年式；空白與大小寫不影響。
    const normalize = value => value.toLowerCase().replace(/\s+/g, "");
    search.addEventListener("input", () => {
      const query = normalize(search.value);
      let shown = 0;
      root.querySelectorAll("[data-model-nav-brand]").forEach(brand => {
        let brandShown = 0;
        brand.querySelectorAll("[data-model-nav-family]").forEach(family => {
          const match = !query || normalize(family.dataset.search || "").includes(query);
          family.hidden = !match;
          if (match) brandShown += 1;
        });
        brand.querySelectorAll("ul").forEach(list => {
          list.hidden = !Array.from(list.children).some(item => !item.hidden);
          const label = list.previousElementSibling;
          if (label && label.matches("[data-model-nav-sub]")) label.hidden = list.hidden;
        });
        brand.hidden = brandShown === 0;
        if (query && brandShown) brand.open = true;
        shown += brandShown;
      });
      empty.hidden = shown > 0;
    });
    search.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      const first = root.querySelector("[data-model-nav-family]:not([hidden]) .model-nav__year");
      if (first) { event.preventDefault(); first.click(); }
    });

    applyPinned(readPinned());
    window.matchMedia("(min-width: 1100px)").addEventListener("change", () => applyPinned(readPinned()));
  };

  const start = () => { init(); initNavigator(); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
