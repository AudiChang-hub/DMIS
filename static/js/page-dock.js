// 右下角懸浮鈕（T-297）：長頁往下捲以後，不用捲回頂端就能「↑」回頂端或「← 來源頁」。
// 超過一個畫面高才出現、回到頂部附近（半個畫面內）才隱藏，中間維持原狀，不會在門檻邊閃爍。
// 遇到底部的固定列（手機主選單、黏在底部的儲存列等）就往上讓開，不蓋住它們；層級低於側邊目錄、彈窗與提示。
(() => {
  const dock = document.querySelector("[data-page-dock]");
  if (!dock) return;
  const topButton = dock.querySelector("[data-page-dock-top]");
  const spacer = document.querySelector("[data-page-dock-spacer]");
  const SHOW_AT = 1;
  const HIDE_BELOW = 0.5;
  const GAP = 12;
  let shown = false;
  let frame = 0;

  const reduceMotion = () => Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const pageStart = () => document.getElementById("main-content") || document.querySelector("main");

  // 會擋到懸浮鈕的元件：固定在畫面下半部的列、或黏在底部（sticky + bottom）的儲存列；
  // 半個畫面以上高的遮罩、抽屜不算（層級本來就比懸浮鈕高）。
  const pinnedAncestor = element => {
    for (let node = element; node && node !== document.body && node !== document.documentElement; node = node.parentElement) {
      const style = window.getComputedStyle(node);
      if (style.position === "fixed") return node;
      if (style.position === "sticky" && style.bottom !== "auto") return node;
    }
    return null;
  };
  const measureLift = () => {
    if (!document.elementsFromPoint) return;
    dock.style.setProperty("--page-dock-lift", "0px");
    const rect = dock.getBoundingClientRect();
    const viewport = window.innerHeight;
    const points = [];
    [rect.left + 2, rect.left + rect.width / 2, rect.right - 2].forEach(x => {
      [rect.top + 2, rect.bottom - 2].forEach(y => points.push([x, y]));
    });
    let lift = 0;
    const seen = new Set();
    points.forEach(([x, y]) => {
      document.elementsFromPoint(x, y).forEach(element => {
        if (dock.contains(element)) return;
        const pinned = pinnedAncestor(element);
        if (!pinned || seen.has(pinned) || dock.contains(pinned)) return;
        seen.add(pinned);
        const box = pinned.getBoundingClientRect();
        if (box.height >= viewport * 0.5 || box.bottom < viewport * 0.5) return;
        if (box.top < rect.bottom && box.bottom > rect.top) lift = Math.max(lift, rect.bottom - box.top + GAP);
      });
    });
    if (lift) dock.style.setProperty("--page-dock-lift", `${Math.round(lift)}px`);
  };

  const setShown = value => {
    if (value === shown) return;
    shown = value;
    if (value && spacer) spacer.hidden = false;
    // 鍵盤焦點在懸浮鈕上卻要隱藏時，先把焦點交給頁面開頭，不讓焦點掉到看不見的地方。
    if (!value && dock.contains(document.activeElement)) {
      const start = pageStart();
      if (start) start.focus({preventScroll: true});
    }
    dock.classList.toggle("is-shown", value);
  };
  const update = () => {
    frame = 0;
    const viewport = window.innerHeight || 0;
    const y = window.scrollY || 0;
    setShown(shown ? y > viewport * HIDE_BELOW : y > viewport * SHOW_AT);
    if (shown) measureLift();
  };
  const schedule = () => {
    if (!frame) frame = window.requestAnimationFrame(update);
  };

  if (topButton) {
    topButton.addEventListener("click", () => {
      // 全站 html 是 smooth；減少動態時要明確用 instant 才會直接跳到頂端。
      window.scrollTo({top: 0, behavior: reduceMotion() ? "instant" : "smooth"});
      const start = pageStart();
      if (start) start.focus({preventScroll: true});
    });
  }
  window.addEventListener("scroll", schedule, {passive: true});
  window.addEventListener("resize", schedule);
  update();
})();
