(() => {
  const catalog = document.querySelector("[data-vehicle-model-catalog]");
  if (!catalog) return;

  const isFiltered = catalog.dataset.filtered === "true";
  const storagePrefix = "dmis.vehicle-model-brand.";

  document.querySelectorAll("details[data-brand-group]").forEach((group) => {
    const brandName = group.dataset.brandGroup || "";
    const storageKey = `${storagePrefix}${brandName}`;

    if (isFiltered) {
      group.open = true;
    } else {
      try {
        group.open = window.localStorage.getItem(storageKey) === "open";
      } catch (_error) {
        group.open = false;
      }
    }

    // 寬螢幕的機種表不捲動，表頭才能固定在頁首下方；萬一內容仍比品牌區塊寬，改回水平捲動，別讓「編輯」被裁掉。
    const wrap = group.querySelector(".vehicle-model-overview-table");
    if (wrap && "ResizeObserver" in window) {
      const observer = new ResizeObserver(() => {
        wrap.toggleAttribute("data-overflowing", wrap.scrollWidth > wrap.clientWidth + 1);
      });
      observer.observe(wrap);
      if (wrap.firstElementChild) observer.observe(wrap.firstElementChild);
    }

    group.addEventListener("toggle", () => {
      if (isFiltered) return;
      try {
        window.localStorage.setItem(storageKey, group.open ? "open" : "closed");
      } catch (_error) {
        // 瀏覽器停用儲存時仍保留原生 details 收合功能。
      }
    });
  });
})();
