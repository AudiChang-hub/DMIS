// 機種與售價列表的左側目錄：點品牌或機種就展開該品牌、跳到那一列並短暫標示；
// 目錄可搜尋（Enter 跳到第一筆），捲動時標示目前看到的品牌與機種。開關與釘選沿用 side-nav.js。
(() => {
  const index = document.querySelector("[data-model-index]");
  if (!index) return;
  const root = index.closest("[data-side-nav]");
  const body = index.closest(".side-nav__body");
  const search = index.querySelector("[data-model-index-search]");
  const empty = index.querySelector("[data-model-index-empty]");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const links = [...index.querySelectorAll("[data-model-index-link]")];
  const targetOf = (link) => document.getElementById(link.hash.slice(1));
  const linkByTarget = new Map(links.map((link) => [targetOf(link), link]).filter(([target]) => target));

  const closeIfFloating = () => {
    if (root && root.classList.contains("is-open") && !root.classList.contains("is-pinned")) {
      root.querySelector("[data-side-nav-toggle]").click();
    }
  };

  const locate = (target, { smooth = true } = {}) => {
    const group = target.matches("details") ? target : target.closest("details[data-brand-group]");
    if (group && !group.open) group.open = true;
    const isRow = target.matches("tr");
    // 手機上每列是一張長卡片，從卡片頂端開始看；寬螢幕表格列置中，上下文都看得到。
    const block = isRow && window.matchMedia("(min-width: 861px)").matches ? "center" : "start";
    target.scrollIntoView({ block, behavior: smooth && !reduceMotion.matches ? "smooth" : "instant" });
    if (isRow) {
      target.classList.remove("is-located");
      void target.offsetWidth; // 重複點同一列時重新播放標示
      target.classList.add("is-located");
      window.setTimeout(() => target.classList.remove("is-located"), 2200);
    }
    setCurrent(linkByTarget.get(target));
    holdCurrent(); // 捲動動畫期間別被路過的列搶走標示
    (isRow ? target : group.querySelector("summary")).focus({ preventScroll: true });
  };

  index.addEventListener("click", (event) => {
    const link = event.target.closest("[data-model-index-link]");
    if (!link) return;
    const target = targetOf(link);
    if (!target) return;
    event.preventDefault();
    history.replaceState(history.state, "", link.hash);
    closeIfFloating();
    locate(target);
  });

  // ---- 搜尋 ----
  const normalize = (value) => value.toLowerCase().replace(/\s+/g, "");
  search.addEventListener("input", () => {
    const query = normalize(search.value);
    let shown = 0;
    index.querySelectorAll("[data-model-index-brand]").forEach((brand) => {
      let brandShown = 0;
      brand.querySelectorAll("[data-model-index-family]").forEach((family) => {
        const match = !query || normalize(family.dataset.search || "").includes(query);
        family.hidden = !match;
        if (match) brandShown += 1;
      });
      brand.querySelectorAll("[data-model-index-divider]").forEach((divider) => {
        let next = divider.nextElementSibling;
        let visible = false;
        while (next) { if (!next.hidden) { visible = true; break; } next = next.nextElementSibling; }
        divider.hidden = !visible;
      });
      brand.hidden = brandShown === 0;
      shown += brandShown;
    });
    empty.hidden = shown > 0;
  });
  search.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const first = index.querySelector("[data-model-index-family]:not([hidden]) [data-model-index-link]");
    if (first) { event.preventDefault(); first.click(); }
  });

  // ---- 目前位置 ----
  let currentLink = null;
  let holding = false;
  let releaseTimer = 0;
  const release = () => { holding = false; window.clearTimeout(releaseTimer); window.removeEventListener("scrollend", release); };
  function holdCurrent() {
    release();
    holding = true;
    // 捲動結束才恢復自動標示；不支援 scrollend 或根本不用捲動時，最多等 3 秒。
    window.addEventListener("scrollend", release, { once: true });
    releaseTimer = window.setTimeout(release, 3000);
  }
  function setCurrent(link) {
    if (!link || link === currentLink) return;
    links.forEach((item) => {
      item.classList.toggle("is-current", item === link);
      if (item === link) item.setAttribute("aria-current", "location"); else item.removeAttribute("aria-current");
    });
    const brandLink = link.closest("[data-model-index-brand]")?.querySelector(".model-index__brand-link");
    links.forEach((item) => item.classList.toggle("is-within", item === brandLink && item !== link));
    currentLink = link;
    // 只捲動目錄本身，不動到頁面。
    if (body && root?.classList.contains("is-open")) {
      const top = link.offsetTop - body.offsetTop;
      if (top < body.scrollTop + 48 || top > body.scrollTop + body.clientHeight - 48) {
        body.scrollTo({ top: Math.max(0, top - body.clientHeight / 3), behavior: "instant" });
      }
    }
  }
  if ("IntersectionObserver" in window) {
    const targets = [...linkByTarget.keys()];
    const visible = new Set();
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => (entry.isIntersecting ? visible.add(entry.target) : visible.delete(entry.target)));
      if (holding) return;
      const rows = targets.filter((target) => target.matches("tr") && visible.has(target));
      const hit = rows[0] || targets.find((target) => !target.matches("tr") && visible.has(target));
      if (hit) setCurrent(linkByTarget.get(hit));
    }, { rootMargin: "-40% 0px -45% 0px" });
    targets.forEach((target) => observer.observe(target));
  }

  // 帶著 #vm-… 回到這頁（返回鍵、分享連結）時，展開該品牌並停在那一列。
  const initial = location.hash && document.getElementById(location.hash.slice(1));
  if (initial && linkByTarget.has(initial)) window.setTimeout(() => locate(initial, { smooth: false }), 0);
})();
