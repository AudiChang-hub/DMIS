(function () {
  "use strict";
  function moveItem(keys, key, offset) {
    const next = [...keys], index = next.indexOf(key), target = index + offset;
    if (index < 0 || target < 0 || target >= next.length) return next;
    [next[index], next[target]] = [next[target], next[index]];
    return next;
  }
  function toggleItem(keys, key, checked) {
    return checked ? (keys.includes(key) ? [...keys] : [...keys, key]) : keys.filter(item => item !== key);
  }
  function matches(text, query, selectedOnly, checked) {
    return (!selectedOnly || checked) && query.trim().toLocaleLowerCase().split(/\s+/).every(word => text.toLocaleLowerCase().includes(word));
  }
  if (typeof module !== "undefined" && module.exports) module.exports = {moveItem, toggleItem, matches};
  if (typeof document === "undefined") return;
  const form = document.querySelector("[data-favorites-form]");
  if (!form) return;
  const options = JSON.parse(document.getElementById("favorite-options-data").textContent);
  const initial = JSON.parse(document.getElementById("favorite-keys-data").textContent);
  const defaults = JSON.parse(document.getElementById("favorite-defaults-data").textContent);
  const byKey = new Map(options.map(item => [item.key, item]));
  const inputs = [...form.querySelectorAll('input[name="favorite"]')];
  let keys = [...initial], submitting = false;
  const picked = form.querySelector("[data-favorites-picked]");
  const search = form.querySelector("[data-favorites-search]");
  const selectedOnly = form.querySelector("[data-favorites-selected-only]");
  const status = form.querySelector("[data-favorites-status]");
  const dirty = () => JSON.stringify(keys) !== JSON.stringify(initial);
  function filter() {
    let count = 0;
    for (const input of inputs) {
      const card = input.closest("[data-favorite-option]");
      card.hidden = !matches(card.dataset.search, search.value, selectedOnly.checked, input.checked);
      if (!card.hidden) count++;
    }
    form.querySelectorAll("[data-favorites-group]").forEach(group => {
      group.hidden = ![...group.querySelectorAll("[data-favorite-option]")].some(card => !card.hidden);
    });
    form.querySelector("[data-favorites-no-results]").hidden = count > 0;
    form.querySelector("[data-favorites-search-count]").textContent = `找到 ${count} 個功能`;
  }
  function actionButton(label, action, key, disabled) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.dataset.action = action;
    button.dataset.key = key;
    button.disabled = disabled;
    button.setAttribute("aria-label", `${label} ${byKey.get(key).label}`);
    return button;
  }
  function render(message) {
    inputs.forEach(input => {
      input.checked = keys.includes(input.value);
      input.closest("[data-favorite-option]").querySelector("small").textContent = input.checked ? "已加入我的最愛" : "加入首頁我的最愛";
    });
    picked.replaceChildren();
    keys.forEach((key, index) => {
      const item = document.createElement("li");
      const label = document.createElement("strong");
      label.textContent = `${index + 1}. ${byKey.get(key).label}`;
      const actions = document.createElement("div");
      actions.className = "favorite-item-actions";
      actions.append(actionButton("上移", "up", key, index === 0), actionButton("下移", "down", key, index === keys.length - 1), actionButton("移除", "remove", key, false));
      item.append(label, actions);
      picked.append(item);
    });
    form.querySelector("[data-favorites-order]").value = keys.join(",");
    form.querySelectorAll("[data-favorites-count]").forEach(counter => { counter.textContent = keys.length; });
    form.querySelector("[data-favorites-empty]").hidden = keys.length > 0;
    status.textContent = message || (dirty() ? "有尚未儲存的變更。" : "目前選取與已載入設定相同。");
    filter();
  }
  function changed(message) {
    render(message);
    form.dispatchEvent(new Event("input", {bubbles: true}));
  }
  inputs.forEach(input => input.addEventListener("change", () => {
    keys = toggleItem(keys, input.value, input.checked);
    changed();
  }));
  picked.addEventListener("click", event => {
    const button = event.target.closest("button[data-action]");
    if (!button || button.disabled) return;
    const {key, action} = button.dataset;
    keys = action === "remove" ? toggleItem(keys, key, false) : moveItem(keys, key, action === "up" ? -1 : 1);
    changed(`${byKey.get(key).label}已${action === "remove" ? "移除" : "移動"}，儲存後生效。`);
    // 重建預覽後保留鍵盤焦點，邊界改聚焦到同列另一個可用操作。
    const candidates = [...picked.querySelectorAll("button")].filter(item => item.dataset.key === key && !item.disabled);
    const target = candidates.find(item => item.dataset.action === action) || candidates[0];
    if (target) target.focus();
    else {
      const input = inputs.find(item => item.value === key);
      if (input && !input.closest("[data-favorite-option]").hidden) input.focus();
      else search.focus();
    }
  });
  search.addEventListener("input", filter);
  selectedOnly.addEventListener("change", filter);
  form.querySelector("[data-favorites-default]").addEventListener("click", () => { keys = [...defaults]; changed("已載入預設，儲存後才會生效。"); });
  form.querySelector("[data-favorites-clear]").addEventListener("click", () => { keys = []; changed("已取消全部勾選，儲存後才會生效。"); });
  form.addEventListener("submit", () => { submitting = true; });
  form.querySelector("[data-favorites-cancel]").addEventListener("click", () => { submitting = true; });
  window.addEventListener("beforeunload", event => {
    if (dirty() && !submitting) { event.preventDefault(); event.returnValue = ""; }
  });
  form.querySelector("[data-favorites-tools]").hidden = false;
  form.querySelector("[data-favorites-preview]").hidden = false;
  render();
})();
