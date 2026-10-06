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
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
