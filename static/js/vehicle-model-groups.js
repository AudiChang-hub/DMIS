(() => {
  const catalog = document.querySelector("[data-vehicle-model-catalog]");
  if (!catalog) return;

  const groups = Array.from(catalog.querySelectorAll("[data-brand-group]"));
  if (!groups.length) return;
  const familyGroups = Array.from(catalog.querySelectorAll("[data-family-group]"));

  const isFiltered = catalog.dataset.filtered === "true";
  const viewport = window.matchMedia("(max-width: 600px)").matches
    ? "mobile"
    : "desktop";
  const storageKey = `dmis:vehicle-model-groups:${viewport}`;
  const familyStorageKey = `dmis:vehicle-model-families:${viewport}`;

  const readState = (key) => {
    try {
      return JSON.parse(window.localStorage.getItem(key) || "null");
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

  const saveFamilyState = () => {
    if (isFiltered) return;
    const state = Object.fromEntries(
      familyGroups.map((group) => [group.dataset.familyGroup, group.open])
    );
    try {
      window.localStorage.setItem(familyStorageKey, JSON.stringify(state));
    } catch (_error) {
      // 儲存偏好失敗不應影響車型資料操作。
    }
  };

  if (!isFiltered) {
    const savedState = readState(storageKey);
    if (savedState && typeof savedState === "object") {
      groups.forEach((group) => {
        if (typeof savedState[group.dataset.brandGroup] === "boolean") {
          group.open = savedState[group.dataset.brandGroup];
        }
      });
    }
    const savedFamilyState = readState(familyStorageKey);
    if (savedFamilyState && typeof savedFamilyState === "object") {
      familyGroups.forEach((group) => {
        if (typeof savedFamilyState[group.dataset.familyGroup] === "boolean") {
          group.open = savedFamilyState[group.dataset.familyGroup];
        }
      });
    }
  }

  groups.forEach((group) => group.addEventListener("toggle", saveState));
  familyGroups.forEach((group) => group.addEventListener("toggle", saveFamilyState));

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
