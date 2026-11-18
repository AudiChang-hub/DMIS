/* 訂單頁首便條（使用者 2026-11-13 回饋第 7 頁，T-175）：備註超過三行才出現「展開全文」；
   訂單頁改了備註，自動儲存回應的 hero_note_html 原地換新（workspace-saved 不冒泡，於捕獲階段接收）。
   可以改訂單內容的人（T-196，使用者 2026-11-16「這個備註要直接可以在這裡修改」）：便條直接可編輯。
   便條沒有自己的存檔：打字寫進訂單表單的「備註」欄，交給訂單頁既有的自動儲存（驗證、交易、版本號衝突保護、修改紀錄）；
   便條上顯示儲存中／已儲存／尚未儲存，存不進去時保留輸入。 */
(function () {
  "use strict";

  function note() { return document.querySelector("[data-order-hero-note]"); }

  // ---- 唯讀便條：展開全文 ----
  // 收合狀態下文字被截斷才顯示按鈕；展開中維持顯示，才能收回。
  function refresh() {
    const box = note();
    const text = box?.querySelector("[data-hero-note-text]");
    const toggle = box?.querySelector("[data-hero-note-toggle]");
    if (!text || !toggle) return;
    const expanded = box.classList.contains("is-expanded");
    toggle.hidden = !expanded && text.scrollHeight <= text.clientHeight + 1;
  }

  function setExpanded(box, expanded) {
    const toggle = box.querySelector("[data-hero-note-toggle]");
    box.classList.toggle("is-expanded", expanded);
    if (toggle) {
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.textContent = expanded ? "收合" : "展開全文";
    }
    refresh();
  }

  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-hero-note-toggle]");
    const box = toggle?.closest("[data-order-hero-note]");
    if (box) setExpanded(box, !box.classList.contains("is-expanded"));
  });

  // ---- 可編輯便條（T-196）----
  const orderForm = () => document.getElementById("order-form");
  const editable = () => { const box = note(); return box?.hasAttribute("data-hero-note-editable") ? box : null; };
  const input = (box) => box?.querySelector("[data-hero-note-input]");
  // 訂單表單上真正存檔的欄位（同一個 SalesOrder.note）。
  const target = (box) => orderForm()?.elements.namedItem(box?.dataset.heroNoteField || "note") || null;
  let pending = false;      // 便條改過、還沒有存檔結果
  let savedRound = false;   // 這一輪自動儲存是否成功
  let mirroring = false;    // 便條寫入表單欄位時，不回頭同步便條
  let lastSaved = input(editable())?.value ?? "";

  function clock() {
    const now = new Date();
    return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  }

  function setState(box, state, message) {
    if (!box) return;
    box.dataset.state = state;
    const status = box.querySelector("[data-hero-note-status]");
    if (status) status.textContent = message || "";
  }

  function fit(area) {
    if (!area) return;
    area.style.height = "auto";
    // border-box：高度要加上下框線，否則剛好差 2px 而出現捲軸。
    area.style.height = `${area.scrollHeight + area.offsetHeight - area.clientHeight}px`;
  }

  function markEmpty(box) {
    const area = input(box);
    box?.classList.toggle("is-empty", !(area?.value || "").trim());
  }

  // 便條 → 訂單表單：同一欄寫入後觸發 input（排入自動儲存）。
  function mirror(box, commit) {
    const area = input(box);
    const field = target(box);
    if (!area || !field) return;
    if (field.value !== area.value) {
      field.value = area.value;
      mirroring = true;
      field.dispatchEvent(new Event("input", {bubbles: true}));
      mirroring = false;
      pending = true;
      setState(box, "saving", "儲存中…");
    }
    // 離開便條時立刻送出，不等打字的延遲。
    if (commit && pending) field.dispatchEvent(new Event("change", {bubbles: true}));
  }

  // 訂單表單 → 便條：其他地方改了備註（「訂車與配件」的備註欄、自動儲存同步回來的值）。
  function pull(box) {
    const area = input(box);
    const field = target(box);
    if (!area || !field || document.activeElement === area || pending) return;
    if (area.value !== field.value) area.value = field.value;
    lastSaved = area.value;
    markEmpty(box);
    // 沒在編輯便條時高度由 CSS 限制三行（focusout 已清掉 style.height），不需要 fit()。
  }

  // 在「訂車與配件」的備註欄打字時，便條同一個畫面更新週期只同步一次：
  // fit() 要讀 scrollHeight，每個鍵都同步呼叫會強制重排整頁（T-241 量到打字卡頓的主因）。
  let pullFrame = 0;
  function pullSoon(box) {
    if (pullFrame) return;
    pullFrame = requestAnimationFrame(() => { pullFrame = 0; pull(box); });
  }

  document.addEventListener("input", (event) => {
    const box = editable();
    if (!box) return;
    if (event.target === input(box)) {
      markEmpty(box);
      fit(event.target);
      mirror(box, false);
    } else if (!mirroring && event.target === target(box)) {
      pullSoon(box);
    }
  });

  document.addEventListener("focusin", (event) => {
    const box = editable();
    if (box && event.target === input(box)) fit(event.target);
  });

  document.addEventListener("focusout", (event) => {
    const box = editable();
    if (!box || event.target !== input(box)) return;
    mirror(box, true);
    // 收回時恢復三行高度（由 CSS 限制），內容不變。
    event.target.style.height = "";
  });

  document.addEventListener("keydown", (event) => {
    const box = editable();
    const area = input(box);
    if (!box || event.target !== area) return;
    if (event.key === "Escape") {
      // 放棄這次還沒存的修改，回到最後一次存好的內容。
      event.preventDefault();
      area.value = lastSaved;
      markEmpty(box);
      mirror(box, false);
      pending = false;
      setState(box, "idle", "");
      area.blur();
    } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      area.blur();
    }
  });

  // 訂單表單的自動儲存結果（事件不冒泡，於捕獲階段接收）。
  document.addEventListener("workspace-saved", (event) => {
    const box = note();
    if (box?.hasAttribute("data-hero-note-editable")) {
      if (event.target !== orderForm()) return;
      savedRound = true;
      if (pending) {
        pending = false;
        lastSaved = input(box)?.value ?? "";
        setState(box, "saved", `已儲存 ${clock()}`);
      }
      pull(box);
      return;
    }
    // 唯讀便條：照舊用伺服器回傳的版本換新。
    const html = event.detail?.hero_note_html;
    if (html == null || !box) return;
    const expanded = box.classList.contains("is-expanded");
    box.outerHTML = html;
    const fresh = note();
    if (fresh && expanded) setExpanded(fresh, true);
    refresh();
  }, true);

  document.addEventListener("workspace-save-finished", (event) => {
    const box = editable();
    const form = orderForm();
    if (!box || event.target !== form) return;
    if (pending && !savedRound) {
      // 存不進去（驗證、版本衝突、網路）：保留便條上的輸入。被標紅的欄位（例如已完成訂單要先勾的「完成後修正」）
      // 直接點名；其他原因取自訂單表單的狀態列。
      const invalid = form.querySelector('[aria-invalid="true"]');
      const label = (invalid?.labels?.[0]?.textContent || "").replace(/\s+/g, " ").trim();
      const reason = label ? `請先處理「${label}」`
        : (form.querySelector("[data-autosave-status]")?.textContent || "").replace(/^尚未儲存：?/, "").replace(/[。\s]+$/, "").trim();
      setState(box, "error", `尚未儲存${reason ? `：${reason}` : ""}。內容已保留，可修改後再試。`);
    }
    savedRound = false;
  }, true);

  document.addEventListener("inplace:updated", () => {
    refresh();
    const box = editable();
    if (box) { lastSaved = input(box)?.value ?? ""; markEmpty(box); }
  });
  window.addEventListener("resize", refresh, {passive: true});
  if (document.fonts?.ready) document.fonts.ready.then(refresh);
  refresh();
})();
