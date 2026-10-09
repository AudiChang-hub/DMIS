/* 批次調整分期方案：每期金額與各期條件（分期公司、撥款比例、開辦費）的變更標示、自動勾選與快速套用。
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

  function sameAmount(a, b) {
    return parseAmount(a) === parseAmount(b);
  }

  function setup(form) {
    const table = form.querySelector("[data-batch-table]");
    if (!table) return;
    const rows = () => Array.from(table.querySelectorAll("[data-inst-row]"));
    const changedCounter = form.querySelector("[data-changed-count]");
    const hint = form.querySelector("[data-inst-hint]");

    const check = (row) => row.querySelector("[data-row-check]");
    const amountInput = (field) => field.querySelector("[data-inst-input]");
    const cond = (field, key) => field.querySelector(`[data-inst-cond="${key}"]`);

    function select(row) {
      const box = check(row);
      if (box && !box.disabled && !box.checked) {
        box.checked = true;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    function condText(field) {
      const company = cond(field, "company");
      const rate = cond(field, "rate");
      const fee = parseAmount(cond(field, "fee").value);
      const name = company.value ? company.selectedOptions[0].textContent : "";
      const rateText = rate.value.trim() ? `${rate.value.trim().replace(/%$/, "")}%` : (rate.placeholder.startsWith("例如") ? "" : rate.placeholder);
      const feeText = fee ? `開辦 $${number.format(fee)}` : "免開辦";
      return { name, rateText, feeText };
    }

    function refreshField(field) {
      const input = amountInput(field);
      const delta = field.querySelector("[data-inst-delta]");
      const summary = field.querySelector("[data-inst-cond-text]");
      const details = field.querySelector(".model-installment-cond");
      field.classList.remove("is-changed", "is-invalid", "is-removed", "has-cond-change", "needs-terms");
      if (delta) { delta.textContent = ""; delta.className = "model-delta"; }

      const value = parseAmount(input.value);
      const current = field.dataset.current === "" ? null : Number(field.dataset.current);
      const company = cond(field, "company").value;
      const rate = parseRate(cond(field, "rate").value);
      const condChanged = company !== field.dataset.currentCompany
        || cond(field, "rate").value.trim().replace(/%$/, "") !== field.dataset.currentRate
        || !sameAmount(cond(field, "fee").value || "0", field.dataset.currentFee || "0");
      const offered = value !== null && !Number.isNaN(value) && value > 0;

      // 條件摘要：有提供的期數才顯示；缺公司或比例時提醒。
      const text = condText(field);
      const missing = offered && (!company || (rate === null && !cond(field, "rate").placeholder.match(/固定|另填/)));
      details.hidden = !offered && !condChanged;
      summary.textContent = missing ? "請設定條件" : [text.name, text.rateText].filter(Boolean).join(" ") + `・${text.feeText}`;
      field.classList.toggle("needs-terms", missing);
      if (Number.isNaN(rate) || Number.isNaN(parseAmount(cond(field, "fee").value))) field.classList.add("needs-terms");

      if (Number.isNaN(value) || value === 0) {
        field.classList.add("is-invalid");
        if (delta) { delta.textContent = "請輸入大於 0 的整數"; delta.classList.add("is-error"); }
        return false;
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
      let changed = false;
      if (value !== current) {
        changed = true;
        field.classList.add("is-changed");
        const diff = value - current;
        if (delta) {
          delta.textContent = `${diff > 0 ? "+" : ""}${number.format(diff)}`;
          delta.classList.add(diff > 0 ? "is-up" : "is-down");
        }
      }
      if (condChanged) {
        changed = true;
        field.classList.add("has-cond-change");
        if (delta && !delta.textContent) { delta.textContent = "條件變更"; delta.classList.add("is-new"); }
      }
      return changed;
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

    function onEdit(event) {
      const target = event.target.closest("[data-inst-input], [data-inst-cond]");
      if (!target) return;
      select(target.closest("[data-inst-row]"));
      refreshField(target.closest("[data-inst-field]"));
      refreshAll();
    }
    table.addEventListener("input", onEdit);
    table.addEventListener("change", (event) => { if (event.target.matches("select[data-inst-cond]")) onEdit(event); });
    table.addEventListener("focusin", (event) => {
      const input = event.target.closest("input[data-inst-input='period'], input[data-inst-cond='fee']");
      if (!input) return;
      const value = parseAmount(input.value);
      if (value !== null && !Number.isNaN(value)) input.value = String(value);
      requestAnimationFrame(() => input.select());
    });
    table.addEventListener("focusout", (event) => {
      const input = event.target.closest("input[data-inst-input='period'], input[data-inst-cond='fee']");
      if (!input) return;
      const value = parseAmount(input.value);
      if (value !== null && !Number.isNaN(value)) input.value = number.format(value);
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
      terms() {
        const terms = {};
        let invalid = "";
        form.querySelectorAll("[data-term-company]").forEach((select) => {
          const periods = select.dataset.termCompany;
          const rate = form.querySelector(`[data-term-rate="${periods}"]`).value.trim();
          const fee = form.querySelector(`[data-term-fee="${periods}"]`).value.trim();
          if (rate && Number.isNaN(parseRate(rate))) invalid = `${periods} 期撥款比例需為 0–100`;
          if (fee && Number.isNaN(parseAmount(fee))) invalid = `${periods} 期開辦費需為整數`;
          if (select.value || rate || fee) terms[periods] = { company: select.value, rate, fee };
        });
        if (invalid) return say(invalid + "。", true);
        if (!Object.keys(terms).length) return say("請先在期數條件填寫要套用的分期公司、撥款比例或開辦費。", true);
        const chosen = targets();
        chosen.forEach((row) => {
          row.querySelectorAll("[data-inst-field]").forEach((field) => {
            const term = terms[field.dataset.periods];
            if (!term) return;
            if (term.company) cond(field, "company").value = term.company;
            if (term.rate) cond(field, "rate").value = String(parseRate(term.rate));
            if (term.fee) cond(field, "fee").value = number.format(parseAmount(term.fee));
          });
        });
        return say(`已把 ${Object.keys(terms).length} 個期數的條件套用到 ${chosen.length} 列。`);
      },
      max() {
        const max = Number(form.querySelector("[data-inst-max]").value);
        const chosen = targets();
        let cleared = 0;
        chosen.forEach((row) => {
          row.querySelectorAll("[data-inst-field]").forEach((field) => {
            const input = amountInput(field);
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
          row.querySelectorAll("[data-inst-field]").forEach((field) => {
            if (periods && field.dataset.periods !== periods) return;
            const input = amountInput(field);
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
            const input = amountInput(field);
            if (input.disabled) return;
            input.value = field.dataset.current === "" ? "" : number.format(Number(field.dataset.current));
            cond(field, "company").value = field.dataset.currentCompany;
            cond(field, "rate").value = field.dataset.currentRate;
            cond(field, "fee").value = field.dataset.currentFee;
            field.querySelector(".model-installment-cond").open = false;
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

    // 送出時只把勾選列打包成一個 JSON 欄位：32 列以上的個別欄位會超過伺服器的欄位數上限。
    const grid = form.querySelector("[data-inst-grid]");
    form.addEventListener("submit", () => {
      if (!grid) return;
      const values = {};
      rows().forEach((row) => {
        const box = check(row);
        if (!box || box.disabled || !box.checked) return;
        values[box.name] = "1";
        row.querySelectorAll("[data-inst-field] [name]").forEach((element) => { values[element.name] = element.value; });
      });
      grid.value = JSON.stringify(values);
      table.querySelectorAll("tbody [name]:not(:disabled)").forEach((element) => {
        element.dataset.instPacked = "1";
        element.disabled = true;
      });
    });
    // 從預覽頁按瀏覽器「上一頁」回來時（頁面快取），恢復可編輯。
    window.addEventListener("pageshow", () => {
      table.querySelectorAll("[data-inst-packed]").forEach((element) => {
        element.disabled = false;
        delete element.dataset.instPacked;
      });
    });

    refreshAll();
  }

  document.querySelectorAll("[data-installment-batch]").forEach(setup);
})();
