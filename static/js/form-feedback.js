(() => {
  function fieldLabel(input) {
    const explicit = input.id
      ? document.querySelector(`label[for="${CSS.escape(input.id)}"]`)
      : null;
    return (explicit?.textContent || input.closest(".field")?.querySelector("label")?.textContent || "必填資料")
      .replace("必填", "")
      .trim();
  }

  function showError(message) {
    let container = document.querySelector(".messages");
    if (!container) {
      container = document.createElement("div");
      container.className = "messages";
      container.setAttribute("aria-live", "assertive");
      document.querySelector("main")?.prepend(container);
    }
    let toast = container.querySelector("[data-form-error-toast]");
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "message error";
      toast.dataset.formErrorToast = "1";
      toast.innerHTML = `
        <span class="message-text"></span>
        <button class="message-close" type="button" aria-label="關閉提示">×</button>
      `;
      toast.querySelector("button").addEventListener("click", () => toast.remove());
      container.append(toast);
    }
    toast.querySelector(".message-text").textContent = message;
  }

  document.addEventListener("invalid", event => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)
        && !(input instanceof HTMLSelectElement)
        && !(input instanceof HTMLTextAreaElement)) return;
    const action = input.form?.querySelector('[type="submit"]')?.textContent.trim() || "送出";
    showError(`目前無法${action}：請先填寫「${fieldLabel(input)}」。`);
  }, true);

  document.addEventListener("submit", event => {
    const message = event.target.dataset.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });
})();
