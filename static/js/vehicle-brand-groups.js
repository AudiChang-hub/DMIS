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
