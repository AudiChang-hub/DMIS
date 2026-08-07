(() => {
  const tabList = document.querySelector("[data-order-tabs]");
  if (!tabList) return;

  const tabs = Array.from(tabList.querySelectorAll("[data-tab]"));
  const panels = Array.from(document.querySelectorAll("[data-tab-panel]"));
  const validTabs = new Set(tabs.map((tab) => tab.dataset.tab));
  const storageKey = `order-detail-tab:${tabList.dataset.orderId}`;

  const requestedTab = new URL(window.location.href).searchParams.get("tab");
  const savedTab = window.localStorage.getItem(storageKey);

  function activate(name, updateUrl = true) {
    const activeName = validTabs.has(name) ? name : "order";
    tabs.forEach((tab) => {
      const active = tab.dataset.tab === activeName;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
      if (active) {
        tab.scrollIntoView({block: "nearest", inline: "nearest"});
      }
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.tabPanel !== activeName;
    });
    window.localStorage.setItem(storageKey, activeName);
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", activeName);
      window.history.replaceState({tab: activeName}, "", url);
    }
    tabList.dataset.activeTab = activeName;
    window.dispatchEvent(
      new CustomEvent("order-tab-change", {detail: {tab: activeName}})
    );
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activate(tab.dataset.tab));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let targetIndex = index;
      if (event.key === "ArrowRight") targetIndex = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") targetIndex = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") targetIndex = 0;
      if (event.key === "End") targetIndex = tabs.length - 1;
      activate(tabs[targetIndex].dataset.tab);
      tabs[targetIndex].focus();
    });
  });

  window.addEventListener("popstate", () => {
    const name = new URL(window.location.href).searchParams.get("tab");
    activate(name, false);
  });

  const subsidyForm = document.querySelector("[data-subsidy-form]");
  if (subsidyForm) {
    subsidyForm.addEventListener("submit", (event) => {
      const checkbox = subsidyForm.querySelector(
        'input[name="is_trade_in_subsidy"]'
      );
      if (
        subsidyForm.dataset.wasEnabled === "true" &&
        checkbox &&
        !checkbox.checked &&
        !window.confirm(
          subsidyForm.dataset.hasDocuments === "true"
            ? "關閉補助申請後，既有文件會保留但不再列入待補項目。確定關閉嗎？"
            : "確定要關閉這張訂單的補助申請嗎？"
        )
      ) {
        event.preventDefault();
      }
    });
  }

  activate(requestedTab || savedTab || "order", Boolean(requestedTab));
})();
