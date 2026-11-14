/* 訂單頁首便條（使用者 2026-11-13 回饋第 7 頁，T-175）：備註超過三行才出現「展開全文」；
   訂單頁改了備註，自動儲存回應的 hero_note_html 原地換新（workspace-saved 不冒泡，於捕獲階段接收）。 */
(function () {
  "use strict";

  function note() { return document.querySelector("[data-order-hero-note]"); }

  // 收合狀態下文字被截斷才顯示按鈕；展開中維持顯示，才能收回。
  function refresh() {
    const box = note();
    const text = box?.querySelector("[data-hero-note-text]");
    const toggle = box?.querySelector("[data-hero-note-toggle]");
    if (!text || !toggle) return;
    const expanded = box.classList.contains("is-expanded");
    toggle.hidden = !expanded && text.scrollHeight <= text.clientHeight + 1;
  }

  function setExpanded(box, expanded) {
    const toggle = box.querySelector("[data-hero-note-toggle]");
    box.classList.toggle("is-expanded", expanded);
    if (toggle) {
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.textContent = expanded ? "收合" : "展開全文";
    }
    refresh();
  }

  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-hero-note-toggle]");
    const box = toggle?.closest("[data-order-hero-note]");
    if (box) setExpanded(box, !box.classList.contains("is-expanded"));
  });

  document.addEventListener("workspace-saved", (event) => {
    const html = event.detail?.hero_note_html;
    const box = note();
    if (html == null || !box) return;
    const expanded = box.classList.contains("is-expanded");
    box.outerHTML = html;
    const fresh = note();
    if (fresh && expanded) setExpanded(fresh, true);
    refresh();
  }, true);

  document.addEventListener("inplace:updated", refresh);
  window.addEventListener("resize", refresh, {passive: true});
  if (document.fonts?.ready) document.fonts.ready.then(refresh);
  refresh();
})();
