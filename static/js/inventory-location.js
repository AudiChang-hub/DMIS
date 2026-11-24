(() => {
  "use strict";

  // T-308 B：庫存列表的「實際位置」直接下拉改，選了就存，存好可以復原。
  // 整頁共用一份選項（#inventory-location-options），點開某列時才複製進去。
  // 防誤觸：只在 change 之後送出（捲動、點一下不會存）；用鍵盤上下切換時先不存，按 Enter 或離開欄位才存。
  const source = document.getElementById("inventory-location-options");
  if (!source) return;
  const csrf = source.dataset.csrf || "";
  const NAV_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"]);

  const optionFor = (select, value) => Array.from(select.options).find((option) => option.value === value);

  const ensureOption = (select, value, label) => {
    if (optionFor(select, value)) return;
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label || value;
    select.append(option);
  };

  // 第一次點開／聚焦時才換成完整選單；目前位置若是已停用的車行，保留原本那一項。
  const populate = (select) => {
    if (select.dataset.locationLoaded) return;
    select.dataset.locationLoaded = "1";
    const current = select.dataset.locationCurrent;
    const original = select.options[0];
    const label = original ? original.textContent : current;
    select.replaceChildren(source.content.cloneNode(true));
    ensureOption(select, current, label);
    select.value = current;
  };

  const statusFor = (select) => select.closest("[data-inventory-location]").querySelector("[data-location-status]");

  const showStatus = (select, text, { tone = "", undo = null } = {}) => {
    const status = statusFor(select);
    status.replaceChildren();
    const message = document.createElement("span");
    message.textContent = text;
    status.append(message);
    if (undo) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "inventory-location__undo";
      button.textContent = "復原";
      button.setAttribute("aria-label", `復原 ${select.closest("[data-inventory-location]").dataset.identifier} 的位置`);
      button.addEventListener("click", undo, { once: true });
      status.append(button);
    }
    status.classList.toggle("is-error", tone === "error");
    status.classList.toggle("is-saving", tone === "saving");
    status.hidden = false;
  };

  const post = async (select, fields) => {
    const wrap = select.closest("[data-inventory-location]");
    const body = new FormData();
    body.append("csrfmiddlewaretoken", csrf);
    Object.entries(fields).forEach(([key, value]) => body.append(key, value));
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 12000);
    wrap.classList.add("is-saving");
    select.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(wrap.dataset.url, {
        method: "POST",
        body,
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 403) payload.message = payload.message || "沒有改位置的權限。";
      return { ok: response.ok && payload.ok, payload };
    } catch (error) {
      return {
        ok: false,
        payload: { message: error.name === "AbortError" ? "儲存等候逾時，位置沒有改，請再試一次。" : "連線失敗，位置沒有改，請再試一次。" },
      };
    } finally {
      window.clearTimeout(timeoutId);
      wrap.classList.remove("is-saving");
      select.removeAttribute("aria-busy");
    }
  };

  // 失敗時退回伺服器回報的目前位置（可能剛被別人改過）。
  const settle = (select, payload) => {
    if (payload.value !== undefined) {
      ensureOption(select, payload.value, payload.label);
      select.dataset.locationCurrent = payload.value;
    }
    select.value = select.dataset.locationCurrent;
  };

  const save = async (select) => {
    delete select.dataset.locationPending;
    const target = select.value;
    const current = select.dataset.locationCurrent;
    if (target === current) return;
    if (select.dataset.locationSaving) {
      select.dataset.locationQueued = "1";
      return;
    }
    select.dataset.locationSaving = "1";
    showStatus(select, "儲存中…", { tone: "saving" });
    const { ok, payload } = await post(select, { location: target, expected: current });
    delete select.dataset.locationSaving;
    if (!ok) {
      settle(select, payload);
      showStatus(select, payload.message || "無法改位置，請稍後再試。", { tone: "error" });
      return;
    }
    settle(select, payload);
    if (payload.changed) {
      showStatus(select, `已改放到 ${payload.label}`, {
        undo: () => undo(select, payload.previous_value, payload.previous_label),
      });
    } else {
      showStatus(select, payload.message);
    }
    if (select.dataset.locationQueued) {
      delete select.dataset.locationQueued;
      save(select);
    }
  };

  const undo = async (select, previousValue, previousLabel) => {
    if (select.dataset.locationSaving) return;
    select.dataset.locationSaving = "1";
    showStatus(select, "復原中…", { tone: "saving" });
    const { ok, payload } = await post(select, {
      location: previousValue, expected: select.dataset.locationCurrent, undo: "1",
    });
    delete select.dataset.locationSaving;
    settle(select, payload);
    if (!ok) {
      showStatus(select, payload.message || "無法復原，請稍後再試。", { tone: "error" });
      return;
    }
    showStatus(select, `已復原，放回 ${payload.label || previousLabel}`);
  };

  const selectFrom = (event) => (
    event.target instanceof HTMLSelectElement && event.target.closest("[data-inventory-location]") ? event.target : null
  );

  ["focusin", "pointerdown", "mousedown", "touchstart"].forEach((type) => {
    document.addEventListener(type, (event) => {
      const select = selectFrom(event);
      if (!select) return;
      populate(select);
      if (type !== "focusin") select.dataset.locationInput = "pointer";
    }, { passive: true, capture: true });
  });

  document.addEventListener("keydown", (event) => {
    const select = selectFrom(event);
    if (!select) return;
    if (NAV_KEYS.has(event.key) || event.key.length === 1) select.dataset.locationInput = "key";
    if (event.key === "Enter" && select.dataset.locationPending) {
      event.preventDefault();
      save(select);
    }
  });

  document.addEventListener("keyup", (event) => {
    const select = selectFrom(event);
    if (select && event.key === "Enter" && select.dataset.locationPending) save(select);
  });

  document.addEventListener("change", (event) => {
    const select = selectFrom(event);
    if (!select) return;
    if (select.dataset.locationInput === "key") {
      // 鍵盤逐項切換時每一步都會觸發 change，先不存，等 Enter 或離開欄位。
      select.dataset.locationPending = "1";
      if (select.value !== select.dataset.locationCurrent) {
        showStatus(select, "按 Enter 或離開欄位就會存");
      } else {
        statusFor(select).hidden = true;
      }
      return;
    }
    save(select);
  });

  document.addEventListener("focusout", (event) => {
    const select = selectFrom(event);
    if (select && select.dataset.locationPending) save(select);
  });
})();
