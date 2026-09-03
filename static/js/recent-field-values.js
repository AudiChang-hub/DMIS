(() => {
  const MAX_VALUES = 10;
  const MAX_LENGTH = 500;
  const FIELD_SELECTOR = [
    'input[type="text"]',
    'input[type="search"]',
    'input[type="tel"]',
    'input[type="email"]',
    'input[type="url"]',
    "input:not([type])",
    "textarea",
  ].join(",");
  const EXCLUDED_NAME = /(^|[-_])(username|password|passwd|csrf|token|secret|otp|verification|code|uuid|id)([-_]|$)/i;
  const userKey = document.body?.dataset.historyUser || "anonymous";
  let currentField = null;
  let activeIndex = -1;

  const list = document.createElement("div");
  list.className = "recent-field-values";
  list.hidden = true;
  list.setAttribute("role", "listbox");
  list.id = "recent-field-values-list";
  document.body.append(list);
  const floating = window.DMISFloatingList.create(list, closeList);

  function eligible(field) {
    if (!(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement)) return false;
    if (!field.matches(FIELD_SELECTOR)) return false;
    if (!field.name || field.disabled || field.readOnly) return false;
    if (field.autocomplete === "new-password" || field.dataset.noRecentValues !== undefined) return false;
    return !EXCLUDED_NAME.test(field.name);
  }

  function disableNativeAutocomplete(root = document) {
    root.querySelectorAll?.("form, input, textarea, select").forEach(element => {
      element.setAttribute("autocomplete", "off");
    });
  }

  function normalizedFieldName(field) {
    return field.name.replace(/-\d+-/g, "-{row}-");
  }

  function storageKey(field) {
    const formPath = field.form?.getAttribute("action") || window.location.pathname;
    return `dmis-recent-field:v1:${userKey}:${formPath}:${normalizedFieldName(field)}`;
  }

  function recentValues(field) {
    try {
      const values = JSON.parse(window.localStorage.getItem(storageKey(field)) || "[]");
      return Array.isArray(values) ? values.filter(value => typeof value === "string").slice(0, MAX_VALUES) : [];
    } catch (_error) {
      return [];
    }
  }

  function remember(field) {
    if (!eligible(field)) return;
    const value = field.value.trim();
    if (!value || value.length > MAX_LENGTH) return;
    const values = [value, ...recentValues(field).filter(item => item !== value)].slice(0, MAX_VALUES);
    try {
      window.localStorage.setItem(storageKey(field), JSON.stringify(values));
    } catch (_error) {
      // 私密瀏覽或儲存空間不可用時，不影響表單輸入。
    }
  }

  function closeList() {
    if (currentField) currentField.setAttribute("aria-expanded", "false");
    list.hidden = true;
    floating.close();
    list.replaceChildren();
    currentField = null;
    activeIndex = -1;
  }

  function choose(value) {
    if (!currentField) return;
    const field = currentField;
    field.value = value;
    field.dispatchEvent(new Event("input", {bubbles: true}));
    field.dispatchEvent(new Event("change", {bubbles: true}));
    remember(field);
    closeList();
    field.focus({preventScroll: true});
  }

  function render(field) {
    if (!eligible(field)) return closeList();
    const values = recentValues(field);
    if (!values.length) return closeList();
    if (currentField && currentField !== field) closeList();
    currentField = field;
    activeIndex = -1;
    list.replaceChildren();
    const title = document.createElement("div");
    title.className = "recent-field-values__title";
    title.textContent = `最近輸入（${values.length} 筆）`;
    list.append(title);
    values.forEach((value, index) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "recent-field-values__option";
      option.id = `recent-field-value-${index}`;
      option.setAttribute("role", "option");
      option.textContent = value.replace(/\s+/g, " ");
      option.title = value;
      option.addEventListener("mousedown", event => event.preventDefault());
      option.addEventListener("click", () => choose(value));
      list.append(option);
    });
    field.setAttribute("aria-controls", list.id);
    field.setAttribute("aria-expanded", "true");
    floating.open(field);
  }

  function moveActive(direction) {
    const options = [...list.querySelectorAll('[role="option"]')];
    if (!options.length) return;
    activeIndex = (activeIndex + direction + options.length) % options.length;
    options.forEach((option, index) => option.classList.toggle("is-active", index === activeIndex));
    const active = options[activeIndex];
    currentField?.setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({block: "nearest"});
  }

  document.addEventListener("focusin", event => {
    if (eligible(event.target)) render(event.target);
  });
  document.addEventListener("click", event => {
    if (eligible(event.target)) return render(event.target);
    if (!list.contains(event.target)) closeList();
  });
  document.addEventListener("change", event => remember(event.target));
  document.addEventListener("focusout", event => remember(event.target));
  document.addEventListener("submit", event => {
    event.target.querySelectorAll?.(FIELD_SELECTOR).forEach(remember);
  }, true);
  document.addEventListener("keydown", event => {
    if (event.target !== currentField || list.hidden) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      moveActive(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      list.querySelectorAll('[role="option"]')[activeIndex]?.click();
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeList();
    }
  });
  disableNativeAutocomplete();
  new MutationObserver(records => {
    records.forEach(record => record.addedNodes.forEach(node => {
      if (!(node instanceof Element)) return;
      if (node.matches("form, input, textarea, select")) node.setAttribute("autocomplete", "off");
      disableNativeAutocomplete(node);
    }));
  }).observe(document.body, {childList: true, subtree: true});
})();
