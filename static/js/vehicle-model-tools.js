/* 機種沿用與批次調整：勾選、試算、鍵盤移動與千分位顯示。
   算法與伺服器 sales/services/vehicle_model_batch.py 的 apply_adjustment 相同；送出後以預覽頁的數字為準。 */
(function () {
  "use strict";

  const number = new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 });

  function parseAmount(text) {
    const cleaned = String(text || "").replace(/[,，$元\s]/g, "");
    if (cleaned === "") return null;
    if (!/^-?\d+(\.\d+)?$/.test(cleaned)) return NaN;
    return Number(cleaned);
  }

  function roundTo(value, step) {
    // 與伺服器相同：除以進位單位後四捨五入（.5 一律進位），再乘回。
    const scaled = value / step;
    const rounded = Math.sign(scaled) * Math.floor(Math.abs(scaled) + 0.5 + 1e-9);
    return rounded * step;
  }

  function adjust(current, operation, amount, step) {
    let result;
    if (operation === "set") result = amount;
    else if (current === null) return null;
    else if (operation === "add") result = current + amount;
    else if (operation === "percent") result = current * (100 + amount) / 100;
    else return null;
    return roundTo(result, step || 1);
  }

  /* ---- 勾選與計數 ---- */
  function setupSelection(root) {
    const table = root.querySelector("[data-batch-table], [data-copy-table]");
    if (!table) return null;
    const master = table.querySelector("[data-select-all]");
    const checks = () => Array.from(table.querySelectorAll("[data-row-check]:not(:disabled)"));
    const counters = root.querySelectorAll("[data-selected-count]");

    function sync() {
      const all = checks();
      const selected = all.filter((box) => box.checked);
      table.querySelectorAll("[data-batch-row]").forEach((row) => {
        const box = row.querySelector("[data-row-check]");
        row.classList.toggle("is-selected", Boolean(box && box.checked));
      });
      if (master) {
        master.checked = all.length > 0 && selected.length === all.length;
        master.indeterminate = selected.length > 0 && selected.length < all.length;
        master.disabled = all.length === 0;
      }
      counters.forEach((node) => { node.textContent = selected.length; });
      root.dispatchEvent(new CustomEvent("selection-change"));
    }

    if (master) {
      master.addEventListener("change", () => {
        checks().forEach((box) => { box.checked = master.checked; });
        sync();
      });
    }
    table.addEventListener("change", (event) => {
      if (event.target.matches("[data-row-check]")) sync();
    });
    // 點列上的空白處也能切換勾選（不含連結與輸入框）。
    table.addEventListener("click", (event) => {
      if (event.target.closest("a, input, label, button, select")) return;
      const row = event.target.closest("[data-batch-row]");
      const box = row && row.querySelector("[data-row-check]");
      if (box && !box.disabled) {
        box.checked = !box.checked;
        sync();
      }
    });
    sync();
    return { table, checks, sync };
  }

  /* ---- 鍵盤：Enter／↓ 下一列同欄、↑ 上一列；Tab 在列尾跳到下一列第一格 ---- */
  function setupKeyboard(table) {
    const grid = () => Array.from(table.querySelectorAll("[data-batch-row]")).map((row) =>
      Array.from(row.querySelectorAll("[data-batch-input]")).filter((input) => !input.disabled)
    ).filter((cells) => cells.length);

    function focusCell(input) {
      if (!input) return false;
      input.focus();
      if (typeof input.select === "function") input.select();
      return true;
    }

    table.addEventListener("keydown", (event) => {
      const input = event.target.closest("[data-batch-input]");
      if (!input || event.isComposing) return;
      const rows = grid();
      const rowIndex = rows.findIndex((cells) => cells.includes(input));
      if (rowIndex < 0) return;
      const colIndex = rows[rowIndex].indexOf(input);
      let target = null;
      if (event.key === "Enter" || event.key === "ArrowDown") {
        target = rows[rowIndex + (event.shiftKey && event.key === "Enter" ? -1 : 1)];
        target = target && (target[colIndex] || target[target.length - 1]);
        event.preventDefault();
      } else if (event.key === "ArrowUp") {
        target = rows[rowIndex - 1];
        target = target && (target[colIndex] || target[target.length - 1]);
        event.preventDefault();
      } else if (event.key === "Tab" && !event.shiftKey && colIndex === rows[rowIndex].length - 1 && rows[rowIndex + 1]) {
        target = rows[rowIndex + 1][0];
        event.preventDefault();
      } else if (event.key === "Tab" && event.shiftKey && colIndex === 0 && rows[rowIndex - 1]) {
        const previous = rows[rowIndex - 1];
        target = previous[previous.length - 1];
        event.preventDefault();
      }
      if (target) focusCell(target);
    });
  }

  /* ---- 批次調整 ---- */
  function setupBatch(form) {
    const selection = setupSelection(form);
    if (!selection) return;
    const { table, checks, sync } = selection;
    setupKeyboard(table);
    const changedCounter = form.querySelector("[data-changed-count]");

    function refreshCell(cell) {
      const input = cell.querySelector("[data-batch-input]");
      const delta = cell.querySelector("[data-batch-delta]");
      const current = cell.dataset.current === "" ? null : Number(cell.dataset.current);
      const value = parseAmount(input.value);
      cell.classList.remove("is-changed", "is-invalid");
      if (delta) { delta.textContent = ""; delta.className = "model-delta"; }
      if (value === null) return false;
      if (Number.isNaN(value) || value < 0 || !Number.isInteger(value)) {
        cell.classList.add("is-invalid");
        if (delta) { delta.textContent = "請輸入不小於 0 的整數"; delta.classList.add("is-error"); }
        return false;
      }
      if (current !== null && value === current) {
        if (delta) { delta.textContent = "與目前相同"; }
        return false;
      }
      cell.classList.add("is-changed");
      if (delta) {
        if (current === null) {
          delta.textContent = "新設定";
          delta.classList.add("is-new");
        } else {
          const diff = value - current;
          const percent = current ? ` (${diff > 0 ? "+" : ""}${(diff / current * 100).toFixed(1)}%)` : "";
          delta.textContent = `${diff > 0 ? "+" : ""}${number.format(diff)}${percent}`;
          delta.classList.add(diff > 0 ? "is-up" : "is-down");
        }
      }
      return true;
    }

    function refreshAll() {
      let changedRows = 0;
      table.querySelectorAll("[data-batch-row]").forEach((row) => {
        const box = row.querySelector("[data-row-check]");
        let changed = false;
        row.querySelectorAll("[data-batch-cell]").forEach((cell) => { changed = refreshCell(cell) || changed; });
        row.classList.toggle("has-changes", changed);
        if (changed && box && box.checked) changedRows += 1;
      });
      if (changedCounter) changedCounter.textContent = changedRows;
    }

    table.addEventListener("input", (event) => {
      const input = event.target.closest("[data-batch-input]");
      if (!input) return;
      const row = input.closest("[data-batch-row]");
      const box = row.querySelector("[data-row-check]");
      if (box && !box.disabled && input.value.trim() !== "" && !box.checked) {
        box.checked = true;
        sync();
      }
      refreshAll();
    });
    table.addEventListener("focusin", (event) => {
      const input = event.target.closest("[data-batch-input]");
      if (!input) return;
      const value = parseAmount(input.value);
      if (value !== null && !Number.isNaN(value)) input.value = String(value);
      requestAnimationFrame(() => input.select());
    });
    table.addEventListener("focusout", (event) => {
      const input = event.target.closest("[data-batch-input]");
      if (!input) return;
      const value = parseAmount(input.value);
      if (value !== null && !Number.isNaN(value) && Number.isInteger(value) && value >= 0) input.value = number.format(value);
    });
    form.addEventListener("selection-change", refreshAll);

    // 快速套用：與伺服器相同算法，直接寫入輸入框；沒有勾選時套用到全部可調整的列。
    const applyButton = form.querySelector("[data-batch-apply]");
    const hint = form.querySelector("[data-batch-op-hint]");
    const opSelect = form.querySelector("[data-batch-op]");
    const unit = form.querySelector("[data-batch-op-unit]");
    function syncUnit() {
      if (unit && opSelect) unit.textContent = opSelect.value === "percent" ? "%" : "元";
    }
    if (opSelect) { opSelect.addEventListener("change", syncUnit); syncUnit(); }
    if (applyButton) {
      applyButton.addEventListener("click", (event) => {
        event.preventDefault();
        const operation = opSelect.value;
        const field = form.querySelector("[data-batch-op-field]").value;
        const step = Number(form.querySelector("[data-batch-op-round]").value) || 1;
        const amount = parseAmount(form.querySelector("[data-batch-op-value]").value);
        if (amount === null || Number.isNaN(amount)) {
          hint.textContent = "請先輸入調整數值。";
          hint.classList.add("is-error");
          form.querySelector("[data-batch-op-value]").focus();
          return;
        }
        let targets = checks().filter((box) => box.checked);
        if (!targets.length) {
          targets = checks();
          targets.forEach((box) => { box.checked = true; });
          sync();
        }
        let applied = 0;
        let skipped = 0;
        targets.forEach((box) => {
          const row = box.closest("[data-batch-row]");
          const cell = row.querySelector(`[data-batch-cell][data-field="${field}"]`);
          if (!cell) return;
          const current = cell.dataset.current === "" ? null : Number(cell.dataset.current);
          const result = adjust(current, operation, amount, step);
          if (result === null || result < 0) { skipped += 1; return; }
          cell.querySelector("[data-batch-input]").value = number.format(result);
          applied += 1;
        });
        refreshAll();
        hint.classList.toggle("is-error", applied === 0);
        hint.textContent = `已套用到 ${applied} 列` + (skipped ? `；${skipped} 列沒有目前金額或結果小於 0，未套用` : "") + "。";
      });
    }

    const clear = form.querySelector("[data-batch-clear]");
    if (clear) {
      clear.addEventListener("click", () => {
        table.querySelectorAll("[data-batch-input]").forEach((input) => { input.value = ""; });
        checks().forEach((box) => { box.checked = false; });
        sync();
        refreshAll();
        if (hint) { hint.textContent = "已清除所有輸入。"; hint.classList.remove("is-error"); }
      });
    }

    // 初次載入（含返回修改）時把數字補上千分位並計算差額。
    table.querySelectorAll("[data-batch-input]").forEach((input) => {
      const value = parseAmount(input.value);
      if (value !== null && !Number.isNaN(value) && Number.isInteger(value) && value >= 0) input.value = number.format(value);
    });
    refreshAll();
  }

  /* ---- 沿用建立 ---- */
  function setupCopy(form) {
    const selection = setupSelection(form);
    if (!selection) return;
    setupKeyboard(selection.table);
    selection.table.addEventListener("input", (event) => {
      const input = event.target.closest("[data-batch-input]");
      const box = input && input.closest("[data-batch-row]").querySelector("[data-row-check]");
      if (box && !box.checked) { box.checked = true; selection.sync(); }
    });
  }

  /* ---- 篩選：選了品牌就只列出該品牌的機種 ---- */
  function setupFilters(filters) {
    const brand = filters.querySelector("[data-tool-brand]");
    const family = filters.querySelector("[data-tool-family]");
    if (!brand || !family) return;
    function apply() {
      const key = brand.value.toLowerCase();
      Array.from(family.options).forEach((option) => {
        if (!option.value) return;
        const visible = !key || option.dataset.brand === key;
        option.hidden = !visible;
        option.disabled = !visible;
      });
      const chosen = family.selectedOptions[0];
      if (chosen && chosen.disabled) family.value = "";
    }
    brand.addEventListener("change", apply);
    apply();
  }

  document.querySelectorAll("[data-batch-editor]").forEach(setupBatch);
  document.querySelectorAll("[data-copy-form]").forEach(setupCopy);
  // 批次套用附加獎勵：只共用勾選與計數，方案編輯由 vehicle-model-reward-batch.js 處理。
  document.querySelectorAll("[data-reward-batch]").forEach((form) => setupSelection(form));
  document.querySelectorAll("[data-model-tool-filters]").forEach(setupFilters);
})();
