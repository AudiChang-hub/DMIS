(() => {
  // 顯示被遮罩的資料：本人驗證有效（閒置 10 分鐘內）就直接顯示；否則在對話框輸入本人登入密碼。
  // 以 Promise 回傳伺服器給的值，取消則回傳 null。
  let dialog = null;
  let pending = null;

  function post(url, csrf, params) {
    return fetch(url, {
      method: "POST",
      headers: {"X-CSRFToken": csrf, "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json"},
      body: new URLSearchParams(params),
    }).then(async response => ({status: response.status, data: await response.json().catch(() => ({}))}));
  }

  function build() {
    const element = document.createElement("dialog");
    element.className = "theme-dialog masked-reveal-dialog";
    element.setAttribute("aria-labelledby", "masked-reveal-title");
    element.innerHTML = `
      <form novalidate>
        <header class="theme-dialog__header">
          <div><h2 id="masked-reveal-title">輸入密碼以顯示</h2><p data-reveal-hint></p></div>
          <button type="button" class="theme-dialog__close" data-reveal-cancel aria-label="取消">×</button>
        </header>
        <div class="masked-reveal-dialog__body">
          <label>目前登入帳號的密碼
            <input type="password" class="form-control" name="password" autocomplete="current-password" required>
          </label>
          <p class="field-error" role="alert" data-reveal-error hidden></p>
        </div>
        <footer class="theme-dialog__footer">
          <small>密碼只用來確認是你本人，不會被儲存。通過後持續操作不必再輸入，閒置 10 分鐘才會再問。</small>
          <div>
            <button type="button" class="button ghost" data-reveal-cancel>取消</button>
            <button type="submit" class="button primary" data-reveal-submit>顯示</button>
          </div>
        </footer>
      </form>`;
    document.body.appendChild(element);
    element.addEventListener("close", () => {
      if (pending) { pending.resolve(null); pending = null; }
    });
    element.querySelectorAll("[data-reveal-cancel]").forEach(button => button.addEventListener("click", () => element.close()));
    element.querySelector("form").addEventListener("submit", async event => {
      event.preventDefault();
      if (!pending) return;
      const input = element.querySelector("input[name=password]");
      const error = element.querySelector("[data-reveal-error]");
      const submit = element.querySelector("[data-reveal-submit]");
      if (!input.value) { error.textContent = "請輸入你的登入密碼。"; error.hidden = false; input.focus(); return; }
      submit.disabled = true;
      try {
        const {data} = await post(pending.url, pending.csrf, {...pending.params, password: input.value});
        if (!data.ok) {
          error.textContent = data.error || "無法顯示資料。";
          error.hidden = false;
          input.value = "";
          input.focus();
          return;
        }
        const finish = pending;
        pending = null;
        input.value = "";
        element.close();
        finish.resolve(data.value || "");
      } catch (failure) {
        error.textContent = "連線失敗，請稍後再試。";
        error.hidden = false;
      } finally {
        submit.disabled = false;
      }
    });
    return element;
  }

  window.dmisRevealMasked = async ({url, csrf, params = {}, hint = ""}) => {
    // 先不帶密碼試一次：驗證仍有效就直接拿到值。
    try {
      const {status, data} = await post(url, csrf, params);
      if (data.ok) return data.value || "";
      if (!(status === 401 && data.need_password)) {
        window.alert(data.error || "無法顯示資料。");
        return null;
      }
    } catch (failure) {
      window.alert("連線失敗，請稍後再試。");
      return null;
    }
    return new Promise(resolve => {
      dialog = dialog || build();
      if (pending) pending.resolve(null);
      pending = {url, csrf, params, resolve};
      dialog.querySelector("[data-reveal-hint]").textContent = hint;
      const error = dialog.querySelector("[data-reveal-error]");
      error.hidden = true;
      error.textContent = "";
      dialog.querySelector("input[name=password]").value = "";
      dialog.showModal();
      dialog.querySelector("input[name=password]").focus();
    });
  };
})();
