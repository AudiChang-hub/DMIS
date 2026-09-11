/* 操作權限仍由後端執行；這裡避免僅查看者誤填同頁修改表單。 */
(() => {
  function disableLocalWrites() {
    for (const form of document.querySelectorAll('#main-content form')) {
      if (form.method.toLowerCase() !== 'post') continue;
      const target = new URL(form.action, location.href);
      if (target.origin !== location.origin || target.pathname !== location.pathname) continue;
      for (const control of form.elements) control.disabled = true;
      form.setAttribute('aria-label', '僅查看，無修改權限');
      form.addEventListener('submit', event => event.preventDefault());
    }
  }
  disableLocalWrites();
  window.addEventListener('pageshow', disableLocalWrites);
})();
