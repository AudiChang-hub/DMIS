(() => {
  document.querySelectorAll("[data-next-actions]").forEach((root) => {
    const expanded = root.querySelector("[data-next-actions-expanded]");
    const compact = root.querySelector("[data-next-actions-restore]");
    const dismiss = root.querySelector("[data-next-actions-dismiss]");
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

    setCollapsed(readDismissedState());
  });
})();
