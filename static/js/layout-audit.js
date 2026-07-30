(() => {
  const isVisible = element => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return (
      style.display !== "none"
      && style.visibility !== "hidden"
      && rect.width > 0
      && rect.height > 0
    );
  };

  const describe = element => (
    element.id
      ? `#${element.id}`
      : `.${[...element.classList].join(".")}` || element.tagName.toLowerCase()
  );

  function auditLayout() {
    const issues = [];
    const containers = document.querySelectorAll([
      "main",
      ".hero-row",
      ".metric-grid",
      ".dashboard-columns",
      ".detail-grid",
      ".form-grid",
      ".accessory-row",
      ".other-fee-row",
      ".order-tab-panel:not([hidden])",
      ".section-block",
      ".card",
      ".mobile-submit",
    ].join(","));

    containers.forEach(container => {
      if (!isVisible(container)) return;
      const children = [...container.children].filter(child => {
        if (!isVisible(child)) return false;
        return !["absolute", "fixed"].includes(getComputedStyle(child).position);
      });
      children.forEach((first, index) => {
        const firstRect = first.getBoundingClientRect();
        children.slice(index + 1).forEach(second => {
          const secondRect = second.getBoundingClientRect();
          const width = Math.min(firstRect.right, secondRect.right)
            - Math.max(firstRect.left, secondRect.left);
          const height = Math.min(firstRect.bottom, secondRect.bottom)
            - Math.max(firstRect.top, secondRect.top);
          if (width > 2 && height > 2) {
            issues.push(
              `${describe(first)} 與 ${describe(second)} 重疊 ${Math.round(width)}×${Math.round(height)}px`,
            );
          }
        });
      });
    });

    const viewportWidth = document.documentElement.clientWidth;
    document.querySelectorAll(
      "main input, main select, main textarea, main button, main .card, main .section-block, main .action-card",
    ).forEach(element => {
      if (!isVisible(element) || element.closest(".order-work-tabs")) return;
      const rect = element.getBoundingClientRect();
      if (rect.left < -2 || rect.right > viewportWidth + 2) {
        issues.push(`${describe(element)} 超出畫面左右邊界`);
      }
    });

    const submitBar = document.querySelector(".mobile-submit");
    const mobileNav = document.querySelector(".mobile-nav");
    if (submitBar && mobileNav && isVisible(submitBar) && isVisible(mobileNav)) {
      const submitRect = submitBar.getBoundingClientRect();
      const navRect = mobileNav.getBoundingClientRect();
      const overlap = Math.min(submitRect.bottom, navRect.bottom)
        - Math.max(submitRect.top, navRect.top);
      if (overlap > 2) {
        issues.push(`手機操作列與底部導覽重疊 ${Math.round(overlap)}px`);
      }
    }

    document.documentElement.dataset.uiLayoutIssues = String(issues.length);
    window.__uiLayoutAudit = {issues, viewport: `${innerWidth}x${innerHeight}`};
    if (issues.length) {
      console.error("[UI Layout Audit]", issues);
    } else {
      console.info("[UI Layout Audit] 未發現重疊或水平溢出");
    }
    return window.__uiLayoutAudit;
  }

  window.runUILayoutAudit = auditLayout;
  if (new URLSearchParams(location.search).get("ui_audit") === "1") {
    requestAnimationFrame(() => requestAnimationFrame(auditLayout));
  }
})();
