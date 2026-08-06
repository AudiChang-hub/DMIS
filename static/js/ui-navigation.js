(() => {
  const sameOriginReferrer = () => {
    if (!document.referrer) return false;
    try {
      return new URL(document.referrer).origin === window.location.origin;
    } catch {
      return false;
    }
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
      if (fallback) {
        event.preventDefault();
        window.location.assign(fallback);
      }
    });
  });
})();
