/* 車行傭金／獎金給付（T-150）：勾選即登記、備註離開欄位即儲存；台數獎金結算先開確認卡（T-203）。
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

  // 每列勾選、備註的 csrf 與 next 整頁共用一份（T-281 h）：送出時照原本的順序放在最前面，伺服器收到的欄位與值和以前相同；
  // 沒有 JavaScript 時這兩個欄位在各列的 noscript 裡，整頁送出照舊。
  document.addEventListener("formdata", (event) => {
    const form = event.target;
    const shared = document.getElementById("payout-shared");
    if (!form?.matches?.("form.payout-item__toggle, form[data-payout-note]") || !shared) return;
    // 原地更新換入的區塊是 DOMParser 解析的（不執行腳本），noscript 裡的 csrf、next 會變成真的欄位：一律以共用的為準，不重複送。
    const all = Array.from(event.formData.entries());
    const own = all.filter(([name]) => name !== "csrfmiddlewaretoken" && name !== "next");
    new Set(all.map(([name]) => name)).forEach((name) => event.formData.delete(name));
    event.formData.append("csrfmiddlewaretoken", shared.elements.csrfmiddlewaretoken.value);
    event.formData.append("next", shared.elements.next.value);
    own.forEach(([name, value]) => event.formData.append(name, value));
  }, true);

  // 台數獎金結算（T-203）：「結算」先開確認卡，按「確認結算」才送出；Esc、先不要、點背景都是取消。
  page.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-settle-open]");
    if (opener) {
      document.getElementById(opener.dataset.settleOpen)?.showModal();
      return;
    }
    if (event.target.closest("[data-settle-close]")) {
      event.target.closest("dialog")?.close();
      return;
    }
    if (event.target.matches?.("[data-settle-dialog]")) event.target.close();
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
