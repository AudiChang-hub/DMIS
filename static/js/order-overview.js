// 訂單總覽：側邊列按鈕開啟唯讀面板（每次開啟重新載入，反映剛自動儲存的資料）；
// 點欄位右側「複製」、區塊「複製本區」或「複製全部」放進剪貼簿；搜尋框即時篩選欄位。完整頁面共用同一支。
(() => {
  const dialog = document.querySelector("[data-order-overview-dialog]");
  const body = dialog?.querySelector("[data-overview-body]");
  let lastTrigger = null;
  let loading = null;

  const statusFor = (node) => (node.closest("dialog") || document).querySelector("[data-overview-status]");
  const announce = (node, message) => {
    const status = statusFor(node);
    if (!status) return;
    status.textContent = "";
    window.setTimeout(() => { status.textContent = message; }, 30);
  };

  const fallbackCopy = (text) => {
    // 非 HTTPS 或瀏覽器拒絕剪貼簿權限時改用選取複製。
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;top:0;left:0;opacity:0;pointer-events:none";
    (dialog?.open ? dialog : document.body).append(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (error) { ok = false; }
    area.remove();
    return ok;
  };
  const copyText = async (text) => {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      try { await navigator.clipboard.writeText(text); return true; } catch (error) { /* 改用備援 */ }
    }
    return fallbackCopy(text);
  };

  const flash = (button, message) => {
    const label = button.querySelector(".order-overview__copy-text") || button;
    if (!button.dataset.label) button.dataset.label = label.textContent;
    label.textContent = message;
    button.classList.add("is-copied");
    window.clearTimeout(Number(button.dataset.timer || 0));
    button.dataset.timer = String(window.setTimeout(() => {
      label.textContent = button.dataset.label;
      button.classList.remove("is-copied");
    }, 1600));
  };

  const visibleRows = (section) => [...section.querySelectorAll("[data-overview-row]")].filter((row) => !row.hidden && row.dataset.copy);
  const sectionText = (section) => {
    const title = section.querySelector("h3")?.firstChild?.textContent.trim() || "";
    const table = section.querySelector("[data-overview-table]");
    if (table) {
      const head = [...table.querySelectorAll("thead th")].map((cell) => cell.textContent.trim()).join("\t");
      return [title, head, ...visibleRows(section).map((row) => row.dataset.copy)].join("\n");
    }
    return [title, ...visibleRows(section).map((row) => `${row.dataset.label}：${row.dataset.copy.replace(/\n/g, "、")}`)].join("\n");
  };

  const plainText = (scope) => {
    const data = scope.querySelector("#order-overview-text");
    try { return data ? JSON.parse(data.textContent) : ""; } catch (error) { return ""; }
  };

  document.addEventListener("click", async (event) => {
    const single = event.target.closest("[data-overview-copy]");
    const section = event.target.closest("[data-overview-copy-section]");
    const all = event.target.closest("[data-overview-copy-all]");
    const button = single || section || all;
    if (!button) return;
    let text = "";
    let what = "";
    if (single) {
      const row = single.closest("[data-overview-row]");
      text = row.dataset.copy;
      what = row.dataset.label;
    } else if (section) {
      const card = section.closest("[data-overview-section]");
      text = sectionText(card);
      what = card.querySelector("h3")?.firstChild?.textContent.trim() || "本區";
    } else {
      const scope = all.closest("dialog") || document;
      text = plainText(scope);
      what = "整張訂單";
    }
    if (!text) { announce(button, "內容還在載入，請稍候再試"); return; }
    const ok = await copyText(text);
    flash(button, ok ? "已複製" : "無法複製");
    announce(button, ok ? `已複製${what}` : "瀏覽器不允許複製，請直接選取文字");
  });

  // 搜尋：比對欄位名稱與內容；沒有符合的區塊整塊隱藏。
  document.addEventListener("input", (event) => {
    const input = event.target.closest("[data-overview-search]");
    if (!input) return;
    const root = input.closest("[data-order-overview]");
    const terms = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    root.querySelectorAll("[data-overview-section]").forEach((card) => {
      const title = (card.querySelector("h3")?.textContent || "").toLowerCase();
      let any = false;
      card.querySelectorAll("[data-overview-row]").forEach((row) => {
        const haystack = `${title} ${row.textContent}`.toLowerCase();
        const match = terms.every((term) => haystack.includes(term));
        row.hidden = !match;
        if (match) any = true;
      });
      card.hidden = !any;
      if (any) shown += 1;
    });
    root.querySelector("[data-overview-empty]").hidden = shown > 0;
    root.classList.toggle("is-filtering", terms.length > 0);
  });

  // 區塊跳轉：在面板內捲動，不改網址。
  document.addEventListener("click", (event) => {
    const jump = event.target.closest("[data-overview-jump]");
    if (!jump) return;
    const target = document.getElementById(jump.getAttribute("href").slice(1));
    if (!target) return;
    event.preventDefault();
    target.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start" });
    target.classList.remove("is-target");
    void target.offsetWidth;
    target.classList.add("is-target");
  });

  if (!dialog) return;

  const load = async (url) => {
    body.setAttribute("aria-busy", "true");
    body.innerHTML = '<div class="order-overview-dialog__loading" role="status"><span></span><span></span><span></span><p>正在整理訂單資料…</p></div>';
    const separator = url.includes("?") ? "&" : "?";
    try {
      const response = await fetch(`${url}${separator}fragment=1`, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" });
      if (!response.ok) throw new Error(String(response.status));
      body.innerHTML = await response.text();
      body.querySelector("[data-overview-search]")?.focus({ preventScroll: true });
    } catch (error) {
      body.innerHTML = '<div class="order-overview-dialog__error" role="alert"><p>訂單總覽載入失敗，請檢查網路後再試一次。</p><button type="button" class="button ghost small" data-overview-retry>重新載入</button></div>';
    } finally {
      body.setAttribute("aria-busy", "false");
    }
  };

  const open = (trigger) => {
    lastTrigger = trigger;
    const url = trigger.dataset.orderOverviewOpen;
    if (!dialog.open) dialog.showModal();
    document.documentElement.classList.add("has-overview-open");
    loading = load(url);
    dialog.dataset.url = url;
  };
  const close = () => {
    if (!dialog.open) return;
    dialog.classList.add("is-closing");
    const finish = () => {
      dialog.classList.remove("is-closing");
      dialog.close();
    };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) finish();
    else window.setTimeout(finish, 180);
  };

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-order-overview-open]");
    if (!trigger || event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    open(trigger);
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog || event.target.closest("[data-overview-close]")) close();
    if (event.target.closest("[data-overview-retry]")) loading = load(dialog.dataset.url);
  });
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  dialog.addEventListener("close", () => {
    document.documentElement.classList.remove("has-overview-open");
    lastTrigger?.focus({ preventScroll: true });
  });
  // 快捷鍵 O：在訂單頁任何地方（非輸入中）開啟總覽。
  document.addEventListener("keydown", (event) => {
    if (event.key.toLowerCase() !== "o" || event.ctrlKey || event.metaKey || event.altKey || dialog.open) return;
    if (event.target.closest?.("input, textarea, select, [contenteditable='true'], dialog")) return;
    const trigger = document.querySelector("[data-order-overview-open]");
    if (!trigger) return;
    event.preventDefault();
    open(trigger);
  });
})();
