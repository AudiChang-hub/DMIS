/* 套表列印：表格勾選 ↔ 列印清單。勾選存在 sessionStorage，換頁、重新搜尋都保留；關閉分頁即清除。 */
(function () {
  const root = document.querySelector("[data-form-print]");
  if (!root) return;
  const KEY = "dmis-form-print-v1";
  const FORMS = ["envelope", "tax_declaration", "receipt", "ev_delivery", "tax_consent"];
  const trayForm = root.querySelector("[data-tray-form]");
  const list = root.querySelector("[data-list]");
  const template = document.querySelector("[data-item-template]");
  const dock = document.querySelector("[data-dock]");

  // state：{ 訂單 pk: { number, name, vehicle, forms: { key: 顯示名稱 }, note, address, seq } }
  let state = {};
  try { state = JSON.parse(sessionStorage.getItem(KEY) || "{}") || {}; } catch (error) { state = {}; }
  let seq = Object.values(state).reduce((max, item) => Math.max(max, item.seq || 0), 0);

  const save = () => {
    try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (error) { /* 無痕模式等情況只保留在畫面上 */ }
  };

  const rowOf = (element) => element.closest("tr[data-order]");

  const entryFor = (row) => {
    const pk = row.dataset.order;
    if (!state[pk]) {
      state[pk] = {
        number: row.dataset.number, name: row.dataset.name, vehicle: row.dataset.vehicle,
        forms: {}, note: row.dataset.note || "", address: row.dataset.address || "", seq: ++seq,
      };
    }
    return state[pk];
  };

  const setForm = (row, input, checked) => {
    const entry = entryFor(row);
    if (checked) entry.forms[input.dataset.form] = input.dataset.label;
    else delete entry.forms[input.dataset.form];
    if (!Object.keys(entry.forms).length) delete state[row.dataset.order];
  };

  const syncRow = (row) => {
    const entry = state[row.dataset.order];
    const inputs = row.querySelectorAll("input[data-form]");
    inputs.forEach((input) => { input.checked = Boolean(entry && entry.forms[input.dataset.form]); });
    const picked = [...inputs].filter((input) => input.checked).length;
    const master = row.querySelector("[data-row-pick]");
    master.checked = picked > 0;
    master.indeterminate = picked > 0 && picked < inputs.length;
    row.classList.toggle("is-picked", picked > 0);
  };

  const render = () => {
    const entries = Object.entries(state).sort((a, b) => a[1].seq - b[1].seq);
    const counts = Object.fromEntries(FORMS.map((key) => [key, 0]));
    list.replaceChildren();
    trayForm.querySelectorAll("input[name='job']").forEach((input) => input.remove());
    entries.forEach(([pk, entry]) => {
      const node = template.content.firstElementChild.cloneNode(true);
      node.dataset.order = pk;
      node.querySelector("[data-item-name]").textContent = entry.name || "（未填車主）";
      node.querySelector("[data-item-meta]").textContent = [entry.number, entry.vehicle].filter(Boolean).join("・");
      node.querySelector("[data-preview-item]").setAttribute("aria-label", `預覽 ${entry.name || entry.number} 的套表`);
      const chips = node.querySelector("[data-item-chips]");
      FORMS.filter((key) => entry.forms[key]).forEach((key) => {
        counts[key] += 1;
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "form-print__chip";
        chip.dataset.removeForm = key;
        chip.setAttribute("aria-label", `不印 ${entry.forms[key]}`);
        chip.innerHTML = `<span></span><i aria-hidden="true">×</i>`;
        chip.querySelector("span").textContent = entry.forms[key];
        chips.append(chip);
        const job = document.createElement("input");
        job.type = "hidden";
        job.name = "job";
        job.value = `${pk}:${key}`;
        trayForm.append(job);
      });
      const receipt = node.querySelector("[data-item-receipt]");
      const note = node.querySelector("[data-item-note]");
      const address = node.querySelector("[data-item-address]");
      receipt.hidden = !entry.forms.receipt;
      note.name = `note_${pk}`;
      address.name = `address_${pk}`;
      note.value = entry.note || "";
      address.value = entry.address || "";
      list.append(node);
    });
    const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
    root.querySelector("[data-total]").textContent = total;
    FORMS.forEach((key) => {
      const paper = root.querySelector(`[data-paper="${key}"]`);
      paper.querySelector("[data-paper-count]").textContent = counts[key];
      paper.classList.toggle("is-active", counts[key] > 0);
    });
    root.querySelector("[data-empty]").hidden = total > 0;
    // 信封出 Word 檔（原稿自訂紙張），聲明書與簽收單出 A4 PDF。
    const envelopes = counts.envelope;
    const a4 = total - envelopes;
    const envelopeButton = trayForm.querySelector("[data-submit-envelope]");
    envelopeButton.disabled = envelopes === 0;
    envelopeButton.textContent = envelopes ? `下載信封 Word 檔（${envelopes} 張）` : "下載信封 Word 檔";
    trayForm.querySelector("[data-submit]").disabled = a4 === 0;
    trayForm.querySelector("[data-submit]").textContent = a4 ? `產生 A4 PDF（${a4} 頁）` : "產生 A4 PDF";
    trayForm.querySelector("[data-clear]").disabled = total === 0;
    const previewButton = trayForm.querySelector("[data-preview-open]");
    previewButton.disabled = total === 0;
    previewButton.querySelector("[data-preview-open-label]").textContent = total ? `預覽 ${total} 份` : "預覽";
    if (dock) {
      dock.hidden = total === 0;
      dock.querySelector("[data-dock-count]").textContent = total;
    }
    root.querySelectorAll("tr[data-order]").forEach(syncRow);
    save();
  };

  // ── 列印預覽（T-118）：用列印清單同一份內容向伺服器要頁面圖；只讀，不寫任何資料。 ──
  const preview = (() => {
    const dialog = document.querySelector("[data-preview-dialog]");
    if (!dialog) return { open() {} };
    const form = dialog.querySelector("[data-preview-form]");
    const desk = dialog.querySelector("[data-preview-desk]");
    const content = dialog.querySelector("[data-preview-content]");
    const rail = dialog.querySelector("[data-preview-rail]");
    const summary = dialog.querySelector("[data-preview-summary]");
    const counter = dialog.querySelector("[data-preview-counter]");
    const zoom = dialog.querySelector("[data-preview-zoom]");
    const printButton = dialog.querySelector("[data-preview-print]");
    const envelopeButton = dialog.querySelector("[data-preview-envelope]");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const FIELD = /^(?:note|address)_(\d+)$/;
    let request = null;
    let trigger = null;
    let pages = [];
    let current = 0;
    let frame = 0;
    let lastCounts = { a4: 0, envelope: 0 };

    // 預覽與列印送出同一份內容：只預覽一張訂單時，按列印也只印那一張。
    const fill = (pk) => {
      form.querySelectorAll("input:not([name='csrfmiddlewaretoken'])").forEach((input) => input.remove());
      const counts = { a4: 0, envelope: 0 };
      for (const [name, value] of new FormData(trayForm)) {
        if (name === "csrfmiddlewaretoken") continue;
        const owner = name === "job" ? String(value).split(":")[0] : (name.match(FIELD) || [])[1];
        if (pk && owner && owner !== pk) continue;
        if (name === "job") counts[String(value).endsWith(":envelope") ? "envelope" : "a4"] += 1;
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = name;
        input.value = value;
        form.append(input);
      }
      return counts;
    };

    const describe = (counts) => [
      counts.a4 ? `A4 ${counts.a4} 頁` : "",
      counts.envelope ? `信封 ${counts.envelope} 張` : "",
    ].filter(Boolean).join("・");

    const skeleton = (counts) => {
      const frag = document.createDocumentFragment();
      [["a4", "A4 PDF", "頁"], ["envelope", "信封 Word 檔", "張"]].forEach(([key, title, unit]) => {
        if (!counts[key]) return;
        const section = document.createElement("section");
        section.className = "print-preview__section is-loading";
        section.innerHTML = `<header class="print-preview__section-head"><h3></h3><span></span></header>`;
        section.querySelector("h3").textContent = title;
        section.querySelector("span").textContent = `${counts[key]} ${unit}`;
        for (let index = 0; index < Math.min(counts[key], 2); index += 1) {
          const sheet = document.createElement("div");
          sheet.className = `print-preview__ghost print-preview__ghost--${key}`;
          sheet.style.setProperty("--i", index);
          sheet.innerHTML = "<i></i><i></i><i></i><i></i>";
          section.append(sheet);
        }
        frag.append(section);
      });
      content.replaceChildren(frag);
    };

    const setCurrent = (index) => {
      current = Math.max(0, Math.min(index, pages.length - 1));
      counter.querySelector("[data-preview-current]").textContent = current + 1;
      rail.querySelectorAll("button").forEach((thumb, i) => {
        thumb.classList.toggle("is-current", i === current);
        if (i === current) thumb.setAttribute("aria-current", "page");
        else thumb.removeAttribute("aria-current");
      });
      // 只捲縮圖列本身，不用 scrollIntoView，免得打斷頁面正在進行的平滑捲動。
      const active = rail.querySelector(".is-current");
      if (active && rail.offsetParent) {
        const top = active.offsetTop - rail.offsetTop;
        if (top < rail.scrollTop) rail.scrollTop = top - 12;
        else if (top + active.offsetHeight > rail.scrollTop + rail.clientHeight) rail.scrollTop = top + active.offsetHeight - rail.clientHeight + 12;
      }
    };

    // 跳頁時以目標頁為準；捲動結束前不依位置重算（最後幾頁可能捲不到頂端）。
    let jumping = 0;
    const goTo = (index) => {
      if (!pages.length) return;
      const next = Math.max(0, Math.min(index, pages.length - 1));
      clearTimeout(jumping);
      jumping = setTimeout(() => { jumping = 0; }, 2000);
      pages[next].scrollIntoView({ block: "start", behavior: reduceMotion.matches ? "instant" : "smooth" });
      setCurrent(next);
    };

    const track = () => {
      if (frame || jumping || !pages.length) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const line = desk.getBoundingClientRect().top + desk.clientHeight * 0.35;
        let best = 0;
        pages.forEach((page, index) => { if (page.getBoundingClientRect().top <= line) best = index; });
        // 捲到底時最後一頁可能停不到上緣，直接算最後一頁。
        if (desk.scrollTop + desk.clientHeight >= desk.scrollHeight - 2) best = pages.length - 1;
        if (best !== current) setCurrent(best);
      });
    };

    const buildRail = () => {
      rail.replaceChildren();
      pages.forEach((page, index) => {
        const thumb = document.createElement("button");
        thumb.type = "button";
        thumb.className = `print-preview__thumb${page.classList.contains("print-preview__page--envelope") ? " is-envelope" : ""}`;
        thumb.setAttribute("aria-label", `第 ${index + 1} 頁：${page.dataset.label}`);
        const image = page.querySelector("img").cloneNode();
        image.alt = "";
        const number = document.createElement("span");
        number.textContent = index + 1;
        thumb.append(image, number);
        thumb.addEventListener("click", () => goTo(index));
        rail.append(thumb);
      });
    };

    const showError = (message) => {
      content.innerHTML = `<div class="print-preview__state is-error" role="alert"><strong>無法預覽</strong><p></p><button class="button ghost" type="button" data-preview-retry>再試一次</button></div>`;
      content.querySelector("p").textContent = message;
      summary.textContent = "預覽失敗";
    };

    const load = async (counts) => {
      request?.abort();
      const controller = new AbortController();
      request = controller;
      desk.setAttribute("aria-busy", "true");
      dialog.classList.add("is-loading");
      counter.hidden = true;
      rail.replaceChildren();
      pages = [];
      skeleton(counts);
      summary.textContent = `${describe(counts)}・產生中…`;
      try {
        const response = await fetch(trayForm.dataset.previewUrl, {
          method: "POST", body: new FormData(form), credentials: "same-origin",
          headers: { "X-Requested-With": "XMLHttpRequest" }, signal: controller.signal,
        });
        const html = await response.text();
        if (!response.ok && !html.includes("print-preview__state")) throw new Error(`HTTP ${response.status}`);
        content.innerHTML = html; // 伺服器範本已跳脫
        pages = [...content.querySelectorAll("[data-page]")];
        if (!pages.length) {
          summary.textContent = "預覽失敗";
          return;
        }
        summary.textContent = describe(counts);
        counter.querySelector("[data-preview-count]").textContent = pages.length;
        counter.hidden = false;
        buildRail();
        desk.scrollTop = 0;
        setCurrent(0);
      } catch (error) {
        if (error.name === "AbortError") return;
        showError("連線中斷或伺服器忙碌，請再試一次。勾選的項目都還在。");
      } finally {
        if (request === controller) {
          desk.setAttribute("aria-busy", "false");
          dialog.classList.remove("is-loading");
        }
      }
    };

    // 窄螢幕兩顆按鈕並排，省略動詞。
    const label = (button, verb, rest) => {
      const span = document.createElement("span");
      span.className = "print-preview__verb";
      span.textContent = verb;
      button.replaceChildren(span, rest);
    };

    const open = (pk, button) => {
      trigger = button;
      lastCounts = fill(pk);
      if (!lastCounts.a4 && !lastCounts.envelope) return;
      printButton.hidden = !lastCounts.a4;
      envelopeButton.hidden = !lastCounts.envelope;
      label(printButton, "開啟\u00a0", `A4 PDF 列印（${lastCounts.a4} 頁）`);
      label(envelopeButton, "下載", `信封 Word 檔（${lastCounts.envelope} 張）`);
      envelopeButton.classList.toggle("primary", !lastCounts.a4);
      envelopeButton.classList.toggle("ghost", Boolean(lastCounts.a4));
      setZoom(false);
      if (!dialog.open) dialog.showModal();
      document.documentElement.classList.add("has-print-preview");
      desk.focus({ preventScroll: true });
      load(lastCounts);
    };

    const close = () => {
      request?.abort();
      if (dialog.open) dialog.close();
    };

    const submit = (url, target) => {
      form.action = url;
      form.target = target;
      form.submit();
    };

    printButton.addEventListener("click", () => submit(trayForm.dataset.pdfUrl, "_blank"));
    envelopeButton.addEventListener("click", () => submit(trayForm.dataset.envelopeUrl, "_self"));
    const setZoom = (zoomed) => {
      dialog.classList.toggle("is-zoomed", zoomed);
      zoom.setAttribute("aria-pressed", String(zoomed));
      zoom.setAttribute("aria-label", zoomed ? "縮回整頁" : "放大檢查");
      zoom.title = zoomed ? "縮回整頁（Z）" : "放大檢查（Z）";
    };
    zoom.addEventListener("click", () => {
      const anchor = pages[current];
      setZoom(!dialog.classList.contains("is-zoomed"));
      anchor?.scrollIntoView({ block: "start", behavior: "instant" });
    });
    desk.addEventListener("scroll", track, { passive: true });
    desk.addEventListener("scrollend", () => {
      if (!jumping) return;
      clearTimeout(jumping);
      jumping = 0;
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog || event.target.closest("[data-preview-close]")) close();
      if (event.target.closest("[data-preview-retry]")) load(lastCounts);
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest("input, textarea, select")) return;
      const key = event.key.toLowerCase();
      const moves = { arrowright: current + 1, j: current + 1, arrowleft: current - 1, k: current - 1, home: 0, end: pages.length - 1 };
      if (key in moves) {
        event.preventDefault();
        goTo(moves[key]);
      } else if (key === "z") {
        event.preventDefault();
        zoom.click();
      }
    });
    dialog.addEventListener("close", () => {
      request?.abort();
      document.documentElement.classList.remove("has-print-preview");
      trigger?.focus({ preventScroll: true });
    });
    // 快捷鍵 P：有勾選時開啟整份預覽。
    document.addEventListener("keydown", (event) => {
      if (event.key.toLowerCase() !== "p" || event.ctrlKey || event.metaKey || event.altKey || dialog.open) return;
      if (event.target.closest?.("input, textarea, select, [contenteditable='true'], dialog")) return;
      const button = trayForm.querySelector("[data-preview-open]");
      if (button.disabled) return;
      event.preventDefault();
      open("", button);
    });
    return { open };
  })();

  root.addEventListener("change", (event) => {
    const input = event.target;
    const row = rowOf(input);
    if (!row) return;
    if (input.matches("[data-row-pick]")) {
      const inputs = [...row.querySelectorAll("input[data-form]")];
      const anyPicked = inputs.some((item) => item.checked);
      inputs.forEach((item) => setForm(row, item, !anyPicked && item.hasAttribute("data-suggested")));
    } else if (input.matches("input[data-form]")) {
      setForm(row, input, input.checked);
    } else {
      return;
    }
    render();
  });

  root.addEventListener("click", (event) => {
    const column = event.target.closest("[data-column]");
    if (column) {
      const key = column.dataset.column;
      const inputs = [...root.querySelectorAll(`tbody input[data-form="${key}"]`)];
      const allPicked = inputs.length && inputs.every((input) => input.checked);
      inputs.forEach((input) => setForm(rowOf(input), input, !allPicked));
      render();
      return;
    }
    const chip = event.target.closest("[data-remove-form]");
    const item = event.target.closest(".form-print__item");
    if (chip && item) {
      const entry = state[item.dataset.order];
      delete entry.forms[chip.dataset.removeForm];
      if (!Object.keys(entry.forms).length) delete state[item.dataset.order];
      render();
      return;
    }
    const previewItem = event.target.closest("[data-preview-item]");
    if (previewItem && item) {
      preview.open(item.dataset.order, previewItem);
      return;
    }
    const previewAll = event.target.closest("[data-preview-open]");
    if (previewAll) {
      preview.open("", previewAll);
      return;
    }
    if (event.target.closest("[data-remove]") && item) {
      delete state[item.dataset.order];
      render();
      return;
    }
    if (event.target.closest("[data-clear]")) {
      state = {};
      render();
    }
  });

  list.addEventListener("input", (event) => {
    const item = event.target.closest(".form-print__item");
    if (!item || !state[item.dataset.order]) return;
    if (event.target.matches("[data-item-note]")) state[item.dataset.order].note = event.target.value;
    if (event.target.matches("[data-item-address]")) state[item.dataset.order].address = event.target.value;
    save();
  });

  render();
})();
