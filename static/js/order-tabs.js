// 全部訂單頁籤：點了只替換下方列表區，不整頁重新載入，畫面停在原位（使用者 2026-10-12）。
// 失敗時退回一般連結；網址同步更新，可用上一頁／重新整理。
(() => {
  const region = document.querySelector("[data-order-results]");
  if (!region || typeof fetch !== "function" || typeof DOMParser !== "function") return;

  function syncTabInputs(url) {
    const tab = new URL(url, location.href).searchParams.get("tab");
    document.querySelectorAll(".order-filter-bar").forEach(form => {
      let input = form.querySelector('input[name="tab"]');
      if (!tab) { input?.remove(); return; }
      if (!input) {
        input = Object.assign(document.createElement("input"), {type: "hidden", name: "tab"});
        form.prepend(input);
      }
      input.value = tab;
    });
    // 狀態篩選切頁籤時已移除，畫面上的下拉也要跟著清空。
    const status = document.querySelector('.order-filter-bar select[name="status"]');
    if (status && !new URL(url, location.href).searchParams.get("status")) status.value = "";
  }

  async function load(url, {push = true} = {}) {
    region.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(url, {credentials: "same-origin", headers: {"X-Requested-With": "fetch"}});
      if (!response.ok || response.redirected) throw new Error(String(response.status));
      const next = new DOMParser().parseFromString(await response.text(), "text/html").querySelector("[data-order-results]");
      if (!next) throw new Error("missing region");
      region.replaceChildren(...next.childNodes);
      syncTabInputs(url);
      if (push) history.pushState({orderTabs: true}, "", url);
      region.querySelector('.order-scope-tabs [aria-current="page"]')?.focus({preventScroll: true});
    } catch (_error) {
      location.assign(url);
    } finally {
      region.removeAttribute("aria-busy");
    }
  }

  region.addEventListener("click", event => {
    const link = event.target.closest(".order-scope-tabs a[href]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (link.getAttribute("aria-current") === "page") return;
    load(link.href);
  });
  window.addEventListener("popstate", () => load(location.href, {push: false}));
})();
