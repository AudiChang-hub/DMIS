// 手機版訂單步驟面板（T-250 B 案，使用者 2026-11-19）：精簡列的「第 N／7 步」按鈕從底部升起面板，
// 依序是訂單總覽、七個步驟與狀態、「其他」。清單每次打開時依左側步驟欄重建，狀態與「正在看」都以步驟欄為準；
// 選了步驟就交給步驟欄原本的切換邏輯（點對應的步驟），不另寫一套。
(() => {
  const sheet = document.querySelector("[data-order-step-sheet]");
  const opener = document.querySelector("[data-order-step-sheet-open]");
  const nav = document.querySelector("[data-order-nav]");
  if (!sheet || !opener || !nav || typeof sheet.showModal !== "function") return;
  const body = sheet.querySelector("[data-order-step-sheet-body]");
  const meta = sheet.querySelector("[data-order-step-sheet-meta]");
  const overview = document.querySelector(".order-step-overview[data-order-overview-open]");
  const position = opener.querySelector("[data-order-step-entry-position]");
  const label = opener.querySelector("[data-order-step-entry-label]");
  const ownerName = meta?.textContent.trim() || "";
  const tabs = () => [...nav.querySelectorAll(".order-step-tab[data-step-link]")];
  const mainTabs = () => tabs().filter((tab) => tab.classList.contains("is-main"));
  const viewing = () => tabs().find((tab) => tab.getAttribute("aria-selected") === "true") || tabs().find((tab) => tab.classList.contains("is-active"));
  const text = (tab, selector) => tab.querySelector(selector)?.textContent.trim() || "";
  const stateOf = (tab) => (tab.className.match(/\bis-(done|current|todo|optional|locked|reference)\b/) || [])[1] || "";

  // 「正在看」：按鈕上的第 N／7 步跟著目前打開的步驟走。
  const describe = (tab) => {
    const index = mainTabs().indexOf(tab);
    return index >= 0 ? `第 ${index + 1}／${mainTabs().length} 步` : "其他";
  };
  const refreshEntry = () => {
    const tab = viewing();
    if (!tab) return;
    if (position) position.textContent = `${describe(tab)}・點這裡換步驟`;
    if (label) label.textContent = text(tab, ".order-step-tab__label");
  };

  const item = (tab, current) => {
    const button = document.createElement("button");
    const state = stateOf(tab);
    button.type = "button";
    button.className = `order-step-sheet__item is-${state}`;
    button.dataset.sheetStep = tab.dataset.stepLink;
    if (tab === current) button.setAttribute("aria-current", "step");
    const marker = document.createElement("span");
    marker.className = "order-step-sheet__marker";
    marker.setAttribute("aria-hidden", "true");
    const index = mainTabs().indexOf(tab);
    marker.textContent = index >= 0 ? String(index + 1) : "";
    const name = document.createElement("span");
    name.className = "order-step-sheet__name";
    name.textContent = text(tab, ".order-step-tab__label");
    const status = document.createElement("span");
    status.className = "order-step-sheet__state";
    // 步驟欄的「目前步驟」是訂單進度，面板裡改叫「目前進度」，與「正在看」分開。
    status.textContent = state === "current" ? "目前進度" : text(tab, ".order-step-tab__state");
    button.append(marker, name, status);
    if (tab === current) {
      const here = document.createElement("span");
      here.className = "order-step-sheet__here";
      here.textContent = "正在看";
      name.append(here);
    }
    return button;
  };
  const build = () => {
    const current = viewing();
    body.replaceChildren();
    if (meta) meta.textContent = current ? `${ownerName}・正在看${describe(current)}` : ownerName;
    if (overview) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "order-step-sheet__overview";
      button.dataset.sheetOverview = "";
      button.innerHTML = '<svg aria-hidden="true" viewBox="0 0 20 20" width="18" height="18"><rect x="3" y="2.5" width="14" height="15" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6.5 7h7M6.5 10h7M6.5 13h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg><span>訂單總覽</span><small>唯讀・查看與複製</small>';
      body.append(button);
    }
    const list = (items, labelText) => {
      if (!items.length) return;
      const group = document.createElement("div");
      group.className = "order-step-sheet__group";
      if (labelText) {
        const heading = document.createElement("p");
        heading.className = "order-step-sheet__group-label";
        heading.textContent = labelText;
        group.append(heading);
      }
      items.forEach((tab) => group.append(item(tab, current)));
      body.append(group);
    };
    list(mainTabs(), "");
    list(tabs().filter((tab) => !tab.classList.contains("is-main")), "其他");
  };

  const open = () => {
    build();
    sheet.showModal();
    document.documentElement.classList.add("has-step-sheet-open");
    opener.setAttribute("aria-expanded", "true");
    (body.querySelector('[aria-current="step"]') || body.querySelector("button"))?.focus({ preventScroll: true });
    body.querySelector('[aria-current="step"]')?.scrollIntoView({ block: "nearest" });
  };
  const close = () => { if (sheet.open) sheet.close(); };
  sheet.addEventListener("close", () => {
    document.documentElement.classList.remove("has-step-sheet-open");
    opener.setAttribute("aria-expanded", "false");
  });

  opener.setAttribute("aria-expanded", "false");
  opener.addEventListener("click", open);
  sheet.querySelector("[data-order-step-sheet-close]")?.addEventListener("click", () => { close(); opener.focus({ preventScroll: true }); });
  sheet.addEventListener("cancel", (event) => { event.preventDefault(); close(); opener.focus({ preventScroll: true }); });
  sheet.addEventListener("click", (event) => {
    // 點面板外的暗色區域關閉。
    if (event.target === sheet) { close(); opener.focus({ preventScroll: true }); return; }
    if (event.target.closest("[data-sheet-overview]")) {
      close();
      overview?.click();  // 總覽由 order-overview.js 打開，關閉後焦點回到精簡列的「總覽」鈕。
      return;
    }
    const choice = event.target.closest("[data-sheet-step]");
    if (!choice) return;
    const tab = tabs().find((candidate) => candidate.dataset.stepLink === choice.dataset.sheetStep);
    close();
    opener.focus({ preventScroll: true });
    tab?.click();
  });
  // 上下鍵在清單裡移動（Tab 也可以，dialog 會把焦點留在面板內）。
  sheet.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const buttons = [...body.querySelectorAll("button")];
    const index = buttons.indexOf(document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    buttons[(index + (event.key === "ArrowDown" ? 1 : buttons.length - 1)) % buttons.length].focus();
  });

  new MutationObserver(refreshEntry).observe(nav, { subtree: true, attributes: true, attributeFilter: ["aria-selected", "class"] });
  refreshEntry();
})();
