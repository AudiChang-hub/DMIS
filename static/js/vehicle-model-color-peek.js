// 機種總表的啟用顏色清單：原生 popover 負責開關（點外面或 Esc 關閉），這裡只把面板放在按鈕旁。
// 沒有 JS 時 popover 仍可開關，只是置中顯示。
(() => {
  const panels = document.querySelectorAll(".color-peek__panel[popover]");
  if (!panels.length) return;
  const edge = 12, gap = 6;

  const place = (panel) => {
    const trigger = document.querySelector(`[popovertarget="${panel.id}"]`);
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const width = panel.offsetWidth, height = panel.offsetHeight;
    const below = window.innerHeight - rect.bottom - gap - edge;
    const top = below >= height || below >= rect.top ? rect.bottom + gap : rect.top - gap - height;
    const left = Math.min(Math.max(edge, rect.left), window.innerWidth - width - edge);
    panel.style.top = `${Math.max(edge, top)}px`;
    panel.style.left = `${Math.max(edge, left)}px`;
  };

  panels.forEach((panel) => {
    panel.addEventListener("toggle", (event) => {
      if (event.newState === "open") place(panel);
    });
  });
  // 面板開著時捲動或縮放就關掉，避免與按鈕脫節。
  const closeOpen = () => panels.forEach((panel) => {
    if (panel.matches(":popover-open")) panel.hidePopover();
  });
  window.addEventListener("scroll", closeOpen, { passive: true });
  window.addEventListener("resize", closeOpen);
})();
