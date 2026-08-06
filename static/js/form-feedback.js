(() => {
  const controlsSelector = "input:not([type='hidden']), select, textarea";
  const pendingInvalidForms = new WeakSet();

  function fieldLabel(input) {
    const explicit = input.id
      ? document.querySelector(`label[for="${CSS.escape(input.id)}"]`)
      : null;
    return (explicit?.textContent || input.closest(".field")?.querySelector("label")?.textContent || input.name || "必填資料")
      .replace("必填", "")
      .trim();
  }

  function errorMessage(input) {
    const label = fieldLabel(input);
    if (input.validity.valueMissing) return `請填寫「${label}」。`;
    if (input.validity.typeMismatch) return `「${label}」格式不正確，請重新確認。`;
    if (input.validity.patternMismatch) return `「${label}」內容格式不符合要求。`;
    if (input.validity.rangeUnderflow || input.validity.rangeOverflow) return `「${label}」超出可填寫範圍。`;
    if (input.validity.tooLong || input.validity.tooShort) return `「${label}」長度不符合要求。`;
    if (input.validity.badInput) return `「${label}」不是可使用的內容。`;
    return input.validationMessage || `請確認「${label}」。`;
  }

  function showToast(message) {
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

  function isVisible(element) {
    return Boolean(element && (element.offsetParent !== null || element.getClientRects().length));
  }

  function invalidItems(form) {
    const controls = [...form.querySelectorAll(controlsSelector)]
      .filter((control) => !control.validity.valid && !control.disabled);
    const items = controls
      .filter(isVisible)
      .map((control) => ({control, target: control, message: errorMessage(control)}));
    const hiddenIdentityControls = controls.filter((control) => (
      !isVisible(control)
      && control.closest("[data-ocr-confirmation-fields][hidden]")
    ));

    if (hiddenIdentityControls.length) {
      const status = form.querySelector("#ocr-status");
      const state = status?.dataset.state;
      const message = state === "processing"
        ? "請等待證件辨識完成，再核對車主資料。"
        : state === "review" || state === "existing"
          ? "請核對證件辨識結果，並完成車主資料確認。"
          : "請先上傳證件正反面，完成辨識後核對車主資料。";
      items.unshift({
        control: hiddenIdentityControls[0],
        target: isVisible(status) ? status : form.querySelector("#owner"),
        message,
      });
    }
    return {controls, items};
  }

  function focusControl(target) {
    if (!target) return;
    const closedDetails = target.closest("details:not([open])");
    if (closedDetails) closedDetails.open = true;
    target.scrollIntoView({behavior: "smooth", block: "center"});
    if (typeof target.focus === "function" && target.matches(controlsSelector + ", button, a, [tabindex]")) {
      window.setTimeout(() => target.focus({preventScroll: true}), 260);
    }
  }

  function renderErrorSummary(form, result) {
    form.querySelector(":scope > [data-form-error-summary]")?.remove();
    if (!result.items.length) return;

    result.controls.forEach((control) => control.setAttribute("aria-invalid", "true"));
    const summary = document.createElement("section");
    summary.className = "form-error-summary";
    summary.dataset.formErrorSummary = "1";
    summary.setAttribute("role", "alert");
    summary.setAttribute("tabindex", "-1");
    const heading = document.createElement("strong");
    heading.textContent = `還有 ${result.items.length} 個地方需要確認`;
    const hint = document.createElement("p");
    hint.textContent = "點選下列項目，系統會帶你到需要修正的位置。";
    const list = document.createElement("ul");

    result.items.forEach(({target, message}) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = message;
      button.addEventListener("click", () => focusControl(target));
      item.append(button);
      list.append(item);
    });
    summary.append(heading, hint, list);
    form.prepend(summary);
    summary.focus({preventScroll: true});
    summary.scrollIntoView({behavior: "smooth", block: "center"});
    showToast(`目前無法送出：還有 ${result.items.length} 個地方需要確認。`);
  }

  function connectDescriptions() {
    document.querySelectorAll(controlsSelector).forEach((control) => {
      if (!control.id) return;
      const ids = new Set((control.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
      if (document.getElementById(`${control.id}_help`)) ids.add(`${control.id}_help`);
      if (document.getElementById(`${control.id}_errors`)) {
        ids.add(`${control.id}_errors`);
        control.setAttribute("aria-invalid", "true");
      }
      if (ids.size) control.setAttribute("aria-describedby", [...ids].join(" "));
    });
  }

  function lockSubmittingForm(form, submitter) {
    if (form.dataset.allowMultipleSubmit === "true") return true;
    if (form.dataset.submitting === "true") return false;
    form.dataset.submitting = "true";
    form.setAttribute("aria-busy", "true");
    const button = submitter || form.querySelector("[type='submit']");
    if (button) {
      button.classList.add("is-submitting");
      button.setAttribute("aria-disabled", "true");
      button.dataset.originalLabel = button.textContent.trim();
      button.textContent = "處理中…";
    }
    return true;
  }

  function unlockSubmittingForms() {
    document.querySelectorAll("form[data-submitting='true']").forEach((form) => {
      form.dataset.submitting = "false";
      form.removeAttribute("aria-busy");
      form.querySelectorAll(".is-submitting").forEach((button) => {
        button.classList.remove("is-submitting");
        button.removeAttribute("aria-disabled");
        if (button.dataset.originalLabel) button.textContent = button.dataset.originalLabel;
      });
    });
  }

  document.addEventListener("invalid", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) && !(input instanceof HTMLSelectElement) && !(input instanceof HTMLTextAreaElement)) return;
    event.preventDefault();
    const form = input.form;
    if (!form || pendingInvalidForms.has(form)) return;
    pendingInvalidForms.add(form);
    window.setTimeout(() => {
      pendingInvalidForms.delete(form);
      renderErrorSummary(form, invalidItems(form));
    }, 0);
  }, true);

  document.addEventListener("input", (event) => {
    const control = event.target;
    if (!(control instanceof HTMLInputElement) && !(control instanceof HTMLSelectElement) && !(control instanceof HTMLTextAreaElement)) return;
    if (control.validity.valid) control.removeAttribute("aria-invalid");
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const confirmation = event.submitter?.dataset.confirm || form.dataset.confirm;
    if (confirmation && !window.confirm(confirmation)) {
      event.preventDefault();
      return;
    }
    if (event.defaultPrevented) return;
    if (!lockSubmittingForm(form, event.submitter)) {
      event.preventDefault();
      showToast("資料正在處理，請不要重複送出。");
    }
  });

  window.addEventListener("pageshow", unlockSubmittingForms);
  connectDescriptions();
})();
