(() => {
  const catalog = document.querySelector("[data-vehicle-model-catalog]");
  if (!catalog) return;

  const groups = Array.from(catalog.querySelectorAll("[data-brand-group]"));
  if (!groups.length) return;

  const isFiltered = catalog.dataset.filtered === "true";
  const viewport = window.matchMedia("(max-width: 600px)").matches
    ? "mobile"
    : "desktop";
  const storageKey = `dmis:vehicle-model-groups:${viewport}`;

  const readState = () => {
    try {
      return JSON.parse(window.localStorage.getItem(storageKey) || "null");
    } catch (_error) {
      return null;
    }
  };

  const saveState = () => {
    if (isFiltered) return;
    const state = Object.fromEntries(
      groups.map((group) => [group.dataset.brandGroup, group.open])
    );
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(state));
    } catch (_error) {
      // 儲存偏好失敗不應影響車型資料操作。
    }
  };

  if (!isFiltered) {
    const savedState = readState();
    if (savedState && typeof savedState === "object") {
      groups.forEach((group) => {
        if (typeof savedState[group.dataset.brandGroup] === "boolean") {
          group.open = savedState[group.dataset.brandGroup];
        }
      });
    }
  }

  groups.forEach((group) => group.addEventListener("toggle", saveState));

  catalog.querySelector("[data-brand-groups-expand]")?.addEventListener("click", () => {
    groups.forEach((group) => {
      group.open = true;
    });
    saveState();
  });

  catalog.querySelector("[data-brand-groups-collapse]")?.addEventListener("click", () => {
    groups.forEach((group) => {
      group.open = false;
    });
    saveState();
  });
})();
