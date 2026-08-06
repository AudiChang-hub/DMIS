(() => {
  const banner = document.querySelector("[data-connectivity-banner]");
  if (!banner) return;

  function updateStatus() {
    banner.hidden = navigator.onLine;
    document.documentElement.classList.toggle("is-offline", !navigator.onLine);
  }

  window.addEventListener("online", updateStatus);
  window.addEventListener("offline", updateStatus);
  updateStatus();
})();
