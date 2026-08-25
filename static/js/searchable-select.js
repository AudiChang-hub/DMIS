(() => {
  const SELECTOR = "select[data-searchable-select]";

  function enhanceSelect(select) {
    if (select.dataset.searchableReady === "1") return;
    select.dataset.searchableReady = "1";
    select.classList.add("searchable-select__native");

    const wrapper = document.createElement("div");
    wrapper.className = "searchable-select";
    const input = document.createElement("input");
    input.type = "search";
    input.className = "searchable-select__input";
    input.id = `${select.id || select.name}-search`;
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.placeholder = select.dataset.searchPlaceholder || "輸入關鍵字搜尋";
    const label = select.id ? document.querySelector(`label[for="${select.id}"]`) : null;
    if (label) label.htmlFor = input.id;

    const listId = `${select.id || select.name}-search-options`;
    input.setAttribute("aria-controls", listId);
    const list = document.createElement("div");
    list.id = listId;
    list.className = "searchable-select__list";
    list.setAttribute("role", "listbox");
    list.hidden = true;

    const toggle = document.createElement("span");
    toggle.className = "searchable-select__toggle";
    toggle.setAttribute("aria-hidden", "true");
    toggle.innerHTML = '<span class="ui-chevron" aria-hidden="true"></span>';

    wrapper.append(input, toggle, list);
    select.insertAdjacentElement("afterend", wrapper);

    const storageKey = `dmis-recent-select:${select.name}`;
    const includeEmptyOption = select.dataset.searchableIncludeEmpty === "1";
    let activeIndex = -1;

    function availableOptions() {
      return [...select.options].filter(option => (
        (option.value || includeEmptyOption) && !option.disabled && !option.hidden
      ));
    }

    function recentValues() {
      try {
        return JSON.parse(localStorage.getItem(storageKey) || "[]");
      } catch (_error) {
        return [];
      }
    }

    function remember(option) {
      if (!option.value) return;
      const values = [option.value, ...recentValues().filter(value => value !== option.value)].slice(0, 5);
      try {
        localStorage.setItem(storageKey, JSON.stringify(values));
      } catch (_error) {
        // 私密模式或儲存空間不可用時，不影響選擇功能。
      }
    }

    function selectedOption() {
      return [...select.options].find(option => option.value === select.value);
    }

    function selectedLabel() {
      const option = selectedOption();
      return option && (option.value || includeEmptyOption) ? option.textContent.trim() : "";
    }

    function normalizeSearch(value) {
      return String(value || "")
        .normalize("NFKC")
        .toLocaleLowerCase("zh-Hant")
        .replace(/[\s/／_\-–—]+/g, "");
    }

    function closeList({restore = false} = {}) {
      list.hidden = true;
      wrapper.classList.remove("is-open");
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      activeIndex = -1;
      if (restore) input.value = selectedLabel();
    }

    function choose(option) {
      select.value = option.value;
      input.value = option.textContent.trim();
      wrapper.classList.remove("has-error");
      remember(option);
      closeList();
      select.dispatchEvent(new Event("change", {bubbles: true}));
      input.focus();
    }

    function renderOptions(query = "") {
      const needle = normalizeSearch(query);
      const recents = recentValues();
      const options = availableOptions()
        .filter(option => !needle || normalizeSearch(option.textContent).includes(needle))
        .sort((left, right) => {
          const leftIndex = recents.indexOf(left.value);
          const rightIndex = recents.indexOf(right.value);
          if (leftIndex >= 0 || rightIndex >= 0) {
            if (leftIndex < 0) return 1;
            if (rightIndex < 0) return -1;
            return leftIndex - rightIndex;
          }
          if (!left.value || !right.value) return left.value ? 1 : -1;
          return left.textContent.localeCompare(right.textContent, "zh-Hant");
        });

      list.replaceChildren();
      activeIndex = -1;
      if (!options.length) {
        const empty = document.createElement("p");
        empty.className = "searchable-select__empty";
        empty.textContent = "找不到符合的選項";
        list.append(empty);
        return;
      }
      options.slice(0, 80).forEach((option, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.id = `${listId}-${index}`;
        button.dataset.value = option.value;
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", option.value === select.value ? "true" : "false");
        button.textContent = option.textContent.trim();
        button.addEventListener("mousedown", event => event.preventDefault());
        button.addEventListener("click", () => choose(option));
        list.append(button);
      });
    }

    function openList(query = "") {
      if (select.disabled) return;
      renderOptions(query);
      list.hidden = false;
      wrapper.classList.add("is-open");
      input.setAttribute("aria-expanded", "true");
    }

    function syncFromSelect() {
      input.disabled = select.disabled;
      wrapper.classList.toggle("is-disabled", select.disabled);
      if (!wrapper.classList.contains("is-open")) {
        input.value = selectedLabel();
      }
    }

    function moveActive(direction) {
      const buttons = [...list.querySelectorAll('[role="option"]')];
      if (!buttons.length) return;
      activeIndex = (activeIndex + direction + buttons.length) % buttons.length;
      buttons.forEach((button, index) => button.classList.toggle("is-active", index === activeIndex));
      const active = buttons[activeIndex];
      input.setAttribute("aria-activedescendant", active.id);
      active.scrollIntoView({block: "nearest"});
    }

    input.addEventListener("focus", () => {
      openList();
      if (selectedLabel()) input.select();
    });
    input.addEventListener("click", () => {
      if (list.hidden) openList(input.value);
    });
    input.addEventListener("input", () => {
      openList(input.value);
    });
    input.addEventListener("keydown", event => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (list.hidden) openList();
        moveActive(event.key === "ArrowDown" ? 1 : -1);
      } else if (event.key === "Enter" && !list.hidden) {
        const options = [...list.querySelectorAll('[role="option"]')];
        const target = options[activeIndex >= 0 ? activeIndex : 0];
        if (target) {
          event.preventDefault();
          target.click();
        }
      } else if (event.key === "Escape") {
        event.preventDefault();
        closeList({restore: true});
      }
    });
    input.addEventListener("blur", () => setTimeout(() => closeList({restore: true}), 120));
    select.addEventListener("change", syncFromSelect);
    select.addEventListener("invalid", event => {
      event.preventDefault();
      wrapper.classList.add("has-error");
      input.focus();
    });

    new MutationObserver(() => {
      syncFromSelect();
      if (!list.hidden) renderOptions(input.value);
    }).observe(select, {childList: true, subtree: true, attributes: true});

    syncFromSelect();
  }

  function init() {
    document.querySelectorAll(SELECTOR).forEach(enhanceSelect);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, {once: true});
  } else {
    init();
  }
})();
