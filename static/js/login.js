(() => {
  "use strict";

  const form = document.querySelector("[data-login-form]");
  if (!form) return;

  const password = form.querySelector('input[type="password"], input[name="password"]');
  const toggle = form.querySelector("[data-password-toggle]");
  const caps = form.querySelector("[data-caps-warning]");
  const submit = form.querySelector("[data-login-submit]");

  // 顯示／隱藏密碼：切換後保留游標位置，方便繼續輸入。
  toggle?.addEventListener("click", () => {
    if (!password) return;
    const showing = password.type === "text";
    password.type = showing ? "password" : "text";
    toggle.textContent = showing ? "顯示" : "隱藏";
    toggle.setAttribute("aria-pressed", showing ? "false" : "true");
    toggle.setAttribute("aria-label", showing ? "顯示密碼" : "隱藏密碼");
    password.focus({ preventScroll: true });
  });
  toggle?.setAttribute("aria-label", "顯示密碼");

  // 大寫鎖定提示，避免密碼大小寫輸入錯誤。
  const updateCaps = (event) => {
    if (!caps || typeof event.getModifierState !== "function") return;
    caps.hidden = !event.getModifierState("CapsLock");
  };
  password?.addEventListener("keydown", updateCaps);
  password?.addEventListener("keyup", updateCaps);
  password?.addEventListener("blur", () => { if (caps) caps.hidden = true; });

  // 送出後顯示登入中，防止重複送出；返回上一頁時恢復。
  form.addEventListener("submit", () => {
    if (!submit) return;
    submit.disabled = true;
    submit.setAttribute("aria-busy", "true");
    submit.textContent = "登入中…";
  });
  window.addEventListener("pageshow", () => {
    if (!submit) return;
    submit.disabled = false;
    submit.removeAttribute("aria-busy");
    submit.textContent = "登入";
  });
})();
