(() => {
  "use strict";

  // T-310：庫存列表「調出」（車離開本店庫存）。勾車 → 調給哪一家 → 確認，三步完成，不簽名。
  // 店名自由輸入；打字即時出建議：原廠／總公司、打過的店名（最近用過的在前）、車行主檔，
  // 最後一列「直接用『○○』當店名」。上下鍵選、Enter 帶入、Esc 收起建議（再按一次關閉小視窗）。
  // 放到本店其他門市不是調出（要改實際位置），打本店名稱會先擋下；伺服器也會再檢查一次。

  const toast = document.querySelector("[data-transfer-out-toast]");
  if (toast) {
    const close = () => toast.remove();
    toast.querySelector("[data-transfer-out-toast-close]")?.addEventListener("click", close);
    // 12 秒後自動收起；滑鼠停在上面或焦點在裡面時先不收。
    const later = () => window.setTimeout(() => {
      if (toast.matches(":hover") || toast.contains(document.activeElement)) later();
      else close();
    }, 12000);
    later();
  }

  const table = document.querySelector("[data-transfer-out-table]");
  const dialog = document.querySelector("[data-transfer-out-dialog]");
  const dataNode = document.getElementById("transfer-out-names");
  if (!table || !dialog || !dataNode || typeof dialog.showModal !== "function") return;

  const names = JSON.parse(dataNode.textContent || "{}");
  const used = names.used || [];
  const dealers = names.dealers || [];
  const homes = names.home || [];
  const factory = names.factory || "";
  const RECENT = 5;
  const MAX_DEALERS = 8;

  const bar = document.querySelector("[data-transfer-out-bar]");
  const panel = table.closest(".inventory-list-panel");
  // 全選框有兩個：桌面在表頭，手機卡片沒有表頭，改用列表上方那一列；兩個同步。
  const alls = Array.from((panel || table).querySelectorAll("[data-transfer-out-all]"));
  const form = dialog.querySelector("[data-transfer-out-form]");
  const inputs = dialog.querySelector("[data-transfer-out-inputs]");
  const title = dialog.querySelector("[data-transfer-out-title]");
  const carList = dialog.querySelector("[data-transfer-out-cars]");
  const nameInput = dialog.querySelector("[data-transfer-out-name]");
  const noteInput = form.elements.note;
  const list = dialog.querySelector("[data-transfer-out-suggest]");
  const error = dialog.querySelector("[data-transfer-out-error]");
  const submit = dialog.querySelector("[data-transfer-out-submit]");

  const checks = () => Array.from(table.querySelectorAll("[data-transfer-out-check]"));
  const selected = () => checks().filter((check) => check.checked);
  const normalize = (value) => String(value || "").toLowerCase().replace(/\s+/g, "");
  const tidy = (value) => String(value || "").trim().replace(/\s+/g, " ");

  // 本店：打「馭盛」「本店」「本店：永湛」都算（和伺服器 is_home_store 一致）。
  const isHomeStore = (value) => {
    let compact = String(value || "").replace(/\s+/g, "");
    if (compact.startsWith("本店")) {
      compact = compact.slice(2).replace(/^[：:]+/, "");
      if (!compact) return true;
    }
    return homes.includes(compact);
  };

  // ---------- 勾選與底部選取列 ----------
  const nudgeDock = () => window.dispatchEvent(new Event("resize"));

  const refresh = () => {
    const picked = selected();
    const enabled = checks();
    checks().forEach((check) => check.closest("tr")?.classList.toggle("is-transfer-selected", check.checked));
    alls.forEach((all) => {
      all.checked = enabled.length > 0 && picked.length === enabled.length;
      all.indeterminate = picked.length > 0 && picked.length < enabled.length;
      all.disabled = enabled.length === 0;
    });
    if (bar) {
      bar.querySelectorAll("[data-transfer-out-count]").forEach((node) => { node.textContent = String(picked.length); });
      const wasHidden = bar.hidden;
      bar.hidden = picked.length === 0;
      panel?.classList.toggle("has-transfer-out-bar", !bar.hidden);
      if (!bar.hidden && toast) toast.remove();
      if (wasHidden !== bar.hidden) nudgeDock();
    }
  };

  (panel || table).addEventListener("change", (event) => {
    if (alls.includes(event.target)) {
      checks().forEach((check) => { check.checked = event.target.checked; });
    }
    refresh();
  });
  bar?.querySelector("[data-transfer-out-clear]")?.addEventListener("click", () => {
    checks().forEach((check) => { check.checked = false; });
    refresh();
    alls.find((all) => all.getClientRects().length > 0)?.focus();
  });

  // ---------- 小視窗 ----------
  const carOf = (check) => ({
    id: check.value,
    model: check.dataset.model || "",
    color: check.dataset.color || "",
    identifier: check.dataset.identifier || "",
  });

  const showError = (message) => {
    error.textContent = message;
    error.hidden = !message;
  };

  const open = (cars) => {
    if (!cars.length) return;
    inputs.replaceChildren(...cars.map((car) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "vehicles";
      input.value = car.id;
      return input;
    }));
    carList.replaceChildren(...cars.map((car) => {
      const item = document.createElement("li");
      const label = document.createElement("span");
      const model = document.createElement("strong");
      model.textContent = car.model;
      label.append(model, ` ${car.color}`);
      const id = document.createElement("small");
      id.textContent = car.identifier;
      item.append(label, id);
      return item;
    }));
    title.textContent = `調出 ${cars.length} 台車`;
    nameInput.value = "";
    noteInput.value = "";
    nameInput.removeAttribute("aria-invalid");
    showError("");
    setBusy(false);
    dialog.showModal();
    nameInput.focus();
    render();
  };

  table.addEventListener("click", (event) => {
    const button = event.target.closest("[data-transfer-out-one]");
    if (!button) return;
    const check = checks().find((item) => item.value === button.dataset.transferOutOne);
    if (check) open([carOf(check)]);
  });
  bar?.querySelector("[data-transfer-out-selected]")?.addEventListener("click", () => open(selected().map(carOf)));
  dialog.querySelector("[data-transfer-out-cancel]").addEventListener("click", () => dialog.close());
  // 點小視窗外面（遮罩）也關閉。
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const box = form.getBoundingClientRect();
    const inside = event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom;
    if (!inside) dialog.close();
  });

  // ---------- 店名建議 ----------
  let options = [];
  let active = -1;

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

  const setExpanded = (expanded) => {
    list.hidden = !expanded;
    nameInput.setAttribute("aria-expanded", expanded ? "true" : "false");
    if (!expanded) {
      active = -1;
      nameInput.removeAttribute("aria-activedescendant");
    }
  };

  const setActive = (index) => {
    active = index;
    options.forEach((option, position) => {
      const on = position === index;
      option.element.classList.toggle("is-active", on);
      option.element.setAttribute("aria-selected", on ? "true" : "false");
      if (on) option.element.scrollIntoView({ block: "nearest" });
    });
    if (index >= 0) nameInput.setAttribute("aria-activedescendant", options[index].element.id);
    else nameInput.removeAttribute("aria-activedescendant");
  };

  const render = () => {
    const raw = tidy(nameInput.value);
    const query = normalize(raw);
    const match = (name) => !query || normalize(name).includes(query);
    const groups = [];
    if (factory && (!query || match(factory) || "原廠".includes(query) || "總公司".includes(query))) {
      groups.push({ label: "", items: [{ value: factory, meta: "" }] });
    }
    const usedItems = used.filter((item) => match(item.name)).slice(0, query ? used.length : RECENT)
      .map((item) => ({ value: item.name, meta: item.meta }));
    if (usedItems.length) groups.push({ label: query ? "打過的店名" : "最近用過", items: usedItems });
    const dealerItems = query ? dealers.filter(match).slice(0, MAX_DEALERS).map((name) => ({ value: name, meta: "車行" })) : [];
    if (dealerItems.length) groups.push({ label: "車行主檔", items: dealerItems });
    const exact = groups.some((group) => group.items.some((item) => normalize(item.value) === query));
    const home = raw && isHomeStore(raw);

    list.replaceChildren();
    options = [];
    groups.forEach((group, groupIndex) => {
      if (group.label) {
        const heading = document.createElement("li");
        heading.className = "transfer-out-suggest__group";
        heading.setAttribute("role", "presentation");
        heading.id = `transfer-out-group-${groupIndex}`;
        heading.textContent = group.label;
        list.append(heading);
      }
      group.items.forEach((item) => {
        const element = document.createElement("li");
        element.className = "transfer-out-suggest__option";
        element.id = `transfer-out-option-${options.length}`;
        element.setAttribute("role", "option");
        element.setAttribute("aria-selected", "false");
        const label = document.createElement("span");
        highlight(label, item.value, raw);
        element.append(label);
        if (item.meta) {
          const meta = document.createElement("small");
          meta.textContent = item.meta;
          element.append(meta);
        }
        options.push({ value: item.value, element });
        list.append(element);
      });
    });
    if (home) {
      const warning = document.createElement("li");
      warning.className = "transfer-out-suggest__warning";
      warning.setAttribute("role", "presentation");
      warning.textContent = `「${raw}」是本店：放到本店其他門市請改列表上的「實際位置」，不用調出。`;
      list.append(warning);
    } else if (raw && !exact) {
      const element = document.createElement("li");
      element.className = "transfer-out-suggest__option transfer-out-suggest__option--typed";
      element.id = `transfer-out-option-${options.length}`;
      element.setAttribute("role", "option");
      element.setAttribute("aria-selected", "false");
      const label = document.createElement("span");
      label.textContent = `直接用「${raw}」當店名`;
      const key = document.createElement("small");
      key.textContent = "Enter";
      element.append(label, key);
      options.push({ value: raw, element });
      list.append(element);
    }
    setExpanded(list.children.length > 0);
    setActive(-1);
  };

  const choose = (index) => {
    const option = options[index];
    if (!option) return;
    nameInput.value = option.value;
    nameInput.removeAttribute("aria-invalid");
    showError("");
    setExpanded(false);
    nameInput.focus();
  };

  nameInput.addEventListener("input", () => {
    nameInput.removeAttribute("aria-invalid");
    showError("");
    render();
  });
  nameInput.addEventListener("focus", () => { if (list.hidden) render(); });
  nameInput.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (list.hidden) render();
      if (!options.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive(active < 0 ? (step > 0 ? 0 : options.length - 1) : (active + step + options.length) % options.length);
    } else if (event.key === "Enter" && !list.hidden) {
      // 建議清單打開時，Enter 只帶入店名、不送出；再按一次 Enter（或按「確認調出」）才送出。
      event.preventDefault();
      if (active >= 0) choose(active);
      else {
        nameInput.value = tidy(nameInput.value);
        setExpanded(false);
      }
    } else if (event.key === "Escape" && !list.hidden) {
      event.preventDefault();
      event.stopPropagation();
      setExpanded(false);
    }
  });
  // 先選再失焦：用 mousedown 擋住失焦，點選建議不會先把清單收掉。
  list.addEventListener("mousedown", (event) => event.preventDefault());
  list.addEventListener("click", (event) => {
    const element = event.target.closest(".transfer-out-suggest__option");
    if (!element) return;
    choose(options.findIndex((option) => option.element === element));
  });
  nameInput.addEventListener("blur", () => setExpanded(false));
  // 原生 <dialog> 按 Esc 會直接關閉；建議清單打開時先只收起清單。
  dialog.addEventListener("cancel", (event) => {
    if (!list.hidden) {
      event.preventDefault();
      setExpanded(false);
    }
  });

  // ---------- 送出 ----------
  const setBusy = (busy) => {
    submit.disabled = busy;
    submit.classList.toggle("is-submitting", busy);
    submit.textContent = busy ? "調出中…" : "確認調出";
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submit.disabled) return;
    const name = tidy(nameInput.value);
    nameInput.value = name;
    if (!name) {
      nameInput.setAttribute("aria-invalid", "true");
      showError("請填寫要調給哪一家。");
      nameInput.focus();
      return;
    }
    if (isHomeStore(name)) {
      nameInput.setAttribute("aria-invalid", "true");
      showError(`「${name}」是本店，不能調出。放到本店其他門市請直接改列表上的「實際位置」，車仍是本店庫存。`);
      nameInput.focus();
      return;
    }
    setExpanded(false);
    showError("");
    setBusy(true);
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok && payload.ok) {
        window.location.assign(payload.redirect || window.location.href);
        return;
      }
      showError(payload.message || "未調出：伺服器沒有回應，請重新整理後再試。");
    } catch (_error) {
      showError("未調出：網路連線中斷，請確認連線後再按一次。");
    }
    setBusy(false);
  });

  refresh();
})();
