"use strict";
// 車行多選依區域分組（T-234，使用者 2026-11-18）：分組與排序沿用車行聯絡資料（縣市，依 TaiwanCounty 順序），
// 沒填縣市歸最後的「未分區」。每區可收合，標題有區域名稱、家數與「全選此區／取消此區」；
// 搜尋時只留符合的車行，沒有符合的區整組隱藏。只改顯示與勾選操作，送出的值不變。
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.DMISRegionGroups = api;
})(typeof window !== "undefined" ? window : globalThis, () => {
  const UNASSIGNED = "未分區";

  // items 帶 {region, order}；依區域順序分組，區內維持原順序。order 相同時依第一次出現的位置。
  function groupByRegion(items) {
    const groups = new Map();
    items.forEach((item, index) => {
      const label = item.region || UNASSIGNED;
      if (!groups.has(label)) {
        const order = Number.isFinite(Number(item.order)) && item.order !== "" && item.order != null ? Number(item.order) : Infinity;
        groups.set(label, {label, order: label === UNASSIGNED ? Infinity : order, first: index, items: []});
      }
      groups.get(label).items.push(item);
    });
    return [...groups.values()].sort((a, b) => {
      if (a.label === UNASSIGNED || b.label === UNASSIGNED) return a.label === UNASSIGNED ? 1 : -1;
      return a.order - b.order || a.first - b.first;
    });
  }

  function countLabel(visible, total) {
    return visible === total ? `${total} 家` : `${visible}／${total} 家`;
  }

  // 伺服器產生的勾選清單（報表中心、禮品名單）：[data-region-group] 內的 [data-region-item] 是一家車行。
  function bindRegionGroups(container) {
    if (!container || typeof container.querySelectorAll !== "function") return;
    container.querySelectorAll("[data-region-group]:not([data-region-bound])").forEach(group => {
      group.dataset.regionBound = "1";
      const toggle = group.querySelector("[data-region-toggle]");
      const body = group.querySelector("[data-region-items]");
      const items = () => [...group.querySelectorAll("[data-region-item]")];
      const visibleBoxes = () => items().filter(item => !item.hidden)
        .map(item => item.querySelector('input[type="checkbox"]')).filter(Boolean);
      toggle?.addEventListener("click", () => {
        const expanded = toggle.getAttribute("aria-expanded") !== "true";
        toggle.setAttribute("aria-expanded", String(expanded));
        body.hidden = !expanded;
        group.dataset.regionCollapsed = expanded ? "" : "1";
      });
      group.querySelectorAll("[data-region-select]").forEach(button => button.addEventListener("click", event => {
        event.preventDefault();
        const checked = button.dataset.regionSelect === "all";
        visibleBoxes().forEach(box => { box.checked = checked; });
        const target = group.closest("[data-report-multi]") || group;
        target.dispatchEvent(new Event("change", {bubbles: true}));
      }));
    });
  }

  // 搜尋後重算：沒有符合的區整組隱藏、有符合的區展開並顯示符合家數；清空搜尋時回到使用者的收合狀態。
  function refreshRegionGroups(container, query) {
    if (!container || typeof container.querySelectorAll !== "function") return;
    const searching = Boolean(String(query || "").trim());
    container.querySelectorAll("[data-region-group]").forEach(group => {
      const items = [...group.querySelectorAll("[data-region-item]")];
      const visible = items.filter(item => !item.hidden).length;
      group.hidden = visible === 0;
      const count = group.querySelector("[data-region-count]");
      if (count) count.textContent = countLabel(visible, items.length);
      const toggle = group.querySelector("[data-region-toggle]");
      const body = group.querySelector("[data-region-items]");
      const expanded = searching || group.dataset.regionCollapsed !== "1";
      if (toggle) toggle.setAttribute("aria-expanded", String(expanded));
      if (body) body.hidden = !expanded;
    });
  }

  if (typeof document !== "undefined") {
    const init = () => {
      bindRegionGroups(document);
      // 各元件自己的搜尋先隱藏選項（掛在搜尋框上），這裡在冒泡階段之後重算分組。
      document.addEventListener("input", event => {
        const scope = event.target.closest?.("[data-region-scope]");
        if (scope) refreshRegionGroups(scope, event.target.value);
      });
      document.addEventListener("inplace:updated", event => (event.detail?.regions || []).forEach(bindRegionGroups));
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true});
    else init();
  }

  return {UNASSIGNED, groupByRegion, countLabel, bindRegionGroups, refreshRegionGroups};
});
