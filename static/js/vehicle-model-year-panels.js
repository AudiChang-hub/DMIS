(() => {
  let activeTrigger = null;

  const closePanel = (panel) => {
    if (!panel) return;
    if (typeof panel.close === "function") panel.close();
    else panel.removeAttribute("open");
  };

  document.querySelectorAll("[data-open-year-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      const panel = document.getElementById(button.dataset.openYearPanel || "");
      if (!panel) return;
      activeTrigger = button;
      if (typeof panel.showModal === "function") panel.showModal();
      else panel.setAttribute("open", "");
      panel.querySelector(".vehicle-year-card.is-displayed")?.scrollIntoView({ block: "nearest" });
      panel.querySelector("[data-close-year-panel]")?.focus();
    });
  });

  document.querySelectorAll("[data-year-panel]").forEach((panel) => {
    panel.querySelectorAll("[data-close-year-panel]").forEach((button) => {
      button.addEventListener("click", () => closePanel(panel));
    });
    panel.addEventListener("click", (event) => {
      if (event.target === panel) closePanel(panel);
    });
    panel.addEventListener("close", () => {
      activeTrigger?.focus();
      activeTrigger = null;
    });
  });
})();
