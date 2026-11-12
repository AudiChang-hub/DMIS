/* 車行傭金／獎金給付（T-150）：勾選即登記、備註離開欄位即儲存。
   送出交給 form-feedback.js（取消已給付先確認、防重複送出）與 inplace-regions.js（原地換入、不捲動）；
   沒有 JavaScript 時各列有 noscript 按鈕可整頁送出。 */
(() => {
  "use strict";
  const page = document.querySelector("[data-payout-page]");
  if (!page) return;

  page.addEventListener("change", (event) => {
    const toggle = event.target.closest("[data-payout-toggle]");
    if (!toggle) return;
    const form = toggle.form;
    const wanted = toggle.checked;
    form.closest("[data-payout-item]")?.classList.add("is-saving");
    form.requestSubmit();
    // 取消確認或重複送出被擋下時，勾選框回到原狀態；送出成功後整塊由伺服器版本換入。
    if (form.dataset.submitting !== "true") {
      toggle.checked = !wanted;
      form.closest("[data-payout-item]")?.classList.remove("is-saving");
    }
  });

  // 備註：改完離開欄位（change）就儲存；Enter 也是儲存，不另跳頁。
  page.addEventListener("change", (event) => {
    const input = event.target;
    const form = input.closest?.("[data-payout-note]");
    if (!form || input.name !== "note") return;
    const state = form.querySelector("[data-payout-note-state]");
    if (state) state.textContent = "儲存中…";
    form.requestSubmit();
  });
})();
