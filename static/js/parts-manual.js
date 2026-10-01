(() => {
  // 官方圖冊本身會捲動；讓框剛好填滿剩餘視窗，外層頁面不再捲動，避免兩層捲動互搶。
  const box = document.querySelector("[data-parts-manual]");
  const frame = document.querySelector("[data-parts-manual-frame]");
  if (!box || !frame) return;
  const fit = () => {
    if (box.classList.contains("is-expanded")) {
      frame.style.height = "";
      return;
    }
    const viewport = window.visualViewport?.height || window.innerHeight;
    const top = frame.getBoundingClientRect().top + window.scrollY;
    const mobileNav = document.querySelector(".mobile-nav");
    const navHeight = mobileNav && getComputedStyle(mobileNav).display !== "none" ? mobileNav.getBoundingClientRect().height : 0;
    const gap = 16;
    frame.style.height = `${Math.max(420, Math.floor(viewport - top - navHeight - gap))}px`;
  };

  const setExpanded = expanded => {
    box.classList.toggle("is-expanded", expanded);
    document.documentElement.classList.toggle("parts-manual-locked", expanded);
    fit();
  };
  document.querySelector("[data-parts-fullscreen]")?.addEventListener("click", () => {
    setExpanded(true);
    // 支援全螢幕 API 時連瀏覽器網址列一起收起；不支援（如 iPhone）時維持固定圖層。
    box.requestFullscreen?.().catch(() => {});
  });
  box.querySelector("[data-parts-fullscreen-exit]")?.addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    setExpanded(false);
  });
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement) setExpanded(false);
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && box.classList.contains("is-expanded")) setExpanded(false);
  });

  fit();
  window.addEventListener("resize", fit);
  window.visualViewport?.addEventListener("resize", fit);
  if (typeof ResizeObserver !== "undefined") {
    const header = document.querySelector(".app-header");
    if (header) new ResizeObserver(fit).observe(header);
  }
})();
