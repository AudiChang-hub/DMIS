// 訂單總覽：側邊列按鈕開啟唯讀面板（每次開啟重新載入，反映剛自動儲存的資料）；
// 點欄位右側「複製」、區塊「複製本區」或「複製全部」放進剪貼簿；搜尋框即時篩選欄位。完整頁面共用同一支。
(() => {
  const dialog = document.querySelector("[data-order-overview-dialog]");
  const body = dialog?.querySelector("[data-overview-body]");
  let lastTrigger = null;
  let loading = null;
  let ownsHistory = false;
  const phone = window.matchMedia("(max-width: 860px)");

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

  // T-307 備註便條紙：內容放不下（被截斷）時才顯示「看全文」；寬度改變時重新判斷。
  const fitNote = (note) => {
    const more = note?.querySelector("[data-overview-note-more]");
    const text = note?.querySelector("[data-overview-note-text]");
    if (!more || !text) return;
    // line-clamp 會連 scrollHeight 一起截掉：暫時拿掉截斷量全文高度，再跟顯示高度比。
    const shown = text.clientHeight;
    text.style.display = "block";
    text.style.webkitLineClamp = "none";
    const full = text.scrollHeight;
    text.style.display = "";
    text.style.webkitLineClamp = "";
    const clipped = full > shown + 1;
    more.hidden = !clipped;
    if (!clipped) more.open = false;
  };
  const fitNotes = () => document.querySelectorAll("[data-overview-note]").forEach(fitNote);
  window.addEventListener("resize", fitNotes);
  document.fonts?.ready.then(fitNotes);
  fitNotes();

  // 「看全文」浮層：Esc 或點外面收起（Esc 先收浮層，不關掉整個總覽）。
  let swallowCancel = false;
  const closeNoteMore = (except) => {
    let closed = false;
    document.querySelectorAll("[data-overview-note-more][open]").forEach((more) => {
      if (more === except) return;
      more.open = false;
      closed = true;
    });
    return closed;
  };
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = document.querySelector("[data-overview-note-more][open]");
    if (!open) return;
    closeNoteMore();
    open.querySelector("summary")?.focus({ preventScroll: true });
    event.preventDefault();
    event.stopPropagation();
    swallowCancel = true;
    window.setTimeout(() => { swallowCancel = false; }, 0);
  }, true);
  document.addEventListener("click", (event) => {
    closeNoteMore(event.target.closest?.("[data-overview-note-more]"));
  });

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
    // 備註便條紙在標題區：符合就標亮，不隱藏。
    const note = (root.closest("dialog") || document).querySelector("[data-overview-note]");
    if (note) {
      const match = terms.length > 0 && terms.every((term) => `備註 ${note.dataset.copy}`.toLowerCase().includes(term));
      note.classList.toggle("is-match", match);
      if (match) shown += 1;
    }
    root.querySelector("[data-overview-empty]").hidden = shown > 0;
    root.classList.toggle("is-filtering", terms.length > 0);
  });

  // 區塊跳轉（跳轉按鈕與重點摘要四格）：在面板內捲動，不改網址。
  document.addEventListener("click", (event) => {
    const jump = event.target.closest("[data-overview-jump], [data-overview-glance]");
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

  // T-307：便條紙在片段裡，載入後搬到面板標題區（姓名與「複製全部」之間）；載入中先放同尺寸的空位，標題區不跳動。
  const head = dialog.querySelector(".order-overview-dialog__head");
  const placeNote = (note) => {
    head?.querySelector("[data-overview-note]")?.remove();
    if (!note || !head) return;
    head.insertBefore(note, head.querySelector(".order-overview-dialog__actions"));
    fitNote(note);
  };
  const notePlaceholder = () => {
    const note = document.createElement("div");
    note.className = "order-overview-note is-loading";
    note.setAttribute("aria-hidden", "true");
    note.dataset.overviewNote = "";
    note.dataset.copy = "";
    return note;
  };

  const load = async (url) => {
    body.setAttribute("aria-busy", "true");
    placeNote(notePlaceholder());
    body.innerHTML = '<div class="order-overview-dialog__loading" role="status"><span></span><span></span><span></span><p>正在整理訂單資料…</p></div>';
    const separator = url.includes("?") ? "&" : "?";
    try {
      const response = await fetch(`${url}${separator}fragment=1`, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" });
      if (!response.ok) throw new Error(String(response.status));
      body.innerHTML = await response.text();
      placeNote(body.querySelector("[data-overview-note]"));
      body.querySelector("[data-overview-search]")?.focus({ preventScroll: true });
    } catch (error) {
      placeNote(null);
      body.innerHTML = '<div class="order-overview-dialog__error" role="alert"><p>訂單總覽載入失敗，請檢查網路後再試一次。</p><button type="button" class="button ghost small" data-overview-retry>重新載入</button></div>';
    } finally {
      body.setAttribute("aria-busy", "false");
    }
  };

  const open = (trigger) => {
    lastTrigger = trigger;
    const url = trigger.dataset.orderOverviewOpen;
    // T-256：全部訂單頁同一個面板開不同訂單，標題、單號與「新分頁開啟」跟著點的那一列換。
    const title = dialog.querySelector("[data-overview-dialog-title]");
    if (title) title.textContent = trigger.dataset.overviewTitle || "";
    const meta = dialog.querySelector("[data-overview-dialog-meta]");
    if (meta) meta.textContent = trigger.dataset.overviewMeta || "";
    const page = dialog.querySelector("[data-overview-dialog-page]");
    if (page) page.href = url;
    if (!dialog.open) {
      dialog.showModal();
      // T-267：手機版總覽是全螢幕，返回手勢／返回鍵要關掉總覽、不離開頁面：開啟時多推一筆同網址的歷史。
      if (phone.matches) {
        history.pushState({ ...(history.state || {}), orderOverview: true }, "", location.href);
        ownsHistory = true;
      }
    }
    document.documentElement.classList.add("has-overview-open");
    loading = load(url);
    dialog.dataset.url = url;
  };
  const close = () => {
    if (!dialog.open) return;
    // 手機版按「← 返回」或 Esc：退回開啟前那一筆歷史，由下面的 popstate 收起面板。
    if (ownsHistory) { history.back(); return; }
    dialog.classList.add("is-closing");
    const finish = () => {
      dialog.classList.remove("is-closing");
      dialog.close();
    };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) finish();
    else window.setTimeout(finish, 180);
  };

  // 捕獲階段先處理：這次返回只是關總覽，不讓列表分頁（order-tabs.js）等其他 popstate 重新載入頁面。
  window.addEventListener("popstate", (event) => {
    if (!ownsHistory || !dialog.open) return;
    ownsHistory = false;
    event.stopImmediatePropagation();
    close();
  }, true);

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
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); if (!swallowCancel) close(); });
  dialog.addEventListener("close", () => {
    if (ownsHistory) { ownsHistory = false; history.back(); }  // 不是經由返回關掉的，也要收回多推的那一筆
    document.documentElement.classList.remove("has-overview-open");
    lastTrigger?.focus({ preventScroll: true });
  });
  // 快捷鍵 O：在訂單頁任何地方（非輸入中）開啟總覽。
  document.addEventListener("keydown", (event) => {
    if (event.key.toLowerCase() !== "o" || event.ctrlKey || event.metaKey || event.altKey || dialog.open) return;
    if (dialog.dataset.overviewShortcut === "off") return;  // T-256：全部訂單頁有很多張單，不用快捷鍵
    if (event.target.closest?.("input, textarea, select, [contenteditable='true'], dialog")) return;
    // T-250：手機版精簡列與電腦版側欄各有一個入口，取畫面上看得到的那個，關閉後焦點才回得去。
    const triggers = [...document.querySelectorAll("[data-order-overview-open]")];
    const trigger = triggers.find((el) => el.getClientRects().length) || triggers[0];
    if (!trigger) return;
    event.preventDefault();
    open(trigger);
  });
})();
