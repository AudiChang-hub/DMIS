(() => {
  // 官方圖冊本身會捲動；讓框剛好填滿剩餘視窗，外層頁面不再捲動，避免兩層捲動互搶。
  const frame = document.querySelector("[data-parts-manual-frame]");
  if (!frame) return;
  const fit = () => {
    const viewport = window.visualViewport?.height || window.innerHeight;
    const top = frame.getBoundingClientRect().top + window.scrollY;
    const mobileNav = document.querySelector(".mobile-nav");
    const navHeight = mobileNav && getComputedStyle(mobileNav).display !== "none" ? mobileNav.getBoundingClientRect().height : 0;
    const gap = 16;
    frame.style.height = `${Math.max(420, Math.floor(viewport - top - navHeight - gap))}px`;
  };
  fit();
  window.addEventListener("resize", fit);
  window.visualViewport?.addEventListener("resize", fit);
  if (typeof ResizeObserver !== "undefined") {
    const header = document.querySelector(".app-header");
    if (header) new ResizeObserver(fit).observe(header);
  }
})();
