/* 批次調整分期方案：標示變更、修改後自動勾選、快速套用到勾選列。
   送出後以伺服器預覽頁的內容為準；勾選與鍵盤移動由 vehicle-model-tools.js 處理。 */
(function () {
  "use strict";

  const number = new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 });

  function parseAmount(text) {
    const cleaned = String(text || "").replace(/[,，$元\s]/g, "");
    if (cleaned === "") return null;
    if (!/^\d+$/.test(cleaned)) return NaN;
    return Number(cleaned);
  }

  function parseRate(text) {
    const cleaned = String(text || "").replace(/[%％\s]/g, "");
    if (cleaned === "") return null;
    if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return NaN;
    const value = Number(cleaned);
    return value > 100 ? NaN : value;
  }

  function roundTo(value, step) {
    const scaled = value / step;
    return Math.sign(scaled) * Math.floor(Math.abs(scaled) + 0.5 + 1e-9) * step;
  }

  function setup(form) {
    const table = form.querySelector("[data-batch-table]");
    if (!table) return;
    const rows = () => Array.from(table.querySelectorAll("[data-inst-row]"));
    const changedCounter = form.querySelector("[data-changed-count]");
    const hint = form.querySelector("[data-inst-hint]");

    function check(row) {
      return row.querySelector("[data-row-check]");
    }

    function select(row) {
      const box = check(row);
      if (box && !box.disabled && !box.checked) {
        box.checked = true;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    function refreshField(field) {
      const input = field.querySelector("[data-inst-input]");
      const delta = field.querySelector("[data-inst-delta]");
      const kind = input.dataset.instInput;
      const currentText = field.dataset.current;
      field.classList.remove("is-changed", "is-invalid", "is-removed");
      if (delta) { delta.textContent = ""; delta.className = "model-delta"; }
      if (kind === "company") {
        const changed = input.value !== "" && input.value !== currentText;
        field.classList.toggle("is-changed", changed);
        return changed;
      }
      const value = kind === "rate" ? parseRate(input.value) : parseAmount(input.value);
      const current = currentText === "" ? null : Number(currentText);
      if (Number.isNaN(value) || (kind === "period" && value === 0)) {
        field.classList.add("is-invalid");
        if (delta) { delta.textContent = kind === "period" ? "請輸入大於 0 的整數" : "格式不正確"; delta.classList.add("is-error"); }
        return false;
      }
      if (kind !== "period") {
        // 開辦費、撥款比例：空白代表維持各期原值（或尚未設定）。
        const changed = value !== null && value !== current;
        field.classList.toggle("is-changed", changed);
        return changed;
      }
      if (value === null && current === null) return false;
      if (value === null) {
        field.classList.add("is-removed");
        if (delta) { delta.textContent = "將移除"; delta.classList.add("is-error"); }
        return true;
      }
      if (current === null) {
        field.classList.add("is-changed");
        if (delta) { delta.textContent = "新增"; delta.classList.add("is-new"); }
        return true;
      }
      if (value === current) return false;
      field.classList.add("is-changed");
      if (delta) {
        const diff = value - current;
        delta.textContent = `${diff > 0 ? "+" : ""}${number.format(diff)}`;
        delta.classList.add(diff > 0 ? "is-up" : "is-down");
      }
      return true;
    }

    function refreshAll() {
      let changedRows = 0;
      rows().forEach((row) => {
        let changed = false;
        row.querySelectorAll("[data-inst-field]").forEach((field) => { changed = refreshField(field) || changed; });
        row.classList.toggle("has-changes", changed);
        const box = check(row);
        if (changed && box && box.checked) changedRows += 1;
      });
      if (changedCounter) changedCounter.textContent = changedRows;
    }

    function format(input) {
      if (input.dataset.instInput === "rate" || input.tagName === "SELECT") return;
      const value = parseAmount(input.value);
      if (value !== null && !Number.isNaN(value)) input.value = number.format(value);
    }

    table.addEventListener("input", (event) => {
      const input = event.target.closest("[data-inst-input]");
      if (!input) return;
      select(input.closest("[data-inst-row]"));
      refreshAll();
    });
    table.addEventListener("change", (event) => {
      if (event.target.matches("select[data-inst-input]")) {
        select(event.target.closest("[data-inst-row]"));
        refreshAll();
      }
    });
    table.addEventListener("focusin", (event) => {
      const input = event.target.closest("input[data-inst-input]");
      if (!input) return;
      if (input.dataset.instInput !== "rate") {
        const value = parseAmount(input.value);
        if (value !== null && !Number.isNaN(value)) input.value = String(value);
      }
      requestAnimationFrame(() => input.select());
    });
    table.addEventListener("focusout", (event) => {
      const input = event.target.closest("input[data-inst-input]");
      if (input) format(input);
    });
    form.addEventListener("selection-change", refreshAll);

    // ---- 快速套用：沒有勾選時套用到全部可調整的列 ----
    function targets() {
      const usable = rows().filter((row) => { const box = check(row); return box && !box.disabled; });
      let chosen = usable.filter((row) => check(row).checked);
      if (!chosen.length) {
        chosen = usable;
        chosen.forEach((row) => select(row));
      }
      return chosen;
    }

    function say(text, isError) {
      if (!hint) return;
      hint.textContent = text;
      hint.classList.toggle("is-error", Boolean(isError));
    }

    const unit = form.querySelector("[data-inst-amount-unit]");
    const amountOp = form.querySelector("[data-inst-amount-op]");
    if (amountOp && unit) {
      amountOp.addEventListener("change", () => { unit.textContent = amountOp.value === "percent" ? "%" : "元"; });
    }

    const actions = {
      company() {
        const value = form.querySelector("[data-inst-company]").value;
        if (!value) return say("請先選擇分期公司。", true);
        const chosen = targets();
        chosen.forEach((row) => { row.querySelector("select[data-inst-input='company']").value = value; });
        return say(`已把 ${chosen.length} 列的分期公司設為「${form.querySelector("[data-inst-company]").selectedOptions[0].textContent}」。`);
      },
      fee() {
        const field = form.querySelector("[data-inst-fee]");
        const value = parseAmount(field.value);
        if (value === null || Number.isNaN(value)) { field.focus(); return say("請輸入開辦費（不收請填 0）。", true); }
        const chosen = targets();
        chosen.forEach((row) => { row.querySelector("[data-inst-input='fee']").value = number.format(value); });
        return say(`已把 ${chosen.length} 列的開辦費設為 $${number.format(value)}。`);
      },
      rate() {
        const field = form.querySelector("[data-inst-rate]");
        const value = parseRate(field.value);
        if (value === null || Number.isNaN(value)) { field.focus(); return say("請輸入 0–100 的撥款比例。", true); }
        const chosen = targets();
        chosen.forEach((row) => { row.querySelector("[data-inst-input='rate']").value = String(value); });
        return say(`已把 ${chosen.length} 列的撥款比例設為 ${value}%。`);
      },
      max() {
        const max = Number(form.querySelector("[data-inst-max]").value);
        const chosen = targets();
        let cleared = 0;
        chosen.forEach((row) => {
          row.querySelectorAll("[data-periods]").forEach((field) => {
            const input = field.querySelector("[data-inst-input]");
            if (Number(field.dataset.periods) > max && input.value.trim() !== "") { input.value = ""; cleared += 1; }
          });
        });
        return say(`已清空 ${chosen.length} 列超過 ${max} 期的 ${cleared} 格。`);
      },
      amount() {
        const periods = form.querySelector("[data-inst-amount-period]").value;
        const operation = amountOp.value;
        const step = Number(form.querySelector("[data-inst-amount-round]").value) || 1;
        const raw = form.querySelector("[data-inst-amount-value]").value.replace(/[,，$元%\s]/g, "");
        if (!/^-?\d+(\.\d+)?$/.test(raw)) {
          form.querySelector("[data-inst-amount-value]").focus();
          return say("請先輸入調整數值。", true);
        }
        const amount = Number(raw);
        if (operation === "set" && (amount <= 0 || !Number.isInteger(amount))) return say("統一設為的金額需為大於 0 的整數。", true);
        if (operation === "set" && !periods) return say("統一設為請先選擇期數。", true);
        const chosen = targets();
        let applied = 0;
        let skipped = 0;
        chosen.forEach((row) => {
          row.querySelectorAll("[data-periods]").forEach((field) => {
            if (periods && field.dataset.periods !== periods) return;
            const input = field.querySelector("[data-inst-input]");
            const current = parseAmount(input.value);
            if (operation !== "set" && (current === null || Number.isNaN(current))) return;
            let result = operation === "set" ? amount
              : operation === "add" ? current + amount : current * (100 + amount) / 100;
            result = roundTo(result, step);
            if (result <= 0) { skipped += 1; return; }
            input.value = number.format(result);
            applied += 1;
          });
        });
        return say(`已調整 ${applied} 格` + (skipped ? `；${skipped} 格結果小於等於 0，未套用` : "") + "。", applied === 0);
      },
    };

    form.querySelectorAll("[data-inst-apply]").forEach((button) => {
      button.addEventListener("click", () => {
        actions[button.dataset.instApply]();
        refreshAll();
      });
    });

    const reset = form.querySelector("[data-inst-reset]");
    if (reset) {
      reset.addEventListener("click", () => {
        rows().forEach((row) => {
          row.querySelectorAll("[data-inst-field]").forEach((field) => {
            const input = field.querySelector("[data-inst-input]");
            if (input.disabled) return;
            const current = field.dataset.current;
            if (input.tagName === "SELECT") input.value = current;
            else if (input.dataset.instInput === "rate") input.value = current;
            else input.value = current === "" ? "" : number.format(Number(current));
          });
          const box = check(row);
          if (box && !box.disabled) box.checked = false;
        });
        // 透過任一列的 change 事件讓勾選計數與全選框同步。
        const anyBox = table.querySelector("[data-row-check]:not(:disabled)");
        if (anyBox) anyBox.dispatchEvent(new Event("change", { bubbles: true }));
        refreshAll();
        say("已還原為目前方案。");
      });
    }

    refreshAll();
  }

  document.querySelectorAll("[data-installment-batch]").forEach(setup);
})();
