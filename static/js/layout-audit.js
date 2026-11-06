(() => {
  const isInsideClosedDetails = element => {
    let ancestor = element.parentElement;
    while (ancestor) {
      if (ancestor.matches("details:not([open])")) {
        const summary = ancestor.querySelector(":scope > summary");
        if (!summary || !summary.contains(element)) return true;
      }
      ancestor = ancestor.parentElement;
    }
    return false;
  };

  const isVisible = element => {
    if (element.hidden || isInsideClosedDetails(element)) return false;
    if (typeof element.checkVisibility === "function" && !element.checkVisibility()) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return (
      style.display !== "none"
      && style.visibility !== "hidden"
      && rect.width > 0
      && rect.height > 0
    );
  };

  const getContainingHorizontalScrollport = element => {
    let ancestor = element.parentElement;
    while (ancestor && ancestor !== document.body) {
      const overflowX = getComputedStyle(ancestor).overflowX;
      if (
        ["auto", "scroll"].includes(overflowX)
        && ancestor.scrollWidth > ancestor.clientWidth + 1
      ) {
        return ancestor;
      }
      ancestor = ancestor.parentElement;
    }
    return null;
  };

  const describe = element => (
    element.id
      ? `#${element.id}`
      : element.classList.length
        ? `.${[...element.classList].join(".")}`
        : element.tagName.toLowerCase()
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
        const scrollport = getContainingHorizontalScrollport(element);
        if (scrollport) {
          const scrollportRect = scrollport.getBoundingClientRect();
          if (scrollportRect.left >= -2 && scrollportRect.right <= viewportWidth + 2) return;
        }
        issues.push(`${describe(element)} 超出畫面左右邊界`);
      }
    });

    // 整頁水平捲動（UAT U-07）：上面只檢查表單與卡片，價格等文字元素超出時抓不到。
    // 手機版面視窗會跟著被撐寬，固定定位的底部導覽也一起變寬，所以只列最內層、非固定定位的超出元素。
    const pageOverflow = document.documentElement.scrollWidth - viewportWidth;
    if (pageOverflow > 1) {
      const culprits = [...document.body.querySelectorAll("*")].filter(element => {
        if (!isVisible(element) || getComputedStyle(element).position === "fixed") return false;
        if (element.closest(".mobile-nav")) return false;
        if (element.getBoundingClientRect().right <= viewportWidth + 1) return false;
        if (getContainingHorizontalScrollport(element)) return false;
        return ![...element.children].some(child => (
          isVisible(child) && child.getBoundingClientRect().right > viewportWidth + 1
        ));
      });
      const locate = element => {
        if (element.id || element.classList.length) return describe(element);
        const owner = element.parentElement?.closest("[id], [class]");
        return owner ? `${describe(owner)} ${describe(element)}` : describe(element);
      };
      const names = [...new Set(culprits.map(locate))].slice(0, 5);
      issues.push(
        `頁面水平溢出 ${Math.round(pageOverflow)}px（scrollWidth ${document.documentElement.scrollWidth}）${names.length ? `：${names.join("、")}` : ""}`,
      );
    }

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
