// 全部訂單：頁籤、排序、分頁、每頁筆數只替換下方列表區，不整頁重新載入、不跳回頁首（使用者 2026-10-12）。
// 失敗時退回一般連結；網址同步更新，可用上一頁／重新整理。排序連結由 order-sorting.js 算出網址後交給這裡載入。
(() => {
  const region = document.querySelector("[data-order-results]");
  if (!region || typeof fetch !== "function" || typeof DOMParser !== "function") return;

  function syncFilterForm(url) {
    const params = new URL(url, location.href).searchParams;
    document.querySelectorAll(".order-filter-bar").forEach(form => {
      for (const name of ["tab", "sort", "per_page"]) {
        let input = form.querySelector(`input[type="hidden"][name="${name}"]`);
        const value = params.get(name);
        if (!value) { if (name === "tab") input?.remove(); continue; }
        if (!input) {
          input = Object.assign(document.createElement("input"), {type: "hidden", name});
          form.prepend(input);
        }
        input.value = value;
      }
      // 切頁籤時狀態篩選已移除，畫面上的下拉也要跟著清空。
      const status = form.querySelector('select[name="status"]');
      if (status && !params.get("status")) status.value = "";
    });
  }

  async function load(url, {push = true, revealList = false} = {}) {
    region.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(url, {credentials: "same-origin", headers: {"X-Requested-With": "fetch"}});
      if (!response.ok || response.redirected) throw new Error(String(response.status));
      const next = new DOMParser().parseFromString(await response.text(), "text/html").querySelector("[data-order-results]");
      if (!next) throw new Error("missing region");
      region.replaceChildren(...next.childNodes);
      syncFilterForm(url);
      if (push) history.pushState({orderResults: true}, "", url);
      if (revealList) {
        // 換頁時只捲到列表開頭（列表已在畫面上方之外時），不回到頁首。
        // 直接定位（新頁較短時平滑捲動會被頁高縮減打斷），並留出頂部固定選單的高度。
        const summary = region.querySelector(".order-list-summary");
        const header = document.querySelector(".site-header, header");
        const offset = (header && getComputedStyle(header).position.match(/sticky|fixed/) ? header.getBoundingClientRect().height : 0) + 12;
        if (summary && summary.getBoundingClientRect().top < offset) {
          window.scrollTo({top: summary.getBoundingClientRect().top + window.scrollY - offset, behavior: "instant"});
        }
      }
    } catch (_error) {
      location.assign(url);
    } finally {
      region.removeAttribute("aria-busy");
    }
  }

  globalThis.DMISOrderResults = {load};

  region.addEventListener("click", event => {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const tab = event.target.closest(".order-scope-tabs a[href]");
    if (tab) {
      event.preventDefault();
      if (tab.getAttribute("aria-current") !== "page") {
        load(tab.href).then(() => region.querySelector('.order-scope-tabs [aria-current="page"]')?.focus({preventScroll: true}));
      }
      return;
    }
    const page = event.target.closest(".site-pagination a[href]");
    if (page) {
      event.preventDefault();
      load(page.href, {revealList: true});
      return;
    }
    // 排序條件的「提前／延後／移除」；欄位排序與全部清除由 order-sorting.js 處理。
    const chip = event.target.closest(".sort-chip-list a[href]:not([data-order-sort-key])");
    if (chip) {
      event.preventDefault();
      load(chip.href);
    }
  });

  // 列表區內的查詢表單（每頁筆數、跳頁）也改為局部載入。
  region.addEventListener("submit", event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || (form.method || "get").toLowerCase() !== "get") return;
    event.preventDefault();
    const url = new URL(form.getAttribute("action") || location.pathname, location.href);
    url.search = new URLSearchParams(new FormData(form)).toString();
    load(url.toString(), {revealList: form.classList.contains("site-pagination__jump")});
  });

  window.addEventListener("popstate", () => load(location.href, {push: false}));
})();
