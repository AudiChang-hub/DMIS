(() => {
  const body = document.body;
  const banner = document.getElementById("app-update-banner");
  const icon = document.getElementById("app-update-icon");
  const message = document.getElementById("app-update-message");
  const reloadButton = document.getElementById("app-update-reload");
  const laterButton = document.getElementById("app-update-later");
  const checkButtons = document.querySelectorAll("[data-check-update]");
  const endpoint = body.dataset.versionEndpoint;
  const loadedVersion = body.dataset.appVersion;
  let availableVersion = null;
  let formDirty = false;
  let checking = false;
  let statusTimer = null;

  if (!banner || !endpoint || !loadedVersion) return;

  document.querySelectorAll('form[method="post"]:not(.logout-form)').forEach(form => {
    form.addEventListener("input", () => { formDirty = true; });
    form.addEventListener("change", () => { formDirty = true; });
    form.addEventListener("submit", () => { formDirty = false; });
  });
  document.addEventListener("draft-saved", () => { formDirty = false; });

  function setBannerState(state) {
    const icons = {success: "✓", update: "↻", error: "!"};
    banner.dataset.state = state;
    if (icon) icon.textContent = icons[state] || icons.update;
  }

  function showStatus(text, state = "success") {
    clearTimeout(statusTimer);
    setBannerState(state);
    message.textContent = text;
    reloadButton.hidden = true;
    laterButton.textContent = "關閉";
    banner.hidden = false;
    statusTimer = window.setTimeout(() => { banner.hidden = true; }, 2600);
  }

  function showUpdate(version) {
    clearTimeout(statusTimer);
    setBannerState("update");
    availableVersion = version;
    message.textContent = formDirty
      ? "系統已有新版。你正在填寫資料，請先完成或確認後再更新。"
      : "系統已有新版，可以立即重新載入。";
    reloadButton.hidden = false;
    laterButton.textContent = "稍後";
    banner.hidden = false;
  }

  async function checkVersion(manual = false) {
    if (checking) return;
    checking = true;
    try {
      const separator = endpoint.includes("?") ? "&" : "?";
      const response = await fetch(`${endpoint}${separator}t=${Date.now()}`, {
        cache: "no-store",
        headers: {"Accept": "application/json"},
      });
      if (!response.ok) throw new Error("版本檢查失敗");
      const data = await response.json();
      if (data.version && data.version !== loadedVersion) {
        showUpdate(data.version);
      } else if (manual) {
        showStatus("目前已是最新版本。", "success");
      }
    } catch (error) {
      if (manual) showStatus("暫時無法檢查更新，請稍後再試。", "error");
    } finally {
      checking = false;
    }
  }

  reloadButton.addEventListener("click", () => {
    if (
      formDirty
      && !window.confirm("重新載入會清除尚未送出的資料，確定要更新嗎？")
    ) return;
    const url = new URL(window.location.href);
    url.searchParams.set("_appv", availableVersion || Date.now().toString());
    window.location.replace(url.toString());
  });
  laterButton.addEventListener("click", () => { banner.hidden = true; });
  checkButtons.forEach(button => {
    button.addEventListener("click", () => checkVersion(true));
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkVersion();
  });
  window.addEventListener("pageshow", () => checkVersion());
  window.setInterval(checkVersion, 5 * 60 * 1000);
})();
