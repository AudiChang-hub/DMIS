(() => {
  "use strict";

  // T-308 B：庫存列表的「實際位置」直接改，選了就存，存好可以復原。
  // T-317 B：每列換成一顆按鈕，點開是整頁共用的一份選擇器（桌機在按鈕下方，手機從底部打開 <dialog>），
  // 可以打字篩選、分「本店／車行」兩組。每列原本的 <select> 保留（沒有 JS 時照常可用），JS 啟動後隱藏，當作存值的地方。
  // 防誤觸：只有點選項或按 Enter 才存；捲動、點外面、Esc、Tab 都只關閉，不存；選回目前位置不送出。
  const source = document.getElementById("inventory-location-options");
  if (!source) return;
  const csrf = source.dataset.csrf || "";
  const MOBILE = window.matchMedia("(max-width: 600px)");
  const HOME_GROUP = "本店";
  const DEALER_GROUP = "車行";

  const normalize = (value) => String(value || "").toLowerCase().replace(/\s+/g, "");

  const optionFor = (select, value) => Array.from(select.options).find((option) => option.value === value);

  const ensureOption = (select, value, label) => {
    if (optionFor(select, value)) return;
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label || value;
    select.append(option);
  };

  // 第一次點開時才換成完整選項；目前位置若是已停用的車行，保留原本那一項。
  const populate = (select) => {
    if (select.dataset.locationLoaded) return;
    select.dataset.locationLoaded = "1";
    const current = select.dataset.locationCurrent;
    const original = select.options[0];
    const label = original ? original.textContent : current;
    select.replaceChildren(source.content.cloneNode(true));
    ensureOption(select, current, label);
    select.value = current;
  };

  const wrapFor = (select) => select.closest("[data-inventory-location]");
  const statusFor = (select) => wrapFor(select).querySelector("[data-location-status]");
  const buttonFor = (select) => wrapFor(select).querySelector("[data-location-button]");
  const labelOf = (select) => (select.selectedOptions[0] || select.options[0])?.textContent || "";

  const syncButton = (select) => {
    const button = buttonFor(select);
    if (!button) return;
    const label = labelOf(select);
    button.querySelector("[data-location-label]").textContent = label;
    button.setAttribute("aria-label", `實際位置 ${wrapFor(select).dataset.identifier}：${label}（點開可改，選了就存）`);
  };

  const showStatus = (select, text, { tone = "", undo = null } = {}) => {
    const status = statusFor(select);
    status.replaceChildren();
    const message = document.createElement("span");
    message.textContent = text;
    status.append(message);
    if (undo) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "inventory-location__undo";
      button.textContent = "復原";
      button.setAttribute("aria-label", `復原 ${wrapFor(select).dataset.identifier} 的位置`);
      button.addEventListener("click", undo, { once: true });
      status.append(button);
    }
    status.classList.toggle("is-error", tone === "error");
    status.classList.toggle("is-saving", tone === "saving");
    status.hidden = false;
  };

  const post = async (select, fields) => {
    const wrap = wrapFor(select);
    const button = buttonFor(select);
    const body = new FormData();
    body.append("csrfmiddlewaretoken", csrf);
    Object.entries(fields).forEach(([key, value]) => body.append(key, value));
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 12000);
    wrap.classList.add("is-saving");
    button?.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(wrap.dataset.url, {
        method: "POST",
        body,
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 403) payload.message = payload.message || "沒有改位置的權限。";
      return { ok: response.ok && payload.ok, payload };
    } catch (error) {
      return {
        ok: false,
        payload: { message: error.name === "AbortError" ? "儲存等候逾時，位置沒有改，請再試一次。" : "連線失敗，位置沒有改，請再試一次。" },
      };
    } finally {
      window.clearTimeout(timeoutId);
      wrap.classList.remove("is-saving");
      button?.removeAttribute("aria-busy");
    }
  };

  // 失敗時退回伺服器回報的目前位置（可能剛被別人改過）。
  const settle = (select, payload) => {
    if (payload.value !== undefined) {
      ensureOption(select, payload.value, payload.label);
      select.dataset.locationCurrent = payload.value;
    }
    select.value = select.dataset.locationCurrent;
    syncButton(select);
  };

  const save = async (select) => {
    const target = select.value;
    const current = select.dataset.locationCurrent;
    if (target === current) return;
    if (select.dataset.locationSaving) {
      select.dataset.locationQueued = "1";
      return;
    }
    select.dataset.locationSaving = "1";
    showStatus(select, "儲存中…", { tone: "saving" });
    const { ok, payload } = await post(select, { location: target, expected: current });
    delete select.dataset.locationSaving;
    if (!ok) {
      settle(select, payload);
      showStatus(select, payload.message || "無法改位置，請稍後再試。", { tone: "error" });
      return;
    }
    settle(select, payload);
    if (payload.changed) {
      showStatus(select, `已改放到 ${payload.label}`, {
        undo: () => undo(select, payload.previous_value, payload.previous_label),
      });
    } else {
      showStatus(select, payload.message);
    }
    if (select.dataset.locationQueued) {
      delete select.dataset.locationQueued;
      save(select);
    }
  };

  const undo = async (select, previousValue, previousLabel) => {
    if (select.dataset.locationSaving) return;
    select.dataset.locationSaving = "1";
    showStatus(select, "復原中…", { tone: "saving" });
    const { ok, payload } = await post(select, {
      location: previousValue, expected: select.dataset.locationCurrent, undo: "1",
    });
    delete select.dataset.locationSaving;
    settle(select, payload);
    if (!ok) {
      showStatus(select, payload.message || "無法復原，請稍後再試。", { tone: "error" });
      return;
    }
    showStatus(select, `已復原，放回 ${payload.label || previousLabel}`);
  };

  // ---------- 每列的按鈕 ----------
  document.querySelectorAll("[data-inventory-location]").forEach((wrap) => {
    const select = wrap.querySelector(".inventory-location__select");
    if (!select) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "inventory-location__button";
    button.dataset.locationButton = "";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    const label = document.createElement("span");
    label.className = "inventory-location__label";
    label.dataset.locationLabel = "";
    button.append(label);
    select.before(button);
    select.tabIndex = -1;
    wrap.classList.add("is-enhanced");
    syncButton(select);
  });

  // ---------- 整頁共用的選擇器（第一次點開才建立） ----------
  let ui = null;
  let openSelect = null;
  let opener = null;
  let options = [];
  let active = -1;

  const el = (tag, className, attrs = {}) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  };

  const build = () => {
    const picker = el("div", "inventory-location-picker");
    const input = el("input", "transfer-out-field__input transfer-out-field__input--name inventory-location-picker__input", {
      type: "text", role: "combobox", autocomplete: "off", spellcheck: "false", placeholder: "打字找門市或車行",
      "aria-autocomplete": "list", "aria-expanded": "true", "aria-controls": "inventory-location-listbox",
      "aria-label": "打字找門市或車行", "data-no-recent-values": "",
    });
    const list = el("div", "transfer-out-suggest inventory-location-picker__list", {
      id: "inventory-location-listbox", role: "listbox", "aria-label": "實際位置選項",
    });
    const hint = el("p", "inventory-location-picker__hint");
    picker.append(input, list, hint);

    const pop = el("div", "inventory-location-pop", { "data-location-pop": "" });
    pop.hidden = true;
    document.body.append(pop);

    const dialog = el("dialog", "transfer-out-dialog inventory-location-sheet", { "aria-labelledby": "inventory-location-sheet-title" });
    const body = el("div", "transfer-out-form inventory-location-sheet__body");
    const head = el("header", "transfer-out-dialog__head");
    const title = el("h2", "", { id: "inventory-location-sheet-title", tabindex: "-1" });
    title.textContent = "改實際位置";
    const meta = el("p");
    head.append(title, meta);
    const slot = el("div", "inventory-location-sheet__slot");
    const actions = el("div", "transfer-out-dialog__actions");
    const cancel = el("button", "button ghost", { type: "button" });
    cancel.textContent = "取消";
    actions.append(cancel);
    body.append(head, slot, actions);
    dialog.append(body);
    document.body.append(dialog);

    input.addEventListener("input", () => render());
    input.addEventListener("keydown", onKeydown);
    // 先選再失焦：按住選項時不讓輸入框失焦。
    list.addEventListener("mousedown", (event) => event.preventDefault());
    // 只有 click 才存：手機在清單上捲動（touchmove）不會觸發。
    list.addEventListener("click", (event) => {
      const option = event.target.closest("[role='option']");
      if (option) choose(options.findIndex((item) => item.element === option));
    });
    cancel.addEventListener("click", () => close({ restoreFocus: true }));
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      close({ restoreFocus: true });
    });
    // 點底部面板外面（遮罩）也關閉，不存。
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const box = body.getBoundingClientRect();
      const inside = event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom;
      if (!inside) close({ restoreFocus: true });
    });
    ui = { picker, input, list, hint, pop, dialog, title, meta, slot };
  };

  const groupsFor = (select) => {
    const groups = new Map([[HOME_GROUP, []], [DEALER_GROUP, []]]);
    const add = (group, option, stale) => {
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push({ value: option.value, label: option.textContent, stale });
    };
    Array.from(select.children).forEach((child) => {
      if (child.tagName === "OPTGROUP") {
        Array.from(child.children).forEach((option) => add(child.label, option, false));
        return;
      }
      // 不在整頁清單裡的選項＝這台車原本放的、已停用的車行（ensureOption 補上的）。
      const home = child.value === "" || child.value.startsWith("home-");
      add(home ? HOME_GROUP : DEALER_GROUP, child, !home);
    });
    return Array.from(groups, ([label, items]) => ({ label, items })).filter((group) => group.items.length);
  };

  const highlight = (target, text, query) => {
    const index = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1;
    if (index < 0) {
      target.textContent = text;
      return;
    }
    const mark = document.createElement("mark");
    mark.textContent = text.slice(index, index + query.length);
    target.append(text.slice(0, index), mark, text.slice(index + query.length));
  };

  const setActive = (index) => {
    active = index;
    options.forEach((option, position) => {
      const on = position === index;
      option.element.classList.toggle("is-active", on);
      option.element.setAttribute("aria-selected", on ? "true" : "false");
      if (on) option.element.scrollIntoView({ block: "nearest", behavior: "instant" });
    });
    if (index >= 0) ui.input.setAttribute("aria-activedescendant", options[index].element.id);
    else ui.input.removeAttribute("aria-activedescendant");
  };

  const render = () => {
    const raw = ui.input.value.trim();
    const query = normalize(raw);
    const current = openSelect.dataset.locationCurrent;
    ui.list.replaceChildren();
    options = [];
    let currentIndex = -1;
    groupsFor(openSelect).forEach((group, groupIndex) => {
      const items = group.items.filter((item) => !query || normalize(item.label).includes(query));
      if (!items.length) return;
      const box = el("div", "inventory-location-picker__group", { role: "group", "aria-labelledby": `inventory-location-group-${groupIndex}` });
      const heading = el("div", "transfer-out-suggest__group", { id: `inventory-location-group-${groupIndex}`, "aria-hidden": "true" });
      heading.textContent = group.label;
      box.append(heading);
      items.forEach((item) => {
        const isCurrent = item.value === current;
        const element = el("div", `transfer-out-suggest__option${isCurrent ? " is-current" : ""}`, {
          id: `inventory-location-option-${options.length}`, role: "option", "aria-selected": "false",
        });
        const label = document.createElement("span");
        highlight(label, item.label, raw);
        element.append(label);
        const notes = [isCurrent ? "目前位置" : "", item.stale ? "已停用" : ""].filter(Boolean);
        if (notes.length) {
          const small = document.createElement("small");
          small.textContent = notes.join("・");
          element.append(small);
        }
        if (isCurrent) currentIndex = options.length;
        options.push({ value: item.value, element });
        box.append(element);
      });
      ui.list.append(box);
    });
    if (!options.length) {
      const empty = el("p", "transfer-out-suggest__warning", { role: "status" });
      empty.textContent = `找不到「${raw}」，請改打其他字`;
      ui.list.append(empty);
    }
    // 沒打字時停在目前位置（直接按 Enter 不會改），打字後停在第一個符合的。
    setActive(query ? (options.length ? 0 : -1) : currentIndex);
  };

  const place = () => {
    if (!opener || ui.pop.hidden) return;
    const rect = opener.getBoundingClientRect();
    const width = ui.pop.offsetWidth;
    const height = ui.pop.offsetHeight;
    const gap = 6;
    const below = window.innerHeight - rect.bottom;
    const top = below < height + gap && rect.top > below ? rect.top - height - gap : rect.bottom + gap;
    const left = Math.max(8, Math.min(rect.left, document.documentElement.clientWidth - width - 8));
    ui.pop.style.top = `${top + window.scrollY}px`;
    ui.pop.style.left = `${left + window.scrollX}px`;
  };

  const open = (select, button) => {
    if (!ui) build();
    if (openSelect) close();
    populate(select);
    openSelect = select;
    opener = button;
    button.setAttribute("aria-expanded", "true");
    wrapFor(select).classList.add("is-open");
    ui.input.value = "";
    render();
    if (MOBILE.matches) {
      ui.hint.textContent = "點一下就存，存好可以按「復原」";
      ui.meta.textContent = `${wrapFor(select).dataset.identifier}・目前在 ${labelOf(select)}`;
      ui.slot.append(ui.picker);
      ui.dialog.showModal();
      // 不自動叫出鍵盤（會擋住清單）；要打字再點輸入框。
      ui.title.focus({ preventScroll: true });
    } else {
      ui.hint.textContent = "↑↓ 選、Enter 存、Esc 關閉不存";
      ui.pop.append(ui.picker);
      ui.pop.hidden = false;
      place();
      ui.input.focus({ preventScroll: true });
    }
  };

  const close = ({ restoreFocus = false } = {}) => {
    if (!openSelect) return;
    const button = opener;
    opener.setAttribute("aria-expanded", "false");
    wrapFor(openSelect).classList.remove("is-open");
    openSelect = null;
    opener = null;
    options = [];
    active = -1;
    ui.pop.hidden = true;
    if (ui.dialog.open) ui.dialog.close();
    if (restoreFocus) button.focus({ preventScroll: true });
  };

  const choose = (index) => {
    const option = options[index];
    if (!option || !openSelect) return;
    const select = openSelect;
    close({ restoreFocus: true });
    select.value = option.value;
    syncButton(select);
    save(select);
  };

  // Tab 離開：關閉不存，焦點照常移到按鈕的下一個（或上一個）可操作元素。
  const tabFrom = (button, backwards) => {
    const selector = "a[href], button:not([disabled]), input:not([disabled]):not([type='hidden']), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";
    const items = Array.from(document.querySelectorAll(selector))
      .filter((item) => !ui.pop.contains(item) && !ui.dialog.contains(item) && item.tabIndex >= 0 && item.getClientRects().length);
    const index = items.indexOf(button);
    const next = items[index + (backwards ? -1 : 1)];
    (next || button).focus();
  };

  function onKeydown(event) {
    if (event.isComposing || !openSelect) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!options.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive(active < 0 ? (step > 0 ? 0 : options.length - 1) : (active + step + options.length) % options.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (active >= 0) choose(active);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close({ restoreFocus: true });
    } else if (event.key === "Tab" && !ui.dialog.open) {
      event.preventDefault();
      const button = opener;
      close();
      tabFrom(button, event.shiftKey);
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-location-button]");
    if (!button) return;
    const select = button.parentElement.querySelector(".inventory-location__select");
    if (openSelect === select) close({ restoreFocus: true });
    else open(select, button);
  });

  // 點選擇器以外的地方：只關閉，不存。
  document.addEventListener("pointerdown", (event) => {
    if (!openSelect || ui.dialog.open) return;
    if (ui.pop.contains(event.target) || event.target.closest("[data-location-button]") === opener) return;
    close();
  }, true);

  window.addEventListener("resize", () => {
    if (!openSelect) return;
    // 跨過手機／桌機寬度就關閉（不存）；同一種版面只重新定位。
    if (MOBILE.matches !== ui.dialog.open) close();
    else place();
  });
})();
