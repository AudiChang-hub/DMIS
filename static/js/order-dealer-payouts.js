/* 訂單頁「車行獎勵」卡逐項勾已給付（T-315，使用者選 A）：與「車行傭金／獎金給付」頁同一筆紀錄。
   勾選直接送出；取消（已給付→未給付、匯入前已結清→改回未給付）先在該列下方開確認卡，按「取消已給付」才送出，
   「保留」或 Esc 關閉並把焦點還給勾選框。送出交給 form-feedback.js（防重複送出）與 inplace-regions.js（原地換入卡片）；
   沒有 JavaScript 時各列有 noscript 按鈕可整頁送出。 */
(() => {
  "use strict";

  // 換入新版卡片後，焦點回到剛操作的那一格（勾選後表單的 action 會變，inplace-regions.js 對不上原表單，只能回到整張卡）。
  let pendingFocus = "";
  document.addEventListener("inplace:updated", () => {
    if (!pendingFocus) return;
    const toggle = document.getElementById(pendingFocus);
    pendingFocus = "";
    const active = document.activeElement;
    if (toggle && (!active || active === document.body || active.matches("[data-order-dealer-rewards]"))) {
      toggle.focus({preventScroll: true});
    }
  });

  function submit(form, toggle) {
    const row = form.closest("[data-order-payout-row]");
    row?.classList.add("is-saving");
    pendingFocus = toggle.id;
    form.requestSubmit();
    // 重複送出被擋下時回到原狀態；送出成功後整張卡由伺服器版本換入。
    if (form.dataset.submitting !== "true") {
      pendingFocus = "";
      toggle.checked = !toggle.checked;
      row?.classList.remove("is-saving");
    }
  }

  function panelOf(toggle) {
    const id = toggle.getAttribute("aria-controls");
    return id ? document.getElementById(id) : null;
  }

  function closePanel(panel, {restoreFocus = true} = {}) {
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    const row = panel.closest("[data-order-payout-row]");
    row?.classList.remove("is-confirming");
    if (restoreFocus) row?.querySelector("[data-order-payout-toggle]")?.focus();
  }

  function openPanel(toggle) {
    const panel = panelOf(toggle);
    if (!panel) return false;
    document.querySelectorAll("[data-order-payout-panel]:not([hidden])").forEach((other) => {
      if (other !== panel) closePanel(other, {restoreFocus: false});
    });
    panel.hidden = false;
    panel.closest("[data-order-payout-row]")?.classList.add("is-confirming");
    // 預設焦點在「保留」：誤按 Enter 不會取消已給付。
    panel.querySelector("[data-order-payout-keep]")?.focus();
    return true;
  }

  document.addEventListener("change", (event) => {
    const toggle = event.target.closest?.("[data-order-payout-toggle]");
    if (!toggle) return;
    const form = toggle.form;
    if (!toggle.checked && form.hasAttribute("data-order-payout-confirm")) {
      // 取消要先確認：勾選框先維持已給付，確認後才改。
      toggle.checked = true;
      if (openPanel(toggle)) return;
      toggle.checked = false;
    }
    submit(form, toggle);
  });

  document.addEventListener("click", (event) => {
    const keep = event.target.closest?.("[data-order-payout-keep]");
    if (keep) {
      closePanel(keep.closest("[data-order-payout-panel]"));
      return;
    }
    const commit = event.target.closest?.("[data-order-payout-commit]");
    if (!commit) return;
    const panel = commit.closest("[data-order-payout-panel]");
    const toggle = panel?.closest("[data-order-payout-row]")?.querySelector("[data-order-payout-toggle]");
    if (!toggle) return;
    closePanel(panel, {restoreFocus: false});
    toggle.checked = false;
    toggle.focus();
    submit(toggle.form, toggle);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const panel = event.target.closest?.("[data-order-payout-panel]")
      || (event.target.matches?.("[data-order-payout-toggle]") ? panelOf(event.target) : null);
    if (!panel || panel.hidden) return;
    event.preventDefault();
    closePanel(panel);
  });
})();
