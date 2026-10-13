// 固定頁首：離開原位置後加上 is-stuck，縮成只有姓名、狀態與操作按鈕的精簡列。
// 縮小少掉的高度由 spacer 補回，頁面總高度不變；否則短頁面會因頁首縮放改變可捲動範圍而在兩種狀態間來回跳動。
(() => {
  document.querySelectorAll("[data-sticky-hero]").forEach((hero) => {
    const sentinel = document.createElement("div");
    sentinel.setAttribute("aria-hidden", "true");
    sentinel.style.height = "1px";
    hero.before(sentinel);
    const spacer = document.createElement("div");
    spacer.setAttribute("aria-hidden", "true");
    spacer.className = "sticky-hero-spacer";
    hero.after(spacer);
    let fullHeight = hero.offsetHeight;
    const syncSpacer = () => {
      const height = hero.offsetHeight;
      if (!hero.classList.contains("is-stuck")) {
        fullHeight = height;
        spacer.style.height = "0px";
        return;
      }
      spacer.style.height = `${Math.max(0, fullHeight - height)}px`;
    };
    const setStuck = (stuck) => {
      if (stuck === hero.classList.contains("is-stuck")) return;
      if (stuck) fullHeight = hero.offsetHeight;
      // 以最終高度一次補足 spacer：padding 過場期間的高度差也會觸發瀏覽器捲動錨定而回彈。
      const transition = hero.style.transition;
      hero.style.transition = "none";
      hero.classList.toggle("is-stuck", stuck);
      syncSpacer();
      hero.style.transition = transition;
    };
    if ("ResizeObserver" in window) new ResizeObserver(syncSpacer).observe(hero);
    const offset = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--app-header-height")) || 72;
    const observer = new IntersectionObserver(
      ([entry]) => setStuck(!entry.isIntersecting),
      { rootMargin: `-${Math.round(offset()) + 1}px 0px 0px 0px` },
    );
    observer.observe(sentinel);
  });
})();
