// T-239：確認、忽略、補圖後帶著 #official-<id> 回來，瞬間停在下一款卡片並把焦點移過去。
// 全站 html 是 smooth 捲動，原生錨點在載入時不可靠，跟機種清單一樣由 JS 定位。
(() => {
  const match = /^#official-\d+$/.test(window.location.hash) && document.querySelector(window.location.hash);
  if (!match) return;
  window.setTimeout(() => {
    match.scrollIntoView({ behavior: "instant", block: "start" });
    match.setAttribute("tabindex", "-1");
    match.focus({ preventScroll: true });
  }, 0);
})();
