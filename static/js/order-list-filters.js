// 全部訂單手機版（T-252，使用者 2026-11-19 選 A）：「更多操作」選單、篩選底部面板、套用中的篩選小標籤。
// 篩選欄位仍是同一張 GET 表單，網址參數與「匯出」帶入目前篩選（T-232）都照舊；電腦版這些按鈕與標籤不顯示，面板以 display: contents 攤開。
(() => {
  const mobile = window.matchMedia("(max-width: 860px)");

  // ---- 更多操作 ----
  const hero = document.querySelector("[data-order-list-hero]");
  const moreToggle = hero?.querySelector("[data-order-more-toggle]");
  const menu = hero?.querySelector("#order-list-actions");
  if (hero && moreToggle && menu) {
    const items = () => [...menu.querySelectorAll("a[href], button")];
    const setOpen = (open, { focus = false } = {}) => {
      hero.classList.toggle("is-actions-open", open);
      moreToggle.setAttribute("aria-expanded", String(open));
      if (open && focus) items()[0]?.focus();
    };
    moreToggle.addEventListener("click", () => setOpen(!hero.classList.contains("is-actions-open"), { focus: true }));
    document.addEventListener("click", (event) => {
      if (hero.classList.contains("is-actions-open") && !hero.contains(event.target)) setOpen(false);
    });
    hero.addEventListener("keydown", (event) => {
      if (!hero.classList.contains("is-actions-open")) return;
      if (event.key === "Escape") { setOpen(false); moreToggle.focus(); return; }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      const list = items();
      const index = list.indexOf(document.activeElement);
      event.preventDefault();
      list[(index + (event.key === "ArrowDown" ? 1 : list.length - 1)) % list.length]?.focus();
    });
    menu.addEventListener("focusout", (event) => {
      if (mobile.matches && !hero.contains(event.relatedTarget)) setOpen(false);
    });
    mobile.addEventListener("change", () => setOpen(false));
  }

  // ---- 篩選面板與小標籤 ----
  const form = document.querySelector("[data-order-filter-form]");
  const sheet = form?.querySelector("[data-order-filter-sheet]");
  const opener = form?.querySelector("[data-order-filter-open]");
  if (!form || !sheet || !opener || typeof sheet.showModal !== "function") return;
  const count = opener.querySelector("[data-order-filter-count]");
  const chips = form.querySelector("[data-order-filter-chips]");
  const NAMES = ["date_from", "date_to", "energy_type", "payment_status", "registered", "status"];
  const field = (name) => sheet.querySelector(`[name="${name}"]`);
  const labelOf = (input) => {
    const label = input.closest("label");
    return [...(label?.childNodes || [])].filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent.trim()).join("") || input.name;
  };
  const valueText = (input) => {
    if (input.tagName === "SELECT") return input.selectedOptions[0]?.text.trim() || "";
    return input.value.replaceAll("-", "/");
  };
  // 以頁面載入時（＝已套用）的值為準；面板裡改了但還沒按「套用」的不算。
  const applied = Object.fromEntries(NAMES.map((name) => [name, field(name)?.value || ""]));
  const active = () => NAMES.filter((name) => applied[name] && field(name));

  const renderChips = () => {
    const names = active();
    count.textContent = names.length ? `（${names.length}）` : "";
    opener.setAttribute("aria-label", names.length ? `篩選，已套用 ${names.length} 項` : "篩選");
    chips.replaceChildren();
    chips.hidden = !names.length;
    names.forEach((name) => {
      const input = field(name);
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "order-filter-chip";
      chip.dataset.clearFilter = name;
      const text = `${labelOf(input)}：${valueText(input)}`;
      chip.setAttribute("aria-label", `移除篩選 ${text}`);
      chip.append(text);
      const x = document.createElement("span");
      x.className = "order-filter-chip__x";
      x.setAttribute("aria-hidden", "true");
      x.textContent = "×";
      chip.append(x);
      chips.append(chip);
    });
    if (names.length) {
      const clear = document.createElement("button");
      clear.type = "button";
      clear.className = "order-filter-chips__clear";
      clear.dataset.clearFilter = "*";
      clear.textContent = "全部清除";
      chips.append(clear);
    }
  };
  const submit = () => (form.requestSubmit ? form.requestSubmit() : form.submit());
  chips.addEventListener("click", (event) => {
    const target = event.target.closest("[data-clear-filter]");
    if (!target) return;
    const names = target.dataset.clearFilter === "*" ? active() : [target.dataset.clearFilter];
    names.forEach((name) => { const input = field(name); if (input) input.value = ""; });
    submit();
  });

  // 打開時記下目前的值；沒按「套用」就關掉，欄位回到原本的值，畫面與網址一致。
  let snapshot = null;
  const open = () => {
    snapshot = Object.fromEntries(NAMES.map((name) => [name, field(name)?.value ?? ""]));
    sheet.showModal();
    document.documentElement.classList.add("has-order-filter-open");
    opener.setAttribute("aria-expanded", "true");
    sheet.querySelector("input:not([type=hidden]), select")?.focus();
  };
  const dismiss = () => {
    if (snapshot) NAMES.forEach((name) => { const input = field(name); if (input) input.value = snapshot[name]; });
    if (sheet.open) sheet.close();
    opener.focus({ preventScroll: true });
  };
  sheet.addEventListener("close", () => {
    document.documentElement.classList.remove("has-order-filter-open");
    opener.setAttribute("aria-expanded", "false");
  });
  opener.setAttribute("aria-expanded", "false");
  opener.addEventListener("click", open);
  sheet.querySelector("[data-order-filter-close]")?.addEventListener("click", dismiss);
  sheet.addEventListener("cancel", (event) => { event.preventDefault(); dismiss(); });
  sheet.addEventListener("click", (event) => { if (event.target === sheet) dismiss(); });
  sheet.querySelector("[data-order-filter-clear]")?.addEventListener("click", () => {
    NAMES.forEach((name) => { const input = field(name); if (input) input.value = ""; });
    sheet.querySelector("input:not([type=hidden]), select")?.focus();
  });
  form.addEventListener("submit", () => { snapshot = null; if (sheet.open) sheet.close(); });
  // 面板開著時，「狀態」改了不要立刻送出（電腦版的下拉仍是選了就查），等按「套用」。
  sheet.addEventListener("change", (event) => { if (sheet.open) event.stopPropagation(); }, true);
  mobile.addEventListener("change", () => { if (!mobile.matches && sheet.open) dismiss(); });
  renderChips();
})();

// 手機版分類頁籤與排序（T-252 擴大範圍，使用者 2026-11-19）：列表區由 order-tabs.js 局部替換，所以一律用事件委派、替換後重新對位。
(() => {
  const region = document.querySelector("[data-order-results]");
  if (!region) return;
  const mobile = window.matchMedia("(max-width: 860px)");

  // 目前分類捲進可視範圍（只橫向捲動頁籤列，不捲動整頁）。
  const revealActiveTab = () => {
    const scroller = region.querySelector(".order-scope-tabs");
    const tab = scroller?.querySelector('[aria-current="page"]');
    if (!scroller || !tab || scroller.scrollWidth <= scroller.clientWidth + 1) return;
    const left = tab.offsetLeft - (scroller.clientWidth - tab.offsetWidth) / 2;
    scroller.scrollTo({ left: Math.max(0, left), behavior: "instant" });
  };

  // 排序面板：按鈕在列表區裡，替換後是新的元素，所以每次都重新找。
  let refocusSort = false;
  const sheetOf = () => region.querySelector("[data-order-sort-sheet]");
  const openerOf = () => region.querySelector("[data-order-sort-open]");
  const links = (sheet) => [...sheet.querySelectorAll(".order-sort-mobile a, a[data-sort-clear], .sort-chip-list a, button")];
  const openSort = () => {
    const sheet = sheetOf();
    if (!sheet || typeof sheet.showModal !== "function") return;
    sheet.showModal();
    document.documentElement.classList.add("has-order-sort-open");
    openerOf()?.setAttribute("aria-expanded", "true");
    (sheet.querySelector(".order-sort-mobile a.is-active") || sheet.querySelector(".order-sort-mobile a"))?.focus();
  };
  const closeSort = (focus) => {
    const sheet = sheetOf();
    if (sheet?.open) sheet.close();
    // close 事件是非同步的；列表若先被替換，事件到不了 document，所以這裡直接解除捲動鎖定。
    document.documentElement.classList.remove("has-order-sort-open");
    if (focus) openerOf()?.focus({ preventScroll: true });
  };
  // 以捕捉階段先關閉面板，再讓 order-sorting.js／order-tabs.js 照原本的方式載入新排序。
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-order-sort-open]")) { openSort(); return; }
    const sheet = event.target.closest("[data-order-sort-sheet]");
    if (!sheet || !sheet.open) return;
    if (event.target === sheet || event.target.closest("[data-order-sort-close]")) { closeSort(true); return; }
    if (event.target.closest("a[href]")) { refocusSort = true; closeSort(false); }
  }, true);
  // dialog 的 close 不會冒泡，用捕捉階段收。
  document.addEventListener("close", (event) => {
    if (!event.target.matches?.("[data-order-sort-sheet]")) return;
    document.documentElement.classList.remove("has-order-sort-open");
    openerOf()?.setAttribute("aria-expanded", "false");
  }, true);
  document.addEventListener("cancel", (event) => {
    if (!event.target.matches?.("[data-order-sort-sheet]")) return;
    event.preventDefault();
    closeSort(true);
  }, true);
  document.addEventListener("keydown", (event) => {
    const sheet = sheetOf();
    if (!sheet?.open || (event.key !== "ArrowDown" && event.key !== "ArrowUp")) return;
    const list = links(sheet);
    const index = list.indexOf(document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    list[(index + (event.key === "ArrowDown" ? 1 : list.length - 1)) % list.length].focus();
  });
  mobile.addEventListener("change", () => { if (!mobile.matches) closeSort(false); });

  new MutationObserver(() => {
    revealActiveTab();
    openerOf()?.setAttribute("aria-expanded", "false");
    if (refocusSort) { refocusSort = false; openerOf()?.focus({ preventScroll: true }); }
  }).observe(region, { childList: true });
  openerOf()?.setAttribute("aria-expanded", "false");
  revealActiveTab();
})();
