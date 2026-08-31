(() => {
  "use strict";

  const toggleForms = (resource, pk) => Array.from(
    document.querySelectorAll("[data-active-quick-toggle]")
  ).filter((form) => (
    form.dataset.activeResource === resource && form.dataset.activePk === String(pk)
  ));

  const updateControl = (form, enabled) => {
    const button = form.querySelector("button[role='switch']");
    const stateInput = form.querySelector("input[name='active']");
    const label = button?.querySelector(".source-active-toggle__label");
    if (!button || !stateInput || !label) return;
    const itemName = form.dataset.activeName || "此項目";
    stateInput.value = enabled ? "0" : "1";
    button.classList.toggle("is-active", enabled);
    button.setAttribute("aria-checked", enabled ? "true" : "false");
    button.setAttribute("aria-label", `${enabled ? "停用" : "啟用"}${itemName}`);
    button.title = `點擊${enabled ? "停用" : "啟用"}`;
    label.textContent = enabled
      ? (form.dataset.enabledLabel || "啟用中")
      : (form.dataset.disabledLabel || "已停用");
    form.closest("tr, article")?.classList.toggle("is-inactive", !enabled);
  };

  const submitToggle = async (form) => {
    const button = form.querySelector("button[role='switch']");
    const stateInput = form.querySelector("input[name='active']");
    if (!button || !stateInput || button.disabled) return;
    const previousEnabled = stateInput.value === "0";
    if (previousEnabled && form.dataset.confirmOff) {
      if (!window.confirm(form.dataset.confirmOff)) return;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 12000);
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    form.classList.add("is-updating");
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || "無法更新使用狀態，請稍後再試。");
      }
      toggleForms(payload.resource || form.dataset.activeResource, payload.pk || form.dataset.activePk)
        .forEach((relatedForm) => updateControl(relatedForm, Boolean(payload.active)));
      window.dispatchEvent(new CustomEvent("activequicktoggle:changed", { detail: payload }));
    } catch (error) {
      updateControl(form, previousEnabled);
      const message = error.name === "AbortError"
        ? "更新等候逾時，已恢復原本狀態，請再試一次。"
        : (error.message || "無法更新使用狀態，請稍後再試。");
      window.alert(message);
    } finally {
      window.clearTimeout(timeoutId);
      button.disabled = false;
      button.removeAttribute("aria-busy");
      form.classList.remove("is-updating");
    }
  };

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches("[data-active-quick-toggle]")) return;
    event.preventDefault();
    submitToggle(form);
  });
})();
