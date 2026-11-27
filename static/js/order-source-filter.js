// 全部訂單「車行／平台」多選篩選（T-323，使用者 2026-11-27）。
// 選項分「本店／車行／網路平台」三組，每組最上面有整組選項；可以打字縮小範圍、可以多選。
// 勾選只改篩選列上的顯示與隱藏欄位 src（逗號分隔），按「套用」才查，不會每勾一個就送出。
// 選項順序與摘要文字的規則和 sales/services/order_source_filter.py 一致，改一邊要改另一邊。
(() => {
  "use strict";

  // ---------- 純資料規則（tests/frontend/order-source-filter.test.cjs） ----------
  const normalize = (value) => String(value || "").toLowerCase().replace(/\s+/g, "");

  const groupOf = (groups, value) => groups.find((group) => group.options.some((option) => option.value === value));

  // 依選項順序排好；整組選了就只留整組，不再逐家列。不在選項裡的值丟掉。
  const canonical = (tokens, groups) => {
    const chosen = new Set(tokens);
    const result = [];
    groups.forEach((group) => {
      if (chosen.has(group.key)) { result.push(group.key); return; }
      group.options.forEach((option) => { if (chosen.has(option.value)) result.push(option.value); });
    });
    return result;
  };

  const parse = (value, groups) => canonical(String(value || "").split(",").map((part) => part.trim()).filter(Boolean), groups);

  const isSelected = (tokens, value, groups) => {
    if (tokens.includes(value)) return true;
    const group = groupOf(groups, value);
    return Boolean(group && tokens.includes(group.key));
  };

  const toggle = (tokens, value, groups) => {
    const chosen = new Set(tokens);
    const whole = groups.find((group) => group.key === value);
    if (whole) {
      if (chosen.has(value)) chosen.delete(value);
      else {
        whole.options.forEach((option) => chosen.delete(option.value));
        chosen.add(value);
      }
      return canonical([...chosen], groups);
    }
    const group = groupOf(groups, value);
    if (!group) return canonical([...chosen], groups);
    if (chosen.has(group.key)) {
      // 整組已選時取消其中一家：整組改成其餘各家。
      chosen.delete(group.key);
      group.options.forEach((option) => { if (option.value !== value) chosen.add(option.value); });
    } else if (chosen.has(value)) chosen.delete(value);
    else chosen.add(value);
    return canonical([...chosen], groups);
  };

  const labelsOf = (tokens, groups) => {
    const labels = [];
    groups.forEach((group) => {
      if (tokens.includes(group.key)) { labels.push({ value: group.key, label: group.all, whole: true }); return; }
      group.options.forEach((option) => { if (tokens.includes(option.value)) labels.push({ value: option.value, label: option.label }); });
    });
    return labels;
  };

  // 「示範車行甲、示範車行乙」；超過兩項寫「示範車行甲 等 3 家」（含整組時單位改「項」）。
  const summarize = (tokens, groups) => {
    const labels = labelsOf(tokens, groups);
    if (labels.length <= 2) return labels.map((item) => item.label).join("、");
    return `${labels[0].label} 等 ${labels.length} ${labels.some((item) => item.whole) ? "項" : "家"}`;
  };

  // 把符合的字切出來標色：[{ text, match }]。
  const highlight = (label, text) => {
    const needle = String(text || "").trim().toLowerCase();
    const index = needle ? String(label).toLowerCase().indexOf(needle) : -1;
    if (index < 0) return [{ text: String(label), match: false }];
    return [
      { text: label.slice(0, index), match: false },
      { text: label.slice(index, index + needle.length), match: true },
      { text: label.slice(index + needle.length), match: false },
    ].filter((part) => part.text);
  };

  // 打字縮小範圍：只留名稱符合的；整組選項在沒打字、或自己的名稱符合時才列。
  const matchGroups = (groups, text) => {
    const needle = normalize(text);
    return groups.map((group) => ({
      key: group.key,
      label: group.label,
      all: !needle || normalize(group.all).includes(needle) ? { value: group.key, label: group.all } : null,
      options: group.options.filter((option) => !needle || normalize(option.label).includes(needle)),
    })).filter((group) => group.all || group.options.length);
  };

  const api = { normalize, canonical, parse, isSelected, toggle, labelsOf, summarize, highlight, matchGroups };
  if (typeof module !== "undefined") module.exports = api;
  if (typeof document === "undefined") return;

  // ---------- 畫面 ----------
  const root = document.querySelector("[data-order-source-filter]");
  const source = document.getElementById("order-source-options");
  if (!root || !source) return;
  const groups = JSON.parse(source.textContent);
  const form = root.closest("form");
  const value = root.querySelector("[data-order-source-value]");
  const button = root.querySelector("[data-order-source-button]");
  const summary = root.querySelector("[data-order-source-summary]");
  const reset = root.querySelector("[data-order-source-reset]");
  const pop = root.querySelector("[data-order-source-pop]");
  const input = root.querySelector("[data-order-source-input]");
  const list = root.querySelector("[data-order-source-list]");
  const status = root.querySelector("[data-order-source-status]");
  const mobile = window.matchMedia("(max-width: 860px)");
  const EMPTY_TEXT = summary.dataset.empty || "全部";

  let tokens = parse(value.value, groups);
  let active = -1;

  const el = (tag, className, attrs = {}) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    Object.entries(attrs).forEach(([key, attr]) => node.setAttribute(key, attr));
    return node;
  };
  const optionNodes = () => [...list.querySelectorAll('[role="option"]')];

  const syncField = () => {
    const text = summarize(tokens, groups);
    summary.textContent = text || EMPTY_TEXT;
    summary.classList.toggle("is-empty", !text);
    button.title = labelsOf(tokens, groups).map((item) => item.label).join("、");
    reset.hidden = !tokens.length;
  };

  const syncOptions = () => {
    optionNodes().forEach((node) => node.setAttribute("aria-selected", String(isSelected(tokens, node.dataset.value, groups))));
    const count = labelsOf(tokens, groups).length;
    status.textContent = list.childElementCount
      ? (count ? `已選 ${count} 項，按「套用」才會查。` : "可以多選，選好按「套用」才會查。")
      : `找不到符合「${input.value.trim()}」的車行或平台。`;
  };

  const setActive = (index, { scroll = true } = {}) => {
    const nodes = optionNodes();
    active = nodes.length ? Math.max(0, Math.min(index, nodes.length - 1)) : -1;
    nodes.forEach((node, position) => node.classList.toggle("is-active", position === active));
    if (active < 0) { input.removeAttribute("aria-activedescendant"); return; }
    input.setAttribute("aria-activedescendant", nodes[active].id);
    if (scroll) nodes[active].scrollIntoView({ block: "nearest" });
  };

  const optionNode = (item, text, extraClass = "") => {
    const node = el("div", `order-source-option${extraClass}`, { role: "option", id: `order-source-option-${item.value}`, "data-value": item.value });
    node.append(el("span", "order-source-option__box", { "aria-hidden": "true" }));
    const label = el("span", "order-source-option__label");
    highlight(item.label, text).forEach((part) => {
      if (!part.match) { label.append(part.text); return; }
      const mark = el("mark");
      mark.textContent = part.text;
      label.append(mark);
    });
    node.append(label);
    if (item.inactive) {
      const tag = el("small", "order-source-option__tag");
      tag.textContent = "已停用";
      node.append(tag);
    }
    return node;
  };

  const renderList = () => {
    const text = input.value;
    list.replaceChildren(...matchGroups(groups, text).map((group) => {
      const section = el("div", "order-source-group", { role: "group", "aria-label": group.label });
      const title = el("div", "order-source-group__title", { "aria-hidden": "true" });
      title.textContent = group.label;
      section.append(title);
      if (group.all) section.append(optionNode(group.all, text, " order-source-option--all"));
      group.options.forEach((option) => section.append(optionNode(option, text)));
      return section;
    }));
    syncOptions();
    setActive(normalize(text) ? 0 : -1, { scroll: false });
  };

  const commit = (next) => {
    tokens = next;
    value.value = tokens.join(",");
    syncField();
    syncOptions();
  };

  const isOpen = () => !pop.hidden;
  const open = () => {
    if (isOpen()) return;
    input.value = "";
    pop.hidden = false;
    button.setAttribute("aria-expanded", "true");
    renderList();
    list.scrollTop = 0;
    // 手機一打開就聚焦輸入框會跳出鍵盤、蓋住清單，所以手機先不聚焦，要打字再點。
    if (!mobile.matches) input.focus({ preventScroll: true });
  };
  const close = ({ focus = false } = {}) => {
    if (!isOpen()) return;
    pop.hidden = true;
    button.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    if (focus) button.focus({ preventScroll: true });
  };

  button.addEventListener("click", () => (isOpen() ? close() : open()));
  reset.addEventListener("click", () => { commit([]); button.focus({ preventScroll: true }); });
  root.querySelector("[data-order-source-clear]").addEventListener("click", () => { commit([]); input.focus({ preventScroll: true }); });
  root.querySelector("[data-order-source-done]").addEventListener("click", () => close({ focus: true }));
  input.addEventListener("input", renderList);
  list.addEventListener("click", (event) => {
    const node = event.target.closest('[role="option"]');
    if (!node) return;
    commit(toggle(tokens, node.dataset.value, groups));
    setActive(optionNodes().indexOf(node), { scroll: false });
  });
  // 點清單不要讓輸入框失焦（鍵盤操作可以接著用）。
  list.addEventListener("mousedown", (event) => event.preventDefault());

  root.addEventListener("keydown", (event) => {
    if (!isOpen()) {
      if (event.target === button && (event.key === "ArrowDown" || event.key === "ArrowUp")) { event.preventDefault(); open(); }
      return;
    }
    if (event.key === "Escape") {
      // 只關選擇器，不連手機的篩選面板一起關。
      event.preventDefault();
      event.stopPropagation();
      close({ focus: true });
      return;
    }
    if (event.target !== input) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const size = optionNodes().length;
      if (size) setActive(active < 0 ? (event.key === "ArrowDown" ? 0 : size - 1) : (active + (event.key === "ArrowDown" ? 1 : size - 1)) % size);
    } else if (event.key === "Home" || event.key === "End") {
      if (!optionNodes().length) return;
      event.preventDefault();
      setActive(event.key === "Home" ? 0 : optionNodes().length - 1);
    } else if (event.key === "Enter") {
      // 輸入框在篩選表單裡：Enter 只勾選目前這一項，不送出表單。
      event.preventDefault();
      const node = optionNodes()[active];
      if (node) commit(toggle(tokens, node.dataset.value, groups));
    }
  });
  document.addEventListener("pointerdown", (event) => { if (isOpen() && !root.contains(event.target)) close(); });
  root.addEventListener("focusout", (event) => {
    if (isOpen() && event.relatedTarget && !root.contains(event.relatedTarget)) close();
  });
  // 篩選面板的「清除」、沒套用就關掉、小標籤移除，都會直接改隱藏欄位；改完通知這裡重新對齊顯示。
  form?.addEventListener("order-filter:sync", () => {
    tokens = parse(value.value, groups);
    syncField();
    if (isOpen()) syncOptions();
  });
  form?.addEventListener("submit", () => close());

  root.classList.add("is-ready");
  // 網址帶了選項以外的編號時（例如手動改網址），先保留伺服器算好的顯示，等使用者動了選擇再重算。
  if (tokens.join(",") === value.value) syncField();
})();
