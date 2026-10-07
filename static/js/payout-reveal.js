(() => {
  const panel = document.querySelector("[data-payout-summary]");
  if (!panel) return;
  const button = panel.querySelector("[data-payout-reveal]");
  const output = panel.querySelector("[data-payout-account]");
  if (!button || !output) return;
  const masked = output.dataset.masked || "";
  button.addEventListener("click", async () => {
    if (button.getAttribute("aria-pressed") === "true") {
      output.textContent = masked;
      button.textContent = "顯示完整帳號";
      button.setAttribute("aria-pressed", "false");
      return;
    }
    const value = await window.dmisRevealMasked({
      url: panel.dataset.revealUrl,
      csrf: panel.dataset.csrf,
      hint: "輸入你自己的登入密碼，才會顯示完整匯款帳戶；查看會留下紀錄。",
    });
    if (value === null) return;
    output.textContent = value || "尚未登記";
    button.textContent = "隱藏帳號";
    button.setAttribute("aria-pressed", "true");
  });
})();
