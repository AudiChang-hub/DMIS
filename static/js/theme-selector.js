(() => {
  const dialog = document.querySelector("[data-theme-dialog]");
  if (!dialog) return;

  const root = document.documentElement;
  const form = dialog.querySelector("[data-theme-form]");
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  const themeColors = {
    professional: "#18323b",
    "night-blue": "#0a151b",
    system: "#18323b",
    "deep-blue": "#162c4a",
    "graphite-gold": "#2b2e33",
    "bright-indigo": "#252a57",
    "high-contrast": "#0b1f2a",
  };
  let themeBeforePreview = root.dataset.theme || "professional";
  let submitting = false;
  const systemDarkQuery = window.matchMedia?.("(prefers-color-scheme: dark)");

  const effectiveTheme = theme => {
    if (theme !== "system") return theme;
    return systemDarkQuery?.matches ? "night-blue" : "professional";
  };

  const updateThemeMeta = theme => {
    const resolvedTheme = effectiveTheme(theme);
    if (themeMeta && themeColors[resolvedTheme]) {
      themeMeta.content = themeColors[resolvedTheme];
    }
  };

  const updateSelection = theme => {
    root.dataset.theme = theme;
    updateThemeMeta(theme);
    dialog.querySelectorAll("[data-theme-option]").forEach(option => {
      const input = option.querySelector('input[name="theme"]');
      const selected = input?.value === theme;
      option.classList.toggle("is-selected", selected);
      if (input) input.checked = selected;
    });
  };

  const handleSystemThemeChange = () => {
    if (root.dataset.theme === "system") updateThemeMeta("system");
  };

  if (systemDarkQuery?.addEventListener) {
    systemDarkQuery.addEventListener("change", handleSystemThemeChange);
  } else if (systemDarkQuery?.addListener) {
    systemDarkQuery.addListener(handleSystemThemeChange);
  }
  updateThemeMeta(root.dataset.theme || "professional");

  const restoreTheme = () => updateSelection(themeBeforePreview);
  const closeDialog = () => {
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  };

  document.querySelectorAll("[data-theme-open]").forEach(button => {
    button.addEventListener("click", () => {
      themeBeforePreview = root.dataset.theme || "professional";
      submitting = false;
      updateSelection(themeBeforePreview);
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    });
  });

  dialog.querySelectorAll('input[name="theme"]').forEach(input => {
    input.addEventListener("change", () => updateSelection(input.value));
  });

  dialog.querySelector("[data-theme-reset]")?.addEventListener("click", () => {
    updateSelection("professional");
  });

  dialog.querySelectorAll("[data-theme-close]").forEach(button => {
    button.addEventListener("click", () => {
      restoreTheme();
      closeDialog();
    });
  });

  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    const inside = event.clientX >= bounds.left && event.clientX <= bounds.right
      && event.clientY >= bounds.top && event.clientY <= bounds.bottom;
    if (!inside) {
      restoreTheme();
      closeDialog();
    }
  });

  dialog.addEventListener("close", () => {
    if (!submitting) restoreTheme();
  });

  form?.addEventListener("submit", () => {
    submitting = true;
  });
})();
