(() => {
  const SELECTOR = "select[data-searchable-select]";

  function enhanceSelect(select) {
    if (select.dataset.searchableReady === "1") return;
    select.dataset.searchableReady = "1";
    select.classList.add("searchable-select__native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    const wrapper = document.createElement("div");
    wrapper.className = "searchable-select";
    const includeEmptyOption = select.dataset.searchableIncludeEmpty === "1";
    const emptyAsPlaceholder = select.dataset.searchableEmptyPlaceholder === "1";
    const showSearchIcon = select.dataset.searchableSearchIcon === "1";
    const isMultiple = select.multiple || select.dataset.searchableMultiple === "1";
    if (showSearchIcon) wrapper.classList.add("has-search-icon");
    if (isMultiple) wrapper.classList.add("is-multiple");
    const input = document.createElement("input");
    input.type = "search";
    input.className = "searchable-select__input";
    input.id = `${select.id || select.name}-search`;
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    const basePlaceholder = select.dataset.searchPlaceholder || "輸入關鍵字搜尋";
    input.placeholder = basePlaceholder;
    const label = select.id ? document.querySelector(`label[for="${select.id}"]`) : null;
    if (label) label.htmlFor = input.id;

    const listId = `${select.id || select.name}-search-options`;
    input.setAttribute("aria-controls", listId);
    const list = document.createElement("div");
    list.id = listId;
    list.className = "searchable-select__list";
    list.setAttribute("role", "listbox");
    if (isMultiple) list.setAttribute("aria-multiselectable", "true");
    list.hidden = true;

    const toggle = document.createElement("span");
    toggle.className = "searchable-select__toggle";
    toggle.setAttribute("aria-hidden", "true");
    toggle.innerHTML = '<span class="ui-chevron" aria-hidden="true"></span>';

    if (showSearchIcon) {
      const searchIcon = document.createElement("span");
      searchIcon.className = "searchable-select__search-icon";
      searchIcon.setAttribute("aria-hidden", "true");
      wrapper.append(searchIcon);
    }
    // 複選的已選數量徽章掛在欄名旁（例如「品牌 2」），框內寬度全部留給已選名稱。
    const count = document.createElement("span");
    count.className = "searchable-select__count";
    count.setAttribute("aria-hidden", "true");
    count.hidden = true;
    if (isMultiple && label) label.append(count);
    wrapper.append(input, toggle, list);
    select.insertAdjacentElement("afterend", wrapper);

    const storageKey = `dmis-recent-select:${select.name}`;
    let activeIndex = -1;
    let suppressFocusOpen = false;
    const floating = window.DMISFloatingList.create(list, () => closeList({restore: true}));

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

    function selectedOptions() {
      return [...select.options].filter(option => option.selected && option.value);
    }

    function optionDisplayLabel(option) {
      if (!option || (!option.value && !includeEmptyOption)) return "";
      if (!option.value && emptyAsPlaceholder) return "";
      return option.textContent.trim();
    }

    function selectedLabel() {
      if (isMultiple) return "";
      return optionDisplayLabel(selectedOption());
    }

    function normalizeSearch(value) {
      return String(value || "")
        .normalize("NFKC")
        .toLocaleLowerCase("zh-Hant")
        .replace(/[\s/／_\-–—]+/g, "");
    }

    function closeList({restore = false} = {}) {
      list.hidden = true;
      floating.close();
      wrapper.classList.remove("is-open");
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      activeIndex = -1;
      if (restore) input.value = selectedLabel();
    }

    function choose(option) {
      if (isMultiple) {
        if (!option.value) {
          [...select.options].forEach(item => { item.selected = !item.value; });
        } else {
          option.selected = !option.selected;
          [...select.options].forEach(item => {
            if (!item.value) item.selected = false;
          });
          if (!selectedOptions().length) {
            const emptyOption = [...select.options].find(item => !item.value);
            if (emptyOption) emptyOption.selected = true;
          }
          if (option.selected) remember(option);
        }
        input.value = "";
        wrapper.classList.remove("has-error");
        select.dispatchEvent(new Event("change", {bubbles: true}));
        syncFromSelect();
        renderOptions();
        input.focus();
        return;
      }
      select.value = option.value;
      input.value = optionDisplayLabel(option);
      wrapper.classList.remove("has-error");
      remember(option);
      closeList();
      select.dispatchEvent(new Event("change", {bubbles: true}));
      suppressFocusOpen = true;
      input.focus({preventScroll: true});
      suppressFocusOpen = false;
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
      if (isMultiple) {
        const bulk = document.createElement("div");
        bulk.className = "searchable-select__bulk";
        // 「全選符合項目」是三態勾選框（T-66）：符合目前搜尋的選項全勾＝勾、部分勾＝半勾、都沒勾＝空；
        // 全勾時再點一次取消這些選項，其餘狀態點了就全勾。
        const matching = options.filter(option => option.value);
        const checkedCount = matching.filter(option => option.selected).length;
        const allChecked = matching.length > 0 && checkedCount === matching.length;
        const selectMatches = document.createElement("button");
        selectMatches.type = "button";
        selectMatches.className = "searchable-select__bulk-toggle";
        selectMatches.setAttribute("role", "checkbox");
        selectMatches.setAttribute("aria-checked", allChecked ? "true" : (checkedCount ? "mixed" : "false"));
        selectMatches.textContent = "全選符合項目";
        selectMatches.disabled = !matching.length;
        selectMatches.addEventListener("mousedown", event => event.preventDefault());
        selectMatches.addEventListener("click", () => {
          matching.forEach(option => {
            option.selected = !allChecked;
            if (!allChecked) remember(option);
          });
          select.dispatchEvent(new Event("change", {bubbles: true}));
          syncFromSelect();
          renderOptions(input.value);
          input.focus();
        });
        const clear = document.createElement("button");
        clear.type = "button";
        clear.className = "searchable-select__bulk-action";
        clear.textContent = "清除此欄";
        clear.disabled = !selectedOptions().length;
        clear.addEventListener("mousedown", event => event.preventDefault());
        clear.addEventListener("click", () => {
          [...select.options].forEach(option => { option.selected = !option.value; });
          input.value = "";
          select.dispatchEvent(new Event("change", {bubbles: true}));
          syncFromSelect();
          renderOptions();
          input.focus();
        });
        bulk.append(selectMatches, clear);
        list.append(bulk);
      }
      if (!options.length) {
        const empty = document.createElement("p");
        empty.className = "searchable-select__empty";
        empty.textContent = select.dataset.searchEmptyMessage || "找不到符合的選項";
        list.append(empty);
        return;
      }
      options.slice(0, 80).forEach((option, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.id = `${listId}-${index}`;
        button.dataset.value = option.value;
        button.setAttribute("role", "option");
        button.setAttribute(
          "aria-selected",
          (isMultiple ? option.selected : option.value === select.value) ? "true" : "false"
        );
        button.textContent = option.textContent.trim();
        button.addEventListener("mousedown", event => event.preventDefault());
        button.addEventListener("click", () => choose(option));
        list.append(button);
      });
    }

    function openList(query = "") {
      if (select.disabled) return;
      renderOptions(query);
      floating.open(input);
      wrapper.classList.add("is-open");
      input.setAttribute("aria-expanded", "true");
      floating.position();
    }

    function syncFromSelect() {
      input.disabled = select.disabled;
      wrapper.classList.toggle("is-disabled", select.disabled);
      if (select.disabled) closeList({restore: true});
      renderSelectionSummary();
      if (!wrapper.classList.contains("is-open")) {
        input.value = selectedLabel();
      }
    }

    // 複選的已選項目不再堆在欄位底下（T-66）：收合時把名稱寫在框內（放不下以刪節號收尾），欄名旁徽章顯示已選幾項，
    // 完整清單放在滑鼠提示；開啟下拉打字時提示字自然消失，勾選狀態看清單的勾選框。
    function renderSelectionSummary() {
      if (!isMultiple) return;
      const labels = selectedOptions().map(option => option.textContent.trim().replace(/（\d+）$/, ""));
      wrapper.classList.toggle("has-selection", labels.length > 0);
      input.placeholder = labels.length ? labels.join("、") : basePlaceholder;
      count.hidden = !labels.length;
      count.textContent = String(labels.length);
      if (labels.length) {
        input.title = `已選 ${labels.length} 項：${labels.join("、")}`;
        input.setAttribute("aria-description", input.title);
      } else {
        input.removeAttribute("title");
        input.removeAttribute("aria-description");
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
      if (suppressFocusOpen) return;
      openList();
      if (!isMultiple && selectedLabel()) input.select();
    });
    input.addEventListener("click", () => {
      if (list.hidden) openList(input.value);
    });
    input.addEventListener("input", () => {
      openList(input.value);
    });
    // 有「全部…」空白選項的單選篩選：按搜尋框的 × 清掉文字就等於清除這一欄，不必再從清單點「全部」。
    input.addEventListener("search", () => {
      if (isMultiple || !includeEmptyOption || input.value || !select.value) return;
      const emptyOption = [...select.options].find(option => !option.value);
      if (emptyOption) choose(emptyOption);
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

  function observeDynamicSelects() {
    if (!document.body) return;
    new MutationObserver(records => {
      records.forEach(record => record.addedNodes.forEach(node => {
        if (!(node instanceof Element)) return;
        if (node.matches(SELECTOR)) enhanceSelect(node);
        node.querySelectorAll(SELECTOR).forEach(enhanceSelect);
      }));
    }).observe(document.body, {childList: true, subtree: true});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      init();
      observeDynamicSelects();
    }, {once: true});
  } else {
    init();
    observeDynamicSelects();
  }
})();
