(() => {
  const form = document.querySelector("[data-sheet-form]");
  const stage = document.querySelector("[data-sheet-stage]");
  const frame = document.querySelector("[data-sheet-frame]");
  const sheet = document.querySelector("[data-dealer-sheet]");
  if (!stage || !frame || !sheet) return;

  const mobileQuery = window.matchMedia("(max-width: 720px)");
  const moneyFormatter = new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 });

  const digitsOnly = (value) => String(value || "").replace(/[^0-9]/g, "");
  const formatMoney = (control) => {
    const digits = digitsOnly(control.value);
    control.value = digits ? moneyFormatter.format(Number(digits)) : "";
  };

  const growTextarea = (control) => {
    control.style.height = "auto";
    control.style.height = `${Math.max(control.scrollHeight, 20)}px`;
  };

  let frameRequest = 0;
  const fitSheet = () => {
    cancelAnimationFrame(frameRequest);
    frameRequest = requestAnimationFrame(() => {
      if (!mobileQuery.matches) {
        sheet.style.transform = "";
        frame.style.width = "";
        frame.style.height = "";
        return;
      }
      const available = Math.max(stage.clientWidth - 16, 280);
      const scale = Math.min(1, available / sheet.offsetWidth);
      sheet.style.transform = `scale(${scale})`;
      frame.style.width = `${sheet.offsetWidth * scale}px`;
      frame.style.height = `${sheet.scrollHeight * scale}px`;
    });
  };

  const syncSectionVisibility = () => {
    sheet.querySelectorAll("[data-sheet-section]").forEach((section) => {
      section.hidden = !section.querySelector("tr[data-sheet-item]:not([hidden])");
    });
    fitSheet();
  };

  sheet.querySelectorAll("[data-auto-grow]").forEach((control) => {
    growTextarea(control);
    control.addEventListener("input", () => {
      growTextarea(control);
      fitSheet();
    });
  });
  sheet.querySelectorAll("[data-money-input]").forEach((control) => {
    formatMoney(control);
    control.addEventListener("focus", () => {
      control.value = digitsOnly(control.value);
      control.select();
    });
    control.addEventListener("blur", () => formatMoney(control));
    control.addEventListener("input", () => {
      control.value = digitsOnly(control.value);
    });
  });

  document.querySelectorAll("[data-item-visibility]").forEach((control) => {
    control.addEventListener("change", () => {
      const row = sheet.querySelector(`[data-sheet-item="${control.dataset.itemVisibility}"]`);
      if (row) row.hidden = !control.checked;
      syncSectionVisibility();
    });
  });

  const logoInput = document.querySelector("[data-logo-input]");
  if (logoInput) {
    logoInput.addEventListener("change", () => {
      const file = logoInput.files && logoInput.files[0];
      if (!file) return;
      let preview = sheet.querySelector("[data-logo-preview]");
      if (!preview) {
        preview = document.createElement("img");
        preview.dataset.logoPreview = "";
        sheet.querySelector("[data-logo-fallback]")?.replaceWith(preview);
      }
      preview.src = URL.createObjectURL(file);
      preview.onload = () => fitSheet();
    });
  }

  const mobileEditor = document.querySelector("[data-mobile-sheet-editor]");
  const mobileEditorTitle = mobileEditor?.querySelector("[data-mobile-editor-title]");
  const mobileEditorControl = mobileEditor?.querySelector("[data-mobile-editor-control]");
  let mobileOriginals = [];

  const cloneControl = (original, labelText) => {
    const label = document.createElement("label");
    label.textContent = labelText;
    const clone = original.cloneNode(true);
    clone.removeAttribute("name");
    clone.removeAttribute("id");
    clone.removeAttribute("data-sheet-field");
    clone.value = original.value;
    const sync = () => {
      original.value = clone.value;
      original.dispatchEvent(new Event("input", { bubbles: true }));
      if (original.matches("textarea")) growTextarea(original);
      fitSheet();
    };
    clone.addEventListener("input", sync);
    clone.addEventListener("change", sync);
    label.appendChild(clone);
    mobileEditorControl.appendChild(label);
    mobileOriginals.push(original);
    return clone;
  };

  const closeMobileEditor = () => {
    mobileOriginals.forEach((control) => {
      if (control.matches("[data-money-input]")) formatMoney(control);
    });
    mobileOriginals = [];
    if (mobileEditor) mobileEditor.hidden = true;
    fitSheet();
  };

  const openMobileEditor = (source) => {
    if (!mobileEditor || !mobileEditorControl) return;
    mobileEditorControl.replaceChildren();
    mobileOriginals = [];
    mobileEditorTitle.textContent = source.getAttribute("aria-label") || "編輯欄位";
    const installmentCell = source.closest(".dealer-sheet__installment-cell");
    if (installmentCell && source.name?.endsWith("-amount")) {
      cloneControl(source, "每期金額");
      const company = installmentCell.querySelector("select");
      const openingFee = installmentCell.querySelector('input[name$="-opening-fee"]');
      if (company) cloneControl(company, "分期公司");
      if (openingFee) cloneControl(openingFee, "開辦費");
    } else {
      cloneControl(source, source.getAttribute("aria-label") || "內容");
    }
    mobileEditor.hidden = false;
    mobileEditorControl.querySelector("input, textarea, select")?.focus();
  };

  if (form && mobileEditor) {
    sheet.addEventListener("click", (event) => {
      if (!mobileQuery.matches) return;
      const source = event.target.closest("[data-sheet-field]");
      if (!source) return;
      event.preventDefault();
      event.stopPropagation();
      openMobileEditor(source);
    }, true);
    mobileEditor.querySelector("[data-mobile-editor-close]")?.addEventListener("click", closeMobileEditor);
  }

  document.addEventListener("click", (event) => {
    sheet.querySelectorAll(".dealer-sheet__term-settings[open]").forEach((details) => {
      if (!details.contains(event.target)) details.removeAttribute("open");
    });
  });

  mobileQuery.addEventListener("change", () => {
    closeMobileEditor();
    fitSheet();
  });
  new ResizeObserver(fitSheet).observe(stage);
  syncSectionVisibility();
})();
