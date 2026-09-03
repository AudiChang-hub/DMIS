(() => {
  "use strict";
  let activeLayer = null;

  function placement(rect, viewport, contentHeight = 330) {
    const gap = 5, edge = 12;
    const leftEdge = viewport.left + edge, topEdge = viewport.top + edge;
    const rightEdge = viewport.left + viewport.width - edge;
    const bottomEdge = viewport.top + viewport.height - edge;
    const width = Math.max(0, Math.min(Math.max(220, rect.width), viewport.width - edge * 2));
    const below = Math.max(0, bottomEdge - rect.bottom - gap);
    const above = Math.max(0, rect.top - topEdge - gap);
    const openAbove = below < 220 && above > below;
    const maxHeight = Math.min(330, openAbove ? above : below);
    const height = Math.min(maxHeight, contentHeight);
    return {
      width, maxHeight, openAbove,
      left: Math.max(leftEdge, Math.min(rect.left, rightEdge - width)),
      top: openAbove ? Math.max(topEdge, rect.top - gap - height) : rect.bottom + gap,
    };
  }

  function create(list, onDismiss) {
    let anchor = null, owner = null, parent = null, sibling = null;
    let observer = null, resizeObserver = null;
    const viewport = () => {
      const visual = window.visualViewport;
      return {left: visual?.offsetLeft || 0, top: visual?.offsetTop || 0,
        width: visual?.width || window.innerWidth, height: visual?.height || window.innerHeight};
    };
    const dismiss = () => {
      close();
      onDismiss?.();
    };
    function position() {
      if (!anchor || list.hidden) return;
      if (!anchor.isConnected || !list.isConnected || (owner && !owner.open)) return dismiss();
      const rect = anchor.getBoundingClientRect(), view = viewport();
      const hostRect = owner?.getBoundingClientRect();
      if (rect.bottom <= view.top || rect.top >= view.top + view.height ||
          (hostRect && (rect.bottom <= hostRect.top || rect.top >= hostRect.bottom))) return dismiss();
      const bounds = placement(rect, view);
      list.style.width = `${bounds.width}px`;
      list.style.maxHeight = `${bounds.maxHeight}px`;
      const result = placement(rect, view, list.getBoundingClientRect().height);
      list.style.left = `${result.left}px`;
      list.style.top = `${result.top}px`;
      list.style.bottom = "auto";
    }
    function outside(event) {
      if (anchor && !anchor.contains(event.target) && !list.contains(event.target)) dismiss();
    }
    function keydown(event) {
      if (event.key === "Escape") {
        // 先收起選單，不能把後方仍在編輯的 dialog 一起關掉。
        event.preventDefault();
        event.stopPropagation();
        dismiss();
      } else if (event.key === "Tab") dismiss();
    }
    function close() {
      if (!anchor) return;
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
      window.visualViewport?.removeEventListener("resize", position);
      window.visualViewport?.removeEventListener("scroll", position);
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("focusin", outside, true);
      document.removeEventListener("keydown", keydown, true);
      owner?.removeEventListener("close", dismiss);
      observer?.disconnect();
      resizeObserver?.disconnect();
      if (list.hasAttribute("popover")) {
        try { list.hidePopover(); } catch (_error) { /* 父彈窗可能已關閉。 */ }
        list.removeAttribute("popover");
      }
      list.hidden = true;
      list.classList.remove("dmis-floating-list");
      list.removeAttribute("style");
      if (parent) parent.insertBefore(list, sibling?.parentNode === parent ? sibling : null);
      if (activeLayer === layer) activeLayer = null;
      anchor = owner = parent = sibling = observer = resizeObserver = null;
    }
    function open(input) {
      if (anchor === input) return position();
      if (activeLayer) activeLayer.dismiss();
      anchor = input;
      owner = input.closest("dialog[open]");
      parent = list.parentNode;
      sibling = list.nextSibling;
      // 保持在所屬 dialog 內，避免模態視窗把外部選項設為 inert。
      (owner || document.body).append(list);
      list.classList.add("dmis-floating-list");
      list.hidden = false;
      if (typeof list.showPopover === "function") {
        list.setAttribute("popover", "manual");
        try { list.showPopover(); } catch (_error) { list.removeAttribute("popover"); }
      }
      activeLayer = layer;
      window.addEventListener("resize", position);
      window.addEventListener("scroll", position, true);
      window.visualViewport?.addEventListener("resize", position);
      window.visualViewport?.addEventListener("scroll", position);
      document.addEventListener("pointerdown", outside, true);
      document.addEventListener("focusin", outside, true);
      document.addEventListener("keydown", keydown, true);
      owner?.addEventListener("close", dismiss);
      observer = new MutationObserver(() => {
        if (!input.isConnected || (owner && !owner.open)) dismiss();
      });
      observer.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ["open"]});
      if (typeof ResizeObserver === "function") {
        resizeObserver = new ResizeObserver(position);
        resizeObserver.observe(input);
      }
      position();
    }
    const layer = {open, close, position, dismiss};
    return layer;
  }

  const api = {create, placement};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else window.DMISFloatingList = api;
})();
