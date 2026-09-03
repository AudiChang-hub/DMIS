(() => {
  "use strict";

  const calendar = document.querySelector("[data-holiday-calendar]");
  if (!calendar) return;

  const editor = calendar.querySelector("[data-holiday-editor]");
  const backdrop = calendar.querySelector(".holiday-editor-backdrop");
  const form = calendar.querySelector("[data-holiday-form]");
  const deleteForm = calendar.querySelector("[data-holiday-delete-form]");
  const deleteButton = calendar.querySelector("[data-holiday-delete-button]");
  const idInput = calendar.querySelector("[data-holiday-id-input]");
  const dateInput = form?.elements.namedItem("date");
  const nameInput = form?.elements.namedItem("name");
  const activeInput = form?.elements.namedItem("active");
  const title = calendar.querySelector("[data-holiday-editor-title]");
  const mode = calendar.querySelector("[data-holiday-editor-mode]");
  const sourceRow = calendar.querySelector("[data-holiday-source-row]");
  const sourceLabel = calendar.querySelector("[data-holiday-source-output]");
  const activeHelp = calendar.querySelector("[data-holiday-active-help]");
  const monthPicker = calendar.querySelector("[data-holiday-month-picker]");
  let lastTrigger = null;

  if (!editor || !form || !dateInput || !nameInput || !activeInput) return;

  const readableDate = (isoDate) => {
    const parts = isoDate.split("-");
    if (parts.length !== 3) return "設定排除日期";
    return `${Number(parts[1])} 月 ${Number(parts[2])} 日`;
  };

  const showEditor = () => {
    editor.classList.add("is-open");
    editor.dataset.editorOpen = "true";
    if (backdrop) backdrop.hidden = false;
  };

  const hideEditor = () => {
    editor.classList.remove("is-open");
    editor.dataset.editorOpen = "false";
    if (backdrop) backdrop.hidden = true;
    lastTrigger?.focus({ preventScroll: true });
  };

  const prepareEditor = (trigger) => {
    const existing = Boolean(trigger.dataset.holidayId);
    const isoDate = trigger.dataset.holidayDate || "";
    lastTrigger = trigger;
    idInput.value = trigger.dataset.holidayId || "";
    dateInput.value = isoDate;
    nameInput.value = trigger.dataset.holidayName || "";
    activeInput.checked = existing
      ? trigger.dataset.holidayActive === "true"
      : true;
    if (activeHelp) {
      activeHelp.textContent = trigger.dataset.holidayWeekend === "true"
        ? "週六、週日固定不計；這個開關只調整額外紀錄，不會把週末改成工作日。"
        : "關閉後仍保留紀錄，但不再額外排除；週末仍固定不計。";
    }
    mode.textContent = existing ? "調整日期" : "新增日期";
    title.textContent = readableDate(isoDate);

    if (sourceRow && sourceLabel) {
      sourceRow.hidden = !existing;
      sourceLabel.textContent = trigger.dataset.holidaySourceLabel || "";
    }
    if (deleteForm && deleteButton) {
      deleteForm.hidden = !existing;
      deleteForm.action = trigger.dataset.holidayDeleteUrl || "";
      deleteButton.dataset.confirm = trigger.dataset.holidaySource === "dgpa"
        ? "確定刪除這個官方日期嗎？下次官方同步時會重新建立。"
        : "確定刪除這個日期嗎？";
    }
    showEditor();
  };

  calendar.addEventListener("click", (event) => {
    const day = event.target.closest("[data-holiday-date]");
    if (day) {
      event.preventDefault();
      prepareEditor(day);
      return;
    }

    const createButton = event.target.closest("[data-holiday-create]");
    if (createButton) {
      const currentMonth = monthPicker?.value || "";
      const today = new Date();
      const todayIso = [
        today.getFullYear(),
        String(today.getMonth() + 1).padStart(2, "0"),
        String(today.getDate()).padStart(2, "0"),
      ].join("-");
      const suggestedDate = todayIso.startsWith(`${currentMonth}-`)
        ? todayIso
        : `${currentMonth}-01`;
      prepareEditor({
        dataset: {
          holidayDate: suggestedDate,
          holidayWeekend: String([0, 6].includes(new Date(`${suggestedDate}T12:00:00`).getDay())),
        },
        focus: () => createButton.focus({ preventScroll: true }),
      });
      return;
    }

    if (event.target.closest("[data-holiday-editor-close]")) {
      event.preventDefault();
      hideEditor();
    }
  });

  monthPicker?.addEventListener("change", () => {
    if (!monthPicker.value) return;
    const destination = new URL(window.location.href);
    destination.search = "";
    destination.searchParams.set("month", monthPicker.value);
    window.location.assign(destination);
  });

  window.addEventListener("activequicktoggle:changed", (event) => {
    const payload = event.detail || {};
    if (payload.resource !== "business-holiday") return;
    const day = calendar.querySelector(
      `[data-holiday-id="${CSS.escape(String(payload.pk))}"]`
    );
    if (!day) return;
    const active = Boolean(payload.active);
    day.dataset.holidayActive = active ? "true" : "false";
    day.classList.toggle("is-excluded", active);
    day.classList.toggle("is-inactive", !active);
    const daySource = day.querySelector(".holiday-calendar-day__source");
    if (daySource) {
      daySource.textContent = `${day.dataset.holidaySource === "dgpa" ? "官方" : "人工"}${active ? "" : " · 不排除"}`;
    }
    if (idInput.value === String(payload.pk)) activeInput.checked = active;
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && editor.classList.contains("is-open")) {
      hideEditor();
    }
  });

  if (editor.dataset.editorOpen === "true" && backdrop) {
    backdrop.hidden = false;
  }
})();
