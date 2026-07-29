(() => {
  const durations = {
    success: 4000,
    info: 5000,
    warning: 8000,
  };

  document.querySelectorAll("[data-message-toast]").forEach((toast) => {
    const closeButton = toast.querySelector("[data-message-close]");
    const duration = Object.entries(durations).find(([type]) =>
      toast.classList.contains(type)
    )?.[1] ?? (toast.classList.contains("error") ? null : durations.info);
    let remaining = duration;
    let startedAt = 0;
    let timerId = null;
    let dismissed = false;

    function dismiss() {
      if (dismissed) return;
      dismissed = true;
      window.clearTimeout(timerId);
      toast.classList.add("is-dismissing");
      window.setTimeout(() => {
        const container = toast.parentElement;
        toast.remove();
        if (container && !container.children.length) container.remove();
      }, 220);
    }

    function pause() {
      if (!timerId || dismissed) return;
      window.clearTimeout(timerId);
      timerId = null;
      remaining = Math.max(0, remaining - (performance.now() - startedAt));
      toast.classList.add("is-paused");
    }

    function resume() {
      if (duration === null || timerId || dismissed) return;
      toast.classList.remove("is-paused");
      if (remaining <= 0) {
        dismiss();
        return;
      }
      startedAt = performance.now();
      timerId = window.setTimeout(dismiss, remaining);
    }

    closeButton?.addEventListener("click", dismiss);
    toast.addEventListener("mouseenter", pause);
    toast.addEventListener("mouseleave", resume);
    toast.addEventListener("focusin", pause);
    toast.addEventListener("focusout", resume);
    toast.addEventListener("touchstart", pause, {passive: true});
    toast.addEventListener("touchend", resume, {passive: true});

    if (duration !== null) {
      toast.style.setProperty("--message-duration", `${duration}ms`);
      toast.classList.add("is-timed");
      resume();
    }
  });
})();
