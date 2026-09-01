(() => {
  if ("scrollRestoration" in window.history) {
    window.history.scrollRestoration = "auto";
  }

  const parseSameOriginUrl = value => {
    if (!value) return null;
    try {
      const url = new URL(value, window.location.href);
      return url.origin === window.location.origin ? url : null;
    } catch {
      return null;
    }
  };

  const sameOriginReferrer = () => {
    if (!document.referrer) return false;
    const referrer = parseSameOriginUrl(document.referrer);
    return Boolean(referrer && referrer.href !== window.location.href);
  };

  document.querySelectorAll("[data-smart-back]").forEach(control => {
    control.addEventListener("click", event => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (sameOriginReferrer() && window.history.length > 1) {
        event.preventDefault();
        window.history.back();
        return;
      }
      const fallback = control.getAttribute("href") || control.dataset.fallbackUrl;
      const fallbackUrl = parseSameOriginUrl(fallback);
      if (fallbackUrl) {
        event.preventDefault();
        window.location.assign(fallbackUrl.href);
      }
    });
  });

  document.querySelectorAll("[data-current-page-label]").forEach(label => {
    if (label.textContent.trim()) {
      label.hidden = false;
      return;
    }
    const heading = document.querySelector("main h1");
    if (!heading) return;
    label.textContent = heading.textContent.trim();
    label.hidden = !label.textContent;
  });

  const mobileMenu = document.querySelector(".mobile-data-menu");
  if (mobileMenu) {
    document.addEventListener("click", event => {
      if (mobileMenu.open && !mobileMenu.contains(event.target)) {
        mobileMenu.open = false;
      }
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && mobileMenu.open) {
        mobileMenu.open = false;
        mobileMenu.querySelector("summary")?.focus();
      }
    });
  }

  const shortcutDialog = document.querySelector("[data-mobile-shortcuts-dialog]");
  if (shortcutDialog) {
    const shortcutForm = shortcutDialog.querySelector("form");
    const shortcutSelects = [...shortcutDialog.querySelectorAll('select[name="shortcut"]')];
    document.querySelectorAll("[data-mobile-shortcuts-open]").forEach(button => {
      button.addEventListener("click", () => {
        if (mobileMenu) mobileMenu.open = false;
        shortcutDialog.showModal();
      });
    });
    shortcutDialog.querySelectorAll("[data-mobile-shortcuts-close]").forEach(button => {
      button.addEventListener("click", () => shortcutDialog.close());
    });
    shortcutDialog.addEventListener("click", event => {
      if (event.target === shortcutDialog) shortcutDialog.close();
    });
    shortcutSelects.forEach(select => {
      select.addEventListener("change", () => {
        shortcutSelects.forEach(item => item.setCustomValidity(""));
      });
    });
    shortcutForm?.addEventListener("submit", event => {
      shortcutSelects.forEach(select => select.setCustomValidity(""));
      const selected = shortcutSelects.filter(select => select.value);
      if (!selected.length) {
        event.preventDefault();
        shortcutSelects[0].setCustomValidity("請至少保留一個快速前往功能。");
        shortcutSelects[0].reportValidity();
        return;
      }
      const duplicate = selected.find((select, index) => (
        selected.findIndex(item => item.value === select.value) !== index
      ));
      if (duplicate) {
        event.preventDefault();
        duplicate.setCustomValidity("同一個功能不能重複設定。");
        duplicate.reportValidity();
      }
    });
  }
})();
