// 單張訂單的身分證影本頁（T-208）：備註改了就重新產生預覽（和列印同一份 PDF），看得到自動縮字的結果。
// 點證件調整裁切交給 form-print-id-copy.js（同一個表單的 data-preview-url）。
(() => {
  "use strict";
  const form = document.querySelector("form[data-id-copy-form]");
  if (!form) return;
  const desk = document.querySelector(".id-copy-desk");
  const target = document.querySelector("[data-preview-content]");
  const status = form.querySelector("[data-preview-summary]");
  const note = form.querySelector("[data-id-copy-note]");
  const count = form.querySelector("[data-note-count]");
  let timer = 0;
  let version = 0;

  async function refresh() {
    const mine = ++version;
    desk.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(form.dataset.previewUrl, {
        method: "POST", body: new FormData(form), credentials: "same-origin",
        headers: {"X-Requested-With": "XMLHttpRequest"},
      });
      const html = await response.text();
      if (mine !== version) return;
      if (!response.ok) throw new Error("preview");
      target.innerHTML = html;  // 同站伺服器產生的預覽片段（套表列印同一份）
      status.textContent = "";
    } catch (_) {
      if (mine === version) status.textContent = "預覽產生失敗，請稍後再試；列印不受影響。";
    } finally {
      if (mine === version) desk.setAttribute("aria-busy", "false");
    }
  }

  const updateCount = () => { count.textContent = `${note.value.length} / ${note.maxLength}`; };
  note.addEventListener("input", () => {
    updateCount();
    clearTimeout(timer);
    timer = setTimeout(refresh, 600);
  });
  form.querySelector("[data-note-reset]").addEventListener("click", () => {
    note.value = note.defaultValue;
    updateCount();
    clearTimeout(timer);
    refresh();
    note.focus();
  });
  refresh();
})();
