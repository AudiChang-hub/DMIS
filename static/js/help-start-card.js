/* 首頁新手卡片（T-201 b）：關閉後記在這台裝置的 localStorage；讀寫失敗（私密模式、封鎖儲存）時照常顯示，關閉只對這次有效。 */
(() => {
  const card = document.querySelector("[data-help-start-card]");
  if (!card) return;
  const KEY = "dmis.helpStartCard.dismissed";
  let dismissed = false;
  try {
    dismissed = window.localStorage.getItem(KEY) === "1";
  } catch (error) {
    dismissed = false;
  }
  if (dismissed) return;
  card.hidden = false;
  card.querySelector("[data-help-start-close]")?.addEventListener("click", () => {
    try {
      window.localStorage.setItem(KEY, "1");
    } catch (error) {
      /* 存不了就只關這一次 */
    }
    card.hidden = true;
  });
})();
