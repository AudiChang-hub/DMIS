(() => {
  document.querySelectorAll("[data-next-actions]").forEach((root) => {
    const expanded = root.querySelector("[data-next-actions-expanded]");
    const compact = root.querySelector("[data-next-actions-restore]");
    const dismiss = root.querySelector("[data-next-actions-dismiss]");
    const primary = root.querySelector("[data-next-action-primary]");
    const controls = root.querySelector("[data-next-actions-controls]");
    const badge = root.querySelector("[data-next-actions-badge]");
    const icon = root.querySelector("[data-next-actions-icon]");
    const compactLabel = root.querySelector("[data-next-actions-compact-label]");
    const secondaryActions = Array.from(
      root.querySelectorAll(".next-actions__secondary-item[data-target-tab]")
    );
    const orderId = root.dataset.orderId;
    const stateKey = root.dataset.stateKey;
    if (!expanded || !compact || !dismiss || !orderId || !stateKey) return;

    const prefix = `order-next-actions:${orderId}:`;
    const storageKey = `${prefix}${stateKey}`;

    function setCollapsed(collapsed) {
      expanded.hidden = collapsed;
      compact.hidden = !collapsed;
      root.classList.toggle("is-collapsed", collapsed);
    }

    function readDismissedState() {
      try {
        for (let index = window.localStorage.length - 1; index >= 0; index -= 1) {
          const key = window.localStorage.key(index);
          if (key && key.startsWith(prefix) && key !== storageKey) {
            window.localStorage.removeItem(key);
          }
        }
        return window.localStorage.getItem(storageKey) === "dismissed";
      } catch (_error) {
        return false;
      }
    }

    function saveDismissedState(dismissed) {
      try {
        if (dismissed) {
          window.localStorage.setItem(storageKey, "dismissed");
        } else {
          window.localStorage.removeItem(storageKey);
        }
      } catch (_error) {
        // 隱私模式或儲存空間不可用時，仍保留本次頁面的收合操作。
      }
    }

    function syncCurrentTab(tabName) {
      root.dataset.currentTab = tabName;
      const primaryIsCurrent = Boolean(
        primary?.dataset.targetTab &&
          primary.dataset.targetTab === tabName &&
          !primary.dataset.targetAnchor
      );
      root.classList.toggle("is-current-context", primaryIsCurrent);
      if (controls) controls.hidden = primaryIsCurrent;
      if (badge) {
        badge.textContent = primaryIsCurrent
          ? "目前作業"
          : badge.dataset.defaultLabel;
      }
      if (compactLabel) {
        compactLabel.textContent = primaryIsCurrent ? "目前作業" : "建議下一步";
      }
      if (icon) icon.textContent = primaryIsCurrent ? "↓" : "→";

      secondaryActions.forEach((action) => {
        const isCurrent = Boolean(
          action.dataset.targetTab &&
            action.dataset.targetTab === tabName &&
            !action.dataset.targetAnchor
        );
        const label = action.querySelector("[data-next-action-label]");
        action.classList.toggle("is-current-context", isCurrent);
        if (isCurrent) {
          if (!action.dataset.defaultHref) {
            action.dataset.defaultHref = action.getAttribute("href") || "";
          }
          action.removeAttribute("href");
          action.setAttribute("aria-current", "location");
          action.tabIndex = -1;
          if (label) label.textContent = "目前頁面";
          return;
        }
        if (!action.hasAttribute("href") && action.dataset.defaultHref) {
          action.setAttribute("href", action.dataset.defaultHref);
        }
        action.removeAttribute("aria-current");
        action.removeAttribute("tabindex");
        if (label) {
          label.innerHTML = `${label.dataset.defaultLabel} <span aria-hidden="true">→</span>`;
        }
      });
    }

    dismiss.addEventListener("click", () => {
      saveDismissedState(true);
      setCollapsed(true);
      compact.focus({preventScroll: true});
    });

    compact.addEventListener("click", () => {
      saveDismissedState(false);
      setCollapsed(false);
      dismiss.focus({preventScroll: true});
    });

    window.addEventListener("order-tab-change", (event) => {
      syncCurrentTab(event.detail?.tab || "order");
    });

    const selectedTab = document.querySelector(
      "[data-order-tabs] [data-tab][aria-selected='true']"
    );
    syncCurrentTab(selectedTab?.dataset.tab || root.dataset.currentTab || "order");

    setCollapsed(readDismissedState());
  });
})();
