/* 批次套用附加獎勵：品項列增減、每台預估成本，以及各年式「套用後」的即時判斷。
   判斷規則與 sales/services/vehicle_model_reward_batch.py 的 decide() 相同；送出後以預覽頁為準。 */
(function () {
  "use strict";

  const form = document.querySelector("[data-reward-batch]");
  if (!form) return;
  const list = form.querySelector("[data-reward-items]");
  const template = document.querySelector("[data-reward-item-template]");
  const startInput = form.querySelector("[data-reward-start]");
  const endInput = form.querySelector("[data-reward-end]");
  const closeInput = form.querySelector("[data-reward-close]");
  const totalNode = form.querySelector("[data-reward-total]");
  const totalNote = form.querySelector("[data-reward-total-note]");
  const summary = form.querySelector("[data-reward-summary]");
  const dayLabel = form.querySelector("[data-reward-day-label]");
  const number = new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 });

  function readJson(id) {
    try {
      return JSON.parse(document.getElementById(id)?.textContent || "{}");
    } catch (_error) {
      return {};
    }
  }
  const catalog = readJson("reward-batch-catalog");
  const plans = readJson("reward-batch-plans");
  const today = startInput?.min || "";

  /* ---- 日期（一律用 YYYY-MM-DD 字串比較，避免時區） ---- */
  const slash = (iso) => iso.replaceAll("-", "/");
  function dayBefore(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    const value = new Date(Date.UTC(y, m - 1, d - 1));
    return value.toISOString().slice(0, 10);
  }
  const period = (plan) => (plan.to ? `${slash(plan.from)}–${slash(plan.to)}` : `${slash(plan.from)} 起・未設結束日`);

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /* ---- 品項列 ---- */
  function parseQuantity(text) {
    const cleaned = String(text || "").replace(/[,，\s]/g, "");
    if (cleaned === "") return null;
    return /^\d+$/.test(cleaned) ? Number(cleaned) : NaN;
  }

  function costOn(item, day) {
    if (!item || !day) return null;
    const version = item.costs.find((cost) => cost.from <= day && (!cost.to || cost.to >= day));
    return version ? Number(version.amount) : null;
  }

  function items() {
    return list ? Array.from(list.querySelectorAll("[data-reward-item]")) : [];
  }

  function refreshItems() {
    const day = startInput?.value || today;
    const seen = new Set();
    let total = 0;
    let missing = false;
    let counted = 0;
    const rows = items();
    rows.forEach((row, index) => {
      row.querySelector("[data-reward-index]").textContent = index + 1;
      const select = row.querySelector("[data-reward-catalog]");
      const quantityInput = row.querySelector("[data-reward-quantity]");
      const unit = row.querySelector("[data-reward-unit]");
      const cost = row.querySelector("[data-reward-cost]");
      const item = catalog[select.value];
      const quantity = parseQuantity(quantityInput.value);
      unit.textContent = item ? item.unit : "";
      row.querySelector("[data-reward-remove]").disabled = rows.length === 1 && !select.value && !quantityInput.value;
      let problem = "";
      if (item && seen.has(select.value)) problem = "已選過此品項，同一方案不可重複";
      else if (Number.isNaN(quantity)) problem = "數量只能是正整數";
      else if (quantity === 0) problem = "數量至少為 1";
      if (item) seen.add(select.value);
      row.classList.toggle("is-invalid", Boolean(problem));
      quantityInput.setAttribute("aria-invalid", Number.isNaN(quantity) || quantity === 0 ? "true" : "false");
      cost.replaceChildren();
      cost.classList.toggle("is-error", Boolean(problem));
      if (problem) { cost.textContent = problem; return; }
      if (!item) { cost.textContent = "選擇品項後顯示成本"; return; }
      const unitCost = costOn(item, day);
      if (unitCost === null) {
        cost.textContent = `${item.type}・此日期尚未維護成本`;
        if (quantity) missing = true;
        return;
      }
      cost.append(`${item.type}・單位成本 $${number.format(unitCost)}`);
      if (quantity) {
        cost.append(` × ${number.format(quantity)} = `);
        cost.append(element("strong", "", `$${number.format(unitCost * quantity)}`));
        total += unitCost * quantity;
        counted += 1;
      }
    });
    if (totalNode) totalNode.textContent = `$${number.format(total)}`;
    if (totalNote) {
      totalNote.textContent = missing
        ? "部分品項此日期尚未維護成本，未計入"
        : counted ? `依 ${slash(day)} 的品項成本版本估算` : "選擇品項並填寫數量後估算";
    }
    const add = form.querySelector("[data-reward-add]");
    if (add && list) add.disabled = rows.length >= Number(list.dataset.max || 20);
  }

  function bindItem(row) {
    row.querySelector("[data-reward-remove]").addEventListener("click", () => {
      if (items().length === 1) {
        row.querySelectorAll("select, input").forEach((field) => { field.value = ""; });
        row.querySelector("[data-reward-catalog]").focus();
      } else {
        const next = row.nextElementSibling || row.previousElementSibling;
        row.remove();
        next?.querySelector("select")?.focus();
      }
      row.querySelectorAll(".field-error").forEach((node) => node.remove());
      refreshItems();
    });
    row.querySelector("[data-reward-quantity]").addEventListener("blur", (event) => {
      const value = parseQuantity(event.target.value);
      if (value) event.target.value = number.format(value);
    });
  }

  if (list) {
    items().forEach(bindItem);
    list.addEventListener("input", refreshItems);
    list.addEventListener("change", (event) => {
      const row = event.target.closest("[data-reward-item]");
      if (row && event.target.matches("[data-reward-catalog]")) {
        row.classList.remove("has-error");
        row.querySelectorAll(".field-error").forEach((node) => node.remove());
        if (event.target.value) row.querySelector("[data-reward-quantity]").focus();
      }
      refreshItems();
    });
    form.querySelector("[data-reward-add]")?.addEventListener("click", () => {
      if (!template) return;
      const row = template.content.firstElementChild.cloneNode(true);
      list.appendChild(row);
      bindItem(row);
      refreshItems();
      row.querySelector("select").focus();
    });
    items().forEach((row) => {
      const input = row.querySelector("[data-reward-quantity]");
      const value = parseQuantity(input.value);
      if (value) input.value = number.format(value);
    });
  }

  /* ---- 各年式的處理方式（同 decide()） ---- */
  function decide(modelPlans, start, end, closeOpen) {
    const current = modelPlans.find((plan) => plan.active && plan.from <= start && (!plan.to || plan.to >= start)) || null;
    const sameDay = modelPlans.find((plan) => plan.from === start);
    if (sameDay) {
      return { status: "skip", current, reason: `${slash(start)} 已有開始的方案${sameDay.active ? "" : "（已停用）"}，請到「傭金與獎勵」分頁修改該方案` };
    }
    const overlapping = modelPlans.filter((plan) => plan.active && (!plan.to || plan.to >= start) && (!end || plan.from <= end));
    let closable = null;
    for (const plan of overlapping) {
      if (plan.to) {
        return { status: "skip", current, reason: `原方案（${period(plan)}）已設定結束日，與新方案期間重疊；已排定的期間不自動修改，請到「傭金與獎勵」分頁調整` };
      }
      if (plan.from > start) {
        return { status: "skip", current, reason: `已排定 ${slash(plan.from)} 起的方案，與新方案期間重疊；請縮短新方案結束日或調整排定方案` };
      }
      closable = plan;
    }
    if (closable) {
      if (!closeOpen) {
        return { status: "skip", current, reason: `原方案（${slash(closable.from)} 起）沒有結束日，與新方案重疊；勾選「自動設為新方案前一天結束」或先到「傭金與獎勵」分頁設定結束日` };
      }
      return { status: "close", current, closeTo: dayBefore(start) };
    }
    return { status: "create", current };
  }

  function chip(className, text) {
    return element("span", `model-chip ${className}`, text);
  }

  function refreshRows() {
    let start = startInput?.value || "";
    if (!start || start < today) start = today;
    const rawEnd = endInput?.value || "";
    const end = rawEnd && rawEnd >= start ? rawEnd : "";
    if (endInput) endInput.min = start;
    if (dayLabel) dayLabel.textContent = slash(start);
    const counts = { create: 0, close: 0, skip: 0 };
    let selected = 0;
    form.querySelectorAll("[data-batch-row][data-model]").forEach((row) => {
      const decision = decide(plans[row.dataset.model] || [], start, end, Boolean(closeInput?.checked));
      const current = row.querySelector("[data-reward-current]");
      const outcome = row.querySelector("[data-reward-outcome]");
      current.replaceChildren();
      if (decision.current) {
        const wrap = element("span", "model-reward-current");
        const text = decision.current.items + (decision.current.to ? `（至 ${slash(decision.current.to)}）` : "");
        wrap.append(element("strong", "", text), element("small", "", period(decision.current)));
        current.append(wrap);
      } else {
        current.append(element("span", "model-reward-muted", "無"));
      }
      outcome.replaceChildren();
      if (decision.status === "close") {
        outcome.append(chip("is-close", "結束原方案並新增"), element("small", "model-chip__detail", `原方案設為 ${slash(decision.closeTo)} 結束`));
      } else if (decision.status === "create") {
        outcome.append(chip("is-create", "新增方案"));
      } else {
        outcome.append(chip("is-skip", "略過"), element("small", "model-chip__detail", decision.reason));
      }
      row.classList.toggle("is-skipped", decision.status === "skip");
      if (row.querySelector("[data-row-check]")?.checked) {
        selected += 1;
        counts[decision.status] += 1;
      }
    });
    if (summary) {
      summary.replaceChildren();
      summary.append("已勾選 ", element("strong", "", String(selected)), " 個年式");
      if (selected) {
        const parts = [];
        if (counts.create) parts.push(`新增 ${counts.create}`);
        if (counts.close) parts.push(`結束原方案並新增 ${counts.close}`);
        if (counts.skip) parts.push(`略過 ${counts.skip}`);
        summary.append(`・${parts.join("・")}`);
      } else {
        summary.append("・確認前會先列出每個年式的處理方式");
      }
      summary.append(`・${slash(start)} 起${end ? `至 ${slash(end)}` : ""}`);
    }
  }

  startInput?.addEventListener("change", () => { refreshItems(); refreshRows(); });
  endInput?.addEventListener("change", refreshRows);
  closeInput?.addEventListener("change", refreshRows);
  form.addEventListener("selection-change", refreshRows);

  /* ---- 篩選時保留已填的方案內容（帶在網址上，伺服器以同一組欄位讀回） ---- */
  const filters = document.querySelector("[data-model-tool-filters]");
  filters?.addEventListener("submit", () => {
    filters.querySelectorAll("[data-reward-carry]").forEach((node) => node.remove());
    const carry = (name, value) => {
      if (value === "" || value === null || value === undefined) return;
      const input = element("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      input.dataset.rewardCarry = "";
      filters.appendChild(input);
    };
    carry("editor", "1");
    carry("effective_from", startInput?.value);
    carry("effective_to", endInput?.value);
    if (closeInput?.checked) carry("close_open", "1");
    carry("plan_note", form.querySelector("[name=plan_note]")?.value.trim());
    items().forEach((row) => {
      const catalogValue = row.querySelector("[data-reward-catalog]").value;
      const quantity = row.querySelector("[data-reward-quantity]").value.trim();
      const note = row.querySelector("[name=item_note]").value.trim();
      if (!catalogValue && !quantity && !note) return;
      carry("item_catalog", catalogValue || " ");
      carry("item_quantity", quantity || " ");
      carry("item_note", note || " ");
    });
    form.querySelectorAll("[data-row-check]:checked").forEach((box) => carry("selected", box.value));
  });

  refreshItems();
  refreshRows();
})();
