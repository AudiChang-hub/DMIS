/* 原廠代墊／代轉（T-334 第一版）：訂單頁小區塊、追蹤頁、營運總表卡片與側邊明細共用這一支。
   - 勾「原廠已撥」「已交給對象」就存，存好列上出現「復原」；送出時帶畫面上看到的狀態，別處剛改過就退回並換成最新狀態。
   - 同一頁有好幾處顯示同一筆（例如側邊明細與卡片）時，依伺服器回傳的狀態一起更新；側邊明細關掉後卡片重新取數字。
   - 追蹤頁「原廠已撥」：多選幾列 → 登記原廠撥款 → 填撥款日、實撥金額，顯示勾選合計／實撥／差額（差額只顯示）→ 一次標成已撥。
   - 營運總表卡片：點兩半任一邊從右側滑出明細（手機從底部），內容同追蹤頁；頁籤與「套用」在面板內換內容，不換頁。 */
(() => {
  "use strict";

  const number = new Intl.NumberFormat("zh-TW");
  const money = (value) => `$${number.format(Math.round(value || 0))}`;
  const signedMoney = (value) => (value === 0 ? "$0" : `${value > 0 ? "＋" : "−"}$${number.format(Math.abs(Math.round(value)))}`);
  const parseAmount = (text) => {
    const raw = String(text ?? "").trim();
    if (!/^\d+$/.test(raw)) return null;
    return Number.parseInt(raw, 10);
  };

  // ── 純計算（node 測試直接呼叫）──────────────────────────────────────

  /** 勾選的列 → 筆數、金額合計、贈品件數、原廠（一次只能登記一家）。 */
  function selectionSummary(picks) {
    const manufacturers = [...new Set(picks.map((pick) => pick.manufacturer))];
    return {
      count: picks.length,
      total: picks.reduce((sum, pick) => sum + (Number(pick.amount) || 0), 0),
      gifts: picks.reduce((sum, pick) => sum + (Number(pick.gift) || 0), 0),
      manufacturers,
      mixed: manufacturers.length > 1,
    };
  }

  /** 只選一筆時，實撥金額預設帶那一筆的金額；多筆時留空讓人照實際撥款填。 */
  function defaultPayoutAmount(picks) {
    return picks.length === 1 && Number(picks[0].amount) > 0 ? String(Math.round(Number(picks[0].amount))) : "";
  }

  /** 勾選合計／實撥／差額：差額＝實撥－勾選合計，只顯示，不算進任何收支。 */
  function payoutFigures(selected, actualText) {
    const actual = parseAmount(actualText);
    return {
      selected,
      actual,
      difference: actual === null ? null : actual - selected,
      selectedText: money(selected),
      actualText: actual === null ? "—" : money(actual),
      differenceText: actual === null ? "—" : (actual === selected ? "沒有差額" : signedMoney(actual - selected)),
      tone: actual === null || actual === selected ? "" : actual > selected ? "is-positive" : "is-negative",
    };
  }

  /** 一筆從 before 變成 after 時，兩個頁籤的筆數各要加減多少（等原廠撥款＝還沒已撥、等交給對象＝還沒交）。 */
  function tabDeltas(before, after) {
    const delta = (key) => (before[key] === after[key] ? 0 : after[key] ? -1 : 1);
    return {reimburse: delta("reimbursed"), handover: delta("handed_over")};
  }

  /** 天數提醒（與伺服器同一條）：超過 7 天才標。 */
  function isOverdue(days, limit = 7) {
    return Number(days) > limit;
  }

  const api = {selectionSummary, defaultPayoutAmount, payoutFigures, tabDeltas, isOverdue, money, signedMoney, parseAmount};
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
    return;
  }
  window.DMISManufacturerAdvance = api;

  // ── 畫面 ────────────────────────────────────────────────────────────

  let drawer = null;

  const csrfOf = (element) => element?.closest("[data-csrf]")?.dataset.csrf
    || document.querySelector("[data-csrf]")?.dataset.csrf
    || document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";

  async function post(url, fields, origin) {
    const body = fields instanceof FormData ? fields : new FormData();
    if (!(fields instanceof FormData)) {
      Object.entries(fields).forEach(([key, value]) => {
        (Array.isArray(value) ? value : [value]).forEach((item) => body.append(key, item));
      });
    }
    if (!body.has("csrfmiddlewaretoken")) body.append("csrfmiddlewaretoken", csrfOf(origin));
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, {
        method: "POST", body, credentials: "same-origin", signal: controller.signal,
        headers: {"X-Requested-With": "XMLHttpRequest"},
      });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 403) payload.message = payload.message || "沒有修改的權限（比照訂單「收入與支出」）。";
      if (response.status === 404) payload.message = payload.message || "找不到這筆，可能已被刪除，請重新整理。";
      if (!payload.message && !response.ok) payload.message = "沒有存成功，請再試一次。";
      return {ok: response.ok && payload.ok, status: response.status, payload};
    } catch (error) {
      return {ok: false, status: 0, payload: {message: error.name === "AbortError" ? "等候逾時，沒有存成功，請再試一次。" : "連線失敗，沒有存成功，請再試一次。"}};
    } finally {
      window.clearTimeout(timer);
    }
  }

  function showStatus(target, text, {tone = "", undo = null, undoLabel = "復原"} = {}) {
    if (!target) return;
    target.replaceChildren();
    const message = document.createElement("span");
    message.textContent = text;
    target.append(message);
    if (undo) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button ghost small advance-status__undo";
      button.textContent = undoLabel;
      button.addEventListener("click", undo, {once: true});
      target.append(button);
    }
    target.classList.toggle("is-error", tone === "error");
    target.classList.toggle("is-saving", tone === "saving");
    target.hidden = false;
  }

  const rowStatus = (element) => element.closest("[data-advance-item]")?.querySelector("[data-advance-row-status]");

  function stateOfRow(row) {
    const flag = (name) => Boolean(row.querySelector(`[data-advance-toggle="${name}"]`)?.checked);
    return {reimbursed: flag("reimbursed"), handed_over: flag("handed_over")};
  }

  function adjustTabCount(panel, key, delta) {
    if (!delta) return;
    const badge = panel?.querySelector(`[data-advance-tab="${key}"] [data-advance-tab-count]`);
    if (!badge) return;
    badge.textContent = String(Math.max((Number.parseInt(badge.textContent, 10) || 0) + delta, 0));
  }

  /** 把伺服器回傳的狀態套到頁面上每一處顯示這筆的地方（訂單頁、追蹤頁、側邊明細）。 */
  function applyState(state) {
    document.querySelectorAll(`[data-advance-item="${state.id}"]`).forEach((row) => {
      const before = stateOfRow(row);
      ["reimbursed", "handed_over"].forEach((flag) => {
        const box = row.querySelector(`[data-advance-toggle="${flag}"]`);
        if (!box) return;
        box.checked = Boolean(state[flag]);
        box.closest("[data-advance-check]")?.classList.toggle("is-checked", Boolean(state[flag]));
        const meta = row.querySelector(`[data-advance-meta="${flag}"]`);
        if (meta) meta.textContent = state[`${flag}_label`] || "";
      });
      row.classList.toggle("is-settled", Boolean(state.settled));
      const voidButton = row.querySelector("[data-advance-void]");
      if (voidButton) voidButton.hidden = Boolean(state.reimbursed || state.handed_over);
      const panel = row.closest("[data-advance-panel]");
      if (panel) {
        const deltas = tabDeltas(before, state);
        adjustTabCount(panel, "reimburse", deltas.reimburse);
        adjustTabCount(panel, "handover", deltas.handover);
        const tab = panel.dataset.tab;
        const done = tab === "reimburse" ? state.reimbursed : state.handed_over;
        row.classList.toggle("is-done", Boolean(done || state.voided));
        const pick = row.querySelector("[data-advance-pick]");
        if (pick) {
          pick.disabled = Boolean(done || state.voided);
          if (pick.disabled) pick.checked = false;
        }
        refreshBatch(panel);
      }
    });
    if (drawer) drawer.dirty = true;
  }

  // ── 勾選 ────────────────────────────────────────────────────────────

  async function toggle(box, {value = box.checked, undo = false} = {}) {
    const flag = box.dataset.advanceToggle;
    const status = rowStatus(box);
    const label = flag === "reimbursed" ? "原廠已撥" : "已交給對象";
    box.disabled = true;
    showStatus(status, undo ? "復原中…" : "儲存中…", {tone: "saving"});
    const {ok, payload} = await post(box.dataset.url, {
      flag, value: value ? "1" : "0", expected: value ? "0" : "1", ...(undo ? {undo: "1"} : {}),
    }, box);
    box.disabled = false;
    if (!ok) {
      box.checked = !value;
      (payload.items || []).forEach(applyState);
      showStatus(status, payload.message, {tone: "error"});
      return;
    }
    (payload.items || []).forEach(applyState);
    if (undo) {
      showStatus(status, `已復原「${label}」`);
    } else if (payload.changed) {
      showStatus(status, payload.message, {undo: () => {
        const current = document.querySelector(`[data-advance-item="${payload.items[0].id}"] [data-advance-toggle="${flag}"]`) || box;
        toggle(current, {value: !value, undo: true});
      }});
    } else {
      showStatus(status, payload.message);
    }
  }

  document.addEventListener("change", (event) => {
    const box = event.target.closest?.("[data-advance-toggle]");
    if (box && !box.disabled) toggle(box);
  });

  // ── 訂單頁：新增、刪除 ─────────────────────────────────────────────

  function replaceBlock(block, html) {
    const holder = document.createElement("div");
    holder.innerHTML = html.trim();
    const fresh = holder.querySelector("[data-advance-block]");
    if (!fresh) return block;
    block.replaceWith(fresh);
    return fresh;
  }

  function kindPanels(form) {
    const kind = form.querySelector("[data-advance-kind]:checked")?.value || "cash";
    form.querySelectorAll("[data-advance-kind-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.advanceKindPanel !== kind;
    });
  }

  function clearErrors(form) {
    form.querySelectorAll(".advance-field-error").forEach((node) => node.remove());
    form.querySelectorAll("[aria-invalid]").forEach((node) => node.removeAttribute("aria-invalid"));
  }

  function showErrors(form, errors) {
    let first = null;
    Object.entries(errors || {}).forEach(([name, messages]) => {
      const field = form.querySelector(`[data-advance-field="${name}"]`);
      if (!field) return;
      const input = field.querySelector("input");
      const note = document.createElement("small");
      note.className = "field-error advance-field-error";
      note.id = `${input?.id || name}-error`;
      note.textContent = messages[0];
      field.append(note);
      if (input) {
        input.setAttribute("aria-invalid", "true");
        input.setAttribute("aria-describedby", note.id);
        first = first || input;
      }
    });
    first?.focus();
  }

  function openForm(block, open) {
    const form = block.querySelector("[data-advance-form]");
    const add = block.querySelector("[data-advance-add]");
    if (!form) return;
    form.hidden = !open;
    add?.setAttribute("aria-expanded", String(open));
    block.classList.toggle("is-adding", open);
    if (open) {
      kindPanels(form);
      form.querySelector("[name=campaign_name]")?.focus();
    } else {
      form.reset();
      clearErrors(form);
      kindPanels(form);
      add?.focus();
    }
  }

  document.addEventListener("click", async (event) => {
    const add = event.target.closest?.("[data-advance-add]");
    if (add) {
      const block = add.closest("[data-advance-block]");
      openForm(block, block.querySelector("[data-advance-form]")?.hidden !== false);
      return;
    }
    const cancel = event.target.closest?.("[data-advance-cancel]");
    if (cancel) {
      openForm(cancel.closest("[data-advance-block]"), false);
      return;
    }
    const voidButton = event.target.closest?.("[data-advance-void]");
    if (voidButton && !voidButton.disabled) {
      voidButton.disabled = true;
      voidItem(voidButton.closest("[data-advance-block]"), voidButton.dataset.url,
        {origin: voidButton, restore: voidButton.dataset.advanceRestore === "1"})
        .finally(() => { voidButton.disabled = false; });
    }
  });

  document.addEventListener("change", (event) => {
    const kind = event.target.closest?.("[data-advance-kind]");
    if (kind) kindPanels(kind.form);
  });

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest?.("[data-advance-form]");
    if (!form) return;
    event.preventDefault();
    event.stopPropagation();
    if (form.dataset.saving) return;
    const block = form.closest("[data-advance-block]");
    clearErrors(form);
    form.dataset.saving = "1";
    const submit = form.querySelector("[type=submit]");
    submit?.setAttribute("aria-busy", "true");
    const {ok, payload} = await post(form.action, new FormData(form), form);
    delete form.dataset.saving;
    submit?.removeAttribute("aria-busy");
    if (!ok) {
      showErrors(form, payload.errors);
      showStatus(block.querySelector("[data-advance-status]"), payload.message, {tone: "error"});
      return;
    }
    const fresh = replaceBlock(block, payload.html);
    showStatus(fresh.querySelector("[data-advance-status]"), payload.message);
    fresh.querySelector("[data-advance-add]")?.focus();
  }, true);

  async function voidItem(block, url, {restore = false, origin = null} = {}) {
    const {ok, payload} = await post(url, restore ? {restore: "1"} : {}, block);
    if (!ok) {
      (payload.items || []).forEach(applyState);
      showStatus((origin && rowStatus(origin)) || block.querySelector("[data-advance-status]"), payload.message, {tone: "error"});
      return;
    }
    const fresh = replaceBlock(block, payload.html);
    const status = fresh.querySelector("[data-advance-status]");
    showStatus(status, payload.message, restore ? {} : {undo: () => voidItem(fresh, url, {restore: true})});
    (fresh.querySelector("[data-advance-add]") || status).focus?.();
  }

  // ── 追蹤頁／側邊明細：多選與登記原廠撥款 ─────────────────────────────

  const picksOf = (panel) => [...panel.querySelectorAll("[data-advance-pick]")];
  const pickData = (box) => {
    const row = box.closest("[data-advance-item]");
    return {id: row.dataset.advanceItem, amount: Number(row.dataset.advanceAmount) || 0, gift: Number(row.dataset.advanceGift) || 0,
      manufacturer: row.dataset.advanceManufacturer || "", number: row.querySelector("a")?.textContent || ""};
  };
  const chosen = (panel) => picksOf(panel).filter((box) => box.checked && !box.disabled).map(pickData);

  function refreshBatch(panel) {
    const batch = panel.querySelector("[data-advance-batch]");
    if (!batch) return;
    const picks = chosen(panel);
    const summary = selectionSummary(picks);
    picksOf(panel).forEach((box) => box.closest("[data-advance-item]")?.classList.toggle("is-picked", box.checked));
    batch.hidden = summary.count === 0;
    batch.querySelector("[data-advance-batch-count]").textContent = String(summary.count);
    batch.querySelector("[data-advance-batch-total]").textContent = money(summary.total);
    const gifts = batch.querySelector("[data-advance-batch-gifts]");
    gifts.hidden = !summary.gifts;
    gifts.textContent = summary.gifts ? `另有贈品 ${summary.gifts} 件` : "";
    const warn = batch.querySelector("[data-advance-batch-warn]");
    warn.hidden = !summary.mixed;
    warn.textContent = summary.mixed ? `勾到不同原廠（${summary.manufacturers.join("、")}），一次只能登記一家；可以先用「原廠」篩選。` : "";
    batch.querySelector("[data-advance-batch-open]").disabled = summary.mixed;
    const all = panel.querySelector("[data-advance-pick-all]");
    if (all) {
      const enabled = picksOf(panel).filter((box) => !box.disabled);
      all.checked = enabled.length > 0 && enabled.every((box) => box.checked);
      all.indeterminate = !all.checked && enabled.some((box) => box.checked);
    }
  }

  document.addEventListener("change", (event) => {
    const all = event.target.closest?.("[data-advance-pick-all]");
    const pick = event.target.closest?.("[data-advance-pick]");
    const panel = (all || pick)?.closest("[data-advance-panel]");
    if (!panel) return;
    if (all) picksOf(panel).forEach((box) => { if (!box.disabled) box.checked = all.checked; });
    refreshBatch(panel);
  });

  function figures(dialog, picks) {
    const summary = selectionSummary(picks);
    const view = payoutFigures(summary.total, dialog.querySelector("[data-advance-paid-amount]").value);
    dialog.querySelector("[data-advance-payout-selected]").textContent = view.selectedText;
    dialog.querySelector("[data-advance-payout-actual]").textContent = view.actualText;
    const diff = dialog.querySelector("[data-advance-payout-diff]");
    diff.textContent = view.differenceText;
    diff.classList.toggle("is-positive", view.tone === "is-positive");
    diff.classList.toggle("is-negative", view.tone === "is-negative");
  }

  function openDialog(panel, opener) {
    const dialog = panel.querySelector("[data-advance-dialog]");
    const picks = chosen(panel);
    if (!dialog || !picks.length) return;
    const summary = selectionSummary(picks);
    if (summary.mixed) return;
    dialog.picks = picks;
    dialog.opener = opener;
    dialog.querySelector("[data-advance-dialog-scope]").textContent =
      `${summary.manufacturers[0]}・${summary.count} 筆${summary.gifts ? `（含贈品 ${summary.gifts} 件，不算金額）` : ""}`;
    const amount = dialog.querySelector("[data-advance-paid-amount]");
    amount.value = defaultPayoutAmount(picks);
    const error = dialog.querySelector("[data-advance-dialog-error]");
    error.hidden = true;
    error.textContent = "";
    figures(dialog, picks);
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
    amount.focus();
    amount.select?.();
  }

  function closeDialog(dialog) {
    if (dialog.open && typeof dialog.close === "function") dialog.close(); else dialog.removeAttribute("open");
    dialog.opener?.focus?.();
  }

  document.addEventListener("click", (event) => {
    const open = event.target.closest?.("[data-advance-batch-open]");
    if (open) {
      openDialog(open.closest("[data-advance-panel]"), open);
      return;
    }
    const clear = event.target.closest?.("[data-advance-batch-clear]");
    if (clear) {
      const panel = clear.closest("[data-advance-panel]");
      picksOf(panel).forEach((box) => { box.checked = false; });
      refreshBatch(panel);
      return;
    }
    const cancel = event.target.closest?.("[data-advance-dialog-cancel]");
    if (cancel) closeDialog(cancel.closest("[data-advance-dialog]"));
  });

  document.addEventListener("input", (event) => {
    const amount = event.target.closest?.("[data-advance-paid-amount]");
    if (!amount) return;
    const dialog = amount.closest("[data-advance-dialog]");
    figures(dialog, dialog.picks || []);
  });

  /** 登記原廠撥款後，已撥的列立即從「等原廠撥款」清單移走（T-337）；復原時放回來。筆數與空狀態跟著更新。 */
  function setPaidRowsHidden(ids, hidden) {
    document.querySelectorAll('[data-advance-panel][data-tab="reimburse"]').forEach((panel) => {
      ids.forEach((id) => panel.querySelectorAll(`[data-advance-item="${id}"]`).forEach((row) => { row.hidden = hidden; }));
      const rows = [...panel.querySelectorAll("[data-advance-item]")];
      const visible = rows.filter((row) => !row.hidden).length;
      const count = panel.querySelector("[data-advance-summary-count]");
      if (count) count.textContent = String(visible);
      const empty = visible === 0 && rows.length > 0;
      panel.querySelector("[data-advance-empty]")?.toggleAttribute("hidden", !empty);
      panel.querySelector("[data-advance-summary]")?.toggleAttribute("hidden", empty);
      panel.querySelectorAll(".inventory-table-wrap, .advance-cards").forEach((list) => list.toggleAttribute("hidden", empty));
      refreshBatch(panel);
    });
  }

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest?.("[data-advance-payout-form]");
    if (!form) return;
    event.preventDefault();
    event.stopPropagation();
    const dialog = form.closest("[data-advance-dialog]");
    const panel = form.closest("[data-advance-panel]");
    if (form.dataset.saving) return;
    const error = dialog.querySelector("[data-advance-dialog-error]");
    const amount = parseAmount(form.elements.amount.value);
    const fail = (message, field) => {
      error.textContent = message;
      error.hidden = false;
      field?.focus();
    };
    if (!form.elements.paid_on.value) return fail("請填撥款日。", form.elements.paid_on);
    if (amount === null) return fail("請填實撥金額（整數，可以是 0）。", form.elements.amount);
    const submit = form.querySelector("[data-advance-dialog-submit]");
    form.dataset.saving = "1";
    submit.disabled = true;
    const ids = (dialog.picks || []).map((pick) => pick.id);
    const {ok, payload} = await post(panel.dataset.payoutUrl, {paid_on: form.elements.paid_on.value, amount: String(amount), items: ids}, panel);
    submit.disabled = false;
    delete form.dataset.saving;
    (payload.items || []).forEach(applyState);
    if (!ok) {
      fail(payload.message);
      return;
    }
    closeDialog(dialog);
    const paidIds = (payload.items || []).map((item) => String(item.id));
    setPaidRowsHidden(paidIds, true);
    const status = panel.querySelector("[data-advance-status]");
    const voidUrl = panel.dataset.payoutVoidUrl.replace("/0/", `/${payload.payout}/`);
    showStatus(status, payload.message, {undo: async () => {
      showStatus(status, "復原中…", {tone: "saving"});
      const result = await post(voidUrl, {}, panel);
      (result.payload.items || []).forEach(applyState);
      if (result.ok) setPaidRowsHidden(paidIds, false);
      showStatus(status, result.payload.message, {tone: result.ok ? "" : "error"});
    }});
  }, true);

  // ── 營運總表：卡片與側邊明細 ────────────────────────────────────────

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function createDrawer() {
    const scrim = make("div", "advance-drawer-scrim");
    scrim.hidden = true;
    const element = make("aside", "advance-drawer");
    element.setAttribute("role", "dialog");
    element.setAttribute("aria-modal", "false");
    element.setAttribute("aria-labelledby", "advance-drawer-title");
    element.setAttribute("inert", "");
    const head = make("header", "advance-drawer__head");
    const heading = make("div", "advance-drawer__heading");
    const eyebrow = make("p", "advance-drawer__eyebrow", "目前未結・不跟期間切換");
    const title = make("h2", "advance-drawer__title", "原廠代墊／代轉");
    title.id = "advance-drawer-title";
    title.tabIndex = -1;
    heading.append(eyebrow, title);
    const closeButton = make("button", "advance-drawer__close", "×");
    closeButton.type = "button";
    closeButton.setAttribute("aria-label", "關閉原廠代墊／代轉明細");
    head.append(heading, closeButton);
    const body = make("div", "advance-drawer__body");
    element.append(head, body);
    document.body.append(scrim, element);
    const state = {element, scrim, body, title, opened: false, dirty: false, trigger: null, card: null};

    async function load(url) {
      element.setAttribute("aria-busy", "true");
      element.dataset.state = "loading";
      const skeleton = make("ul", "advance-drawer__skeleton");
      skeleton.setAttribute("aria-hidden", "true");
      for (let index = 0; index < 4; index += 1) {
        const row = make("li");
        row.append(make("span"), make("span"));
        skeleton.append(row);
      }
      body.replaceChildren(skeleton);
      try {
        const response = await fetch(url, {credentials: "same-origin", headers: {"X-Requested-With": "XMLHttpRequest"}});
        if (!response.ok) throw Object.assign(new Error("http"), {status: response.status});
        body.innerHTML = await response.text();
        element.dataset.state = "ready";
      } catch (error) {
        element.dataset.state = "error";
        const box = make("div", "advance-drawer__notice");
        box.setAttribute("role", "alert");
        const denied = error.status === 403 || error.status === 404;
        box.append(make("p", "", denied ? "沒有查看原廠代墊／代轉的權限。" : "明細沒有載入成功。"));
        const actions = make("p", "advance-drawer__actions");
        if (!denied) {
          const retry = make("button", "button ghost small", "再試一次");
          retry.type = "button";
          retry.addEventListener("click", () => load(url));
          actions.append(retry);
        }
        const all = make("a", "", "改開追蹤頁");
        all.href = state.card?.querySelector(".ops-card__head a")?.href || url.replace(/[?&]fragment=panel/, "");
        actions.append(all);
        box.append(actions);
        body.replaceChildren(box);
      } finally {
        element.removeAttribute("aria-busy");
      }
    }

    state.load = load;
    state.open = (trigger, url) => {
      state.trigger = trigger;
      state.card = trigger.closest("[data-advance-ops-card]");
      if (!state.opened) {
        element.removeAttribute("inert");
        element.classList.add("is-open");
        scrim.hidden = false;
        state.opened = true;
      }
      load(url);
      title.focus({preventScroll: true});
    };
    state.close = ({restoreFocus = true} = {}) => {
      if (!state.opened) return;
      state.opened = false;
      element.classList.remove("is-open");
      element.setAttribute("inert", "");
      scrim.hidden = true;
      if (state.dirty && state.card) refreshCard(state.card);
      state.dirty = false;
      if (restoreFocus) {
        const target = state.trigger?.isConnected ? state.trigger
          : document.querySelector(`[data-advance-open="${state.trigger?.dataset.advanceOpen}"]`);
        target?.focus({preventScroll: true});
      }
    };
    closeButton.addEventListener("click", () => state.close());
    scrim.addEventListener("click", () => state.close());
    return state;
  }

  async function refreshCard(card) {
    try {
      const response = await fetch(card.dataset.cardUrl, {credentials: "same-origin", headers: {"X-Requested-With": "XMLHttpRequest"}});
      if (!response.ok) return;
      const holder = document.createElement("div");
      holder.innerHTML = (await response.text()).trim();
      const fresh = holder.querySelector("[data-advance-ops-card]");
      if (fresh) card.replaceWith(fresh);
      if (drawer) drawer.card = fresh;
    } catch (error) {
      // 取不到新數字時保留原卡片；重新整理頁面就會同步。
    }
  }

  function panelUrl(card, params) {
    const url = new URL(card.dataset.panelUrl, window.location.href);
    Object.entries(params).forEach(([key, value]) => { if (value) url.searchParams.set(key, value); });
    return `${url.pathname}${url.search}`;
  }

  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button > 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const opener = event.target.closest?.("[data-advance-open]");
    if (opener) {
      const card = opener.closest("[data-advance-ops-card]");
      if (!card) return;
      event.preventDefault();
      drawer = drawer || createDrawer();
      drawer.open(opener, panelUrl(card, {tab: opener.dataset.advanceOpen}));
      return;
    }
    // 面板裡的頁籤與「清除」：在側邊明細裡換內容，不換頁。
    const link = event.target.closest?.("[data-advance-tab], [data-advance-clear]");
    if (link && drawer?.opened && drawer.element.contains(link) && drawer.card) {
      event.preventDefault();
      const target = new URL(link.href, window.location.href);
      drawer.load(panelUrl(drawer.card, Object.fromEntries(target.searchParams)));
      return;
    }
    // 用事件當下的路徑判斷：按下的按鈕若在處理時被換掉（例如「復原」），仍算在面板裡。
    const path = event.composedPath ? event.composedPath() : [event.target];
    if (drawer?.opened && !path.includes(drawer.element) && !path.some((node) => node?.tagName === "DIALOG")) {
      // 點到面板外（桌機）：關閉，比照報表熱度格。
      drawer.close({restoreFocus: false});
    }
  });

  document.addEventListener("submit", (event) => {
    const filter = event.target.closest?.("[data-advance-filter]");
    if (!filter || !drawer?.opened || !drawer.element.contains(filter) || !drawer.card) return;
    event.preventDefault();
    event.stopPropagation();
    drawer.load(panelUrl(drawer.card, Object.fromEntries(new FormData(filter))));
  }, true);

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !drawer?.opened) return;
    if (document.querySelector("[data-advance-dialog][open]")) return; // 先關登記撥款的視窗
    drawer.close();
  });

  document.querySelectorAll("[data-advance-panel]").forEach(refreshBatch);
})();
