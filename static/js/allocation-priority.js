(() => {
  "use strict";

  // 車輛庫存列表：優先配車開關以背景送出，失敗時保留原狀態。
  const updateToggle = (form, enabled, source) => {
    const button = form.querySelector("button[role='switch']");
    const stateInput = form.querySelector("input[name='priority']");
    const label = form.querySelector("[data-priority-label]");
    const sourceTag = form.querySelector("[data-priority-source]");
    if (!button || !stateInput) return;
    stateInput.value = enabled ? "0" : "1";
    button.classList.toggle("is-active", enabled);
    button.setAttribute("aria-checked", enabled ? "true" : "false");
    if (label) label.textContent = enabled ? "優先" : "一般";
    if (sourceTag && source) {
      sourceTag.textContent = source;
      sourceTag.classList.toggle("is-manual", source === "人工");
      sourceTag.title = source === "人工" ? "人員手動設定" : "依出廠年月自動判斷";
    }
  };

  const submitToggle = async (form) => {
    const button = form.querySelector("button[role='switch']");
    if (!button || button.disabled) return;
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
        throw new Error(payload.message || "無法更新優先配車，請稍後再試。");
      }
      updateToggle(form, Boolean(payload.priority), payload.source);
    } catch (error) {
      window.alert(error.name === "AbortError"
        ? "更新等候逾時，已保留原本狀態，請再試一次。"
        : (error.message || "無法更新優先配車，請稍後再試。"));
    } finally {
      window.clearTimeout(timeoutId);
      button.disabled = false;
      button.removeAttribute("aria-busy");
      form.classList.remove("is-updating");
    }
  };

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches("[data-inventory-priority-toggle]")) return;
    event.preventDefault();
    submitToggle(form);
  });

  // 訂單配車：有優先配車卻選了其他車時提醒填寫原因（不強制）。
  document.querySelectorAll("[data-allocation-priority-form]").forEach((form) => {
    const select = form.querySelector("select[name='vehicle']");
    const hint = form.querySelector("[data-allocation-priority-hint]");
    if (!select || !hint) return;
    const sync = () => {
      const option = select.selectedOptions[0];
      hint.hidden = !option || !option.value || option.dataset.allocationPriority === "true";
    };
    select.addEventListener("change", sync);
    sync();
  });
})();
