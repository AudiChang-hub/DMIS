// 固定頁首：離開原位置後加上 is-stuck，縮成只有姓名、狀態與操作按鈕的精簡列。
(() => {
  document.querySelectorAll("[data-sticky-hero]").forEach((hero) => {
    const sentinel = document.createElement("div");
    sentinel.setAttribute("aria-hidden", "true");
    sentinel.style.height = "1px";
    hero.before(sentinel);
    const offset = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--app-header-height")) || 72;
    const observer = new IntersectionObserver(
      ([entry]) => hero.classList.toggle("is-stuck", !entry.isIntersecting),
      { rootMargin: `-${Math.round(offset()) + 1}px 0px 0px 0px` },
    );
    observer.observe(sentinel);
  });
})();
