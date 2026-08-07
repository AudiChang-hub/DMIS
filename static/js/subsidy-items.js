document.addEventListener("DOMContentLoaded", () => {
  const section = document.querySelector("[data-subsidy-items]");
  if (!section) return;
  const subsidyForm = document.querySelector("[data-subsidy-form]");
  const subsidyToggle = subsidyForm?.querySelector("[name='is_trade_in_subsidy']");
  const toggleMessage = subsidyForm?.querySelector("[data-subsidy-toggle-message]");
  const revisionInput = subsidyForm?.querySelector("[name='_order_revision']");
  const stageStatus = document.querySelector("[data-subsidy-stage-status]");
  const completion = document.querySelector("[data-subsidy-completion]");
  const uploadControls = [...document.querySelectorAll("[data-subsidy-upload-control]")];
  const saveDock = subsidyForm?.querySelector("[data-subsidy-save-dock]");
  const saveButton = subsidyForm?.querySelector("[data-subsidy-save-button]");
  const saveTitle = subsidyForm?.querySelector("[data-subsidy-save-title]");
  const saveDescription = subsidyForm?.querySelector("[data-subsidy-save-description]");
  let initialFormState = "";
  let formIsDirty = false;
  let formIsSubmitting = false;

  function currentFormState() {
    if (!subsidyForm) return "";
    return JSON.stringify(
      [...subsidyForm.elements]
        .filter(field => {
          if (!field.name || field.disabled) return false;
          if (["submit", "button", "file"].includes(field.type)) return false;
          return ![
            "csrfmiddlewaretoken",
            "_order_revision",
            "is_trade_in_subsidy",
          ].includes(field.name);
        })
        .map(field => [
          field.name,
          ["checkbox", "radio"].includes(field.type) ? field.checked : field.value,
        ])
    );
  }

  function refreshDirtyState() {
    if (!subsidyForm || !saveDock) return;
    formIsDirty = currentFormState() !== initialFormState;
    saveDock.classList.toggle("is-saved", !formIsDirty);
    saveDock.classList.toggle("is-dirty", formIsDirty);
    if (saveTitle) {
      saveTitle.textContent = formIsDirty ? "補助資料尚未儲存" : "補助資料已儲存";
    }
    if (saveDescription) {
      saveDescription.textContent = formIsDirty
        ? "儲存後會同步更新尾款，並留下修改人員與異動紀錄。"
        : "修改舊車資料或補助項目後，即可在這裡儲存。";
    }
    if (saveButton) {
      saveButton.disabled = !formIsDirty;
      saveButton.textContent = formIsDirty ? "儲存補助變更" : "資料已儲存";
    }
  }

  function setUploadControls(enabled) {
    uploadControls.forEach(control => {
      control.hidden = !enabled;
    });
    document.querySelectorAll("[data-subsidy-document-row]").forEach(row => {
      const required = enabled && row.dataset.requiredWhenEnabled === "true";
      const requiredBadge = row.querySelector("[data-subsidy-required-badge]");
      const optionalBadge = row.querySelector("[data-subsidy-optional-badge]");
      if (requiredBadge) requiredBadge.hidden = !required;
      if (optionalBadge) optionalBadge.hidden = required;
    });
  }

  function setCompletionState(enabled) {
    if (stageStatus) {
      stageStatus.textContent = enabled ? "辦理中" : "未申請";
      stageStatus.classList.remove("done");
    }
    if (!completion) return;
    completion.classList.add("has-missing");
    completion.classList.remove("is-ready");
    const title = completion.querySelector("strong");
    const description = completion.querySelector("p");
    if (title) title.textContent = enabled ? "補助資料尚待補齊" : "目前未啟用補助申請";
    if (description) {
      description.textContent = enabled
        ? "可立即上傳文件；舊車資料與補助項目填妥後，再儲存補助資料。"
        : "已上傳的文件仍會保留；再次啟用後可繼續補齊資料。";
    }
  }

  async function persistSubsidyToggle() {
    if (!subsidyForm || !subsidyToggle || !revisionInput) return;
    const previousEnabled = subsidyForm.dataset.wasEnabled === "true";
    const enabled = subsidyToggle.checked;
    if (!enabled && previousEnabled && subsidyForm.dataset.hasDocuments === "true") {
      const confirmed = window.confirm("關閉補助申請後，既有文件仍會保留，但上傳按鈕會暫時隱藏。確定關閉嗎？");
      if (!confirmed) {
        subsidyToggle.checked = previousEnabled;
        return;
      }
    }

    subsidyToggle.disabled = true;
    subsidyToggle.closest("label")?.setAttribute("aria-busy", "true");
    if (toggleMessage) toggleMessage.textContent = enabled ? "正在啟用補助申請…" : "正在關閉補助申請…";
    const body = new URLSearchParams({
      enabled: enabled ? "1" : "0",
      _order_revision: revisionInput.value,
    });
    try {
      const response = await fetch(subsidyForm.dataset.subsidyToggleUrl, {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": subsidyForm.querySelector("[name='csrfmiddlewaretoken']").value,
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        body,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "補助狀態未能儲存，請稍後再試。");
      }
      subsidyForm.dataset.wasEnabled = payload.enabled ? "true" : "false";
      subsidyForm.classList.remove("has-toggle-error");
      revisionInput.value = String(payload.revision);
      subsidyToggle.checked = payload.enabled;
      setUploadControls(payload.enabled);
      setCompletionState(payload.enabled);
      if (toggleMessage) toggleMessage.textContent = payload.message;
    } catch (error) {
      subsidyToggle.checked = previousEnabled;
      setUploadControls(previousEnabled);
      subsidyForm.classList.add("has-toggle-error");
      if (toggleMessage) toggleMessage.textContent = error.message;
    } finally {
      subsidyToggle.disabled = false;
      subsidyToggle.closest("label")?.removeAttribute("aria-busy");
    }
  }

  if (subsidyToggle) {
    setUploadControls(subsidyForm.dataset.wasEnabled === "true");
    subsidyToggle.addEventListener("change", persistSubsidyToggle);
  }

  if (subsidyForm && saveDock) {
    initialFormState = currentFormState();
    refreshDirtyState();
    subsidyForm.addEventListener("input", refreshDirtyState);
    subsidyForm.addEventListener("change", refreshDirtyState);
    subsidyForm.addEventListener("submit", () => {
      formIsSubmitting = true;
      if (saveButton) {
        saveButton.disabled = true;
        saveButton.textContent = "正在儲存…";
      }
    });
    window.addEventListener("beforeunload", event => {
      if (!formIsDirty || formIsSubmitting) return;
      event.preventDefault();
      event.returnValue = "";
    });
  }

  const list = section.querySelector("[data-form-list]");
  const template = section.querySelector("[data-empty-form]");
  const total = section.querySelector("input[name$='-TOTAL_FORMS']");
  section.querySelector("[data-add-form]")?.addEventListener("click", () => {
    const index = Number(total.value);
    const fragment = template.content.cloneNode(true);
    fragment.querySelectorAll("[name],[id],[for]").forEach(element => {
      for (const attribute of ["name", "id", "for"]) {
        if (element.hasAttribute(attribute)) {
          element.setAttribute(attribute, element.getAttribute(attribute).replaceAll("__prefix__", String(index)));
        }
      }
    });
    list.append(fragment);
    total.value = index + 1;
    refreshDirtyState();
  });
  list.addEventListener("change", event => {
    if (!event.target.matches("input[name$='-DELETE']")) return;
    event.target.closest("[data-form-row]")?.classList.toggle("is-deleted", event.target.checked);
    refreshDirtyState();
  });
});
