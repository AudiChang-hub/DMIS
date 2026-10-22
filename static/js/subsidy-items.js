document.addEventListener("DOMContentLoaded", () => {
  const section = document.querySelector("[data-subsidy-items]");
  if (!section) return;
  const subsidyForm = document.querySelector("[data-subsidy-form]");
  // 「新舊車主不同人」（使用者 2026-10-22 T-84）：不勾＝同一人，舊車主欄位收起並沿用新車主；打勾才展開讓人填舊車主。
  subsidyForm?.querySelector('[name="old_owner_different"]')?.addEventListener('change', event => {
    const different = event.target.checked;
    subsidyForm.querySelectorAll('[data-old-owner-field]').forEach(cell => { cell.hidden = !different; });
    subsidyForm.querySelectorAll('[data-old-owner-same]').forEach(note => { note.hidden = different; });
    for (const [name, value] of [['old_owner_name', subsidyForm.dataset.ownerName], ['old_owner_id_number', subsidyForm.dataset.ownerId]]) {
      const field = subsidyForm.querySelector(`[name="${name}"]`);
      if (!field) continue;
      // 改成不同人時清掉沿用的新車主資料，避免把新車主當成舊車主送出。
      const next = different ? (field.value === (value || '') ? '' : field.value) : (value || '');
      if (field.value !== next) { field.value = next; field.dispatchEvent(new Event('input', {bubbles: true})); }
    }
    if (different) subsidyForm.querySelector('[name="old_owner_name"]')?.focus({preventScroll: true});
  });
  // 汰舊流程改由補助項目推導（使用者 2026-10-22 T-81）：存檔後汰舊狀態改變時重新載入，文件區、完成條件與「新舊車主不同人」一起更新。
  const ownerDifferent = subsidyForm?.querySelector('[name="old_owner_different"]');
  let savedOwnerDifferent = ownerDifferent?.checked;
  subsidyForm?.addEventListener("workspace-saved", event => {
    const tradeIn = event.detail?.subsidy_trade_in;
    if (typeof tradeIn === "boolean" && String(tradeIn) !== subsidyForm.dataset.wasEnabled) { location.reload(); return; }
    // 新舊車主是否同人會改變必備文件（聲明書、舊車主證件）與「已備妥」件數：存好後原地換新文件區，不跳動、不搶焦點。
    if (ownerDifferent && ownerDifferent.checked !== savedOwnerDifferent) {
      savedOwnerDifferent = ownerDifferent.checked;
      window.DMISInplace?.refresh?.(location.href).catch(() => {});
    }
  });
  const subsidyToggle = subsidyForm?.querySelector("[name='is_trade_in_subsidy']");
  const toggleMessage = subsidyForm?.querySelector("[data-subsidy-toggle-message]");
  const revisionInput = subsidyForm?.querySelector("[name='_order_revision']");
  // 補助文件原地上傳或刪除後，關閉補助前的「已有文件」提醒跟著伺服器狀態。
  document.addEventListener("inplace:updated", event => {
    const fresh = event.detail.doc?.querySelector("[data-subsidy-form]");
    if (subsidyForm && fresh) subsidyForm.dataset.hasDocuments = fresh.dataset.hasDocuments || "";
  });
  // 文件區上傳後會原地換新（inplace-regions.js），每次都重新取得目前畫面上的節點。
  function setUploadControls(enabled) {
    document.querySelectorAll("[data-subsidy-upload-control]").forEach(control => {
      control.hidden = !enabled;
    });
    document.querySelectorAll("[data-subsidy-document-row]").forEach(row => {
      const required = enabled && row.dataset.requiredWhenEnabled === "true";
      const requiredBadge = row.querySelector("[data-subsidy-required-badge]");
      const optionalBadge = row.querySelector("[data-subsidy-optional-badge]");
      if (requiredBadge) requiredBadge.hidden = !required;
      if (optionalBadge) optionalBadge.hidden = required;
    });
  }

  function setCompletionState(enabled) {
    const stageStatus = document.querySelector("[data-subsidy-stage-status]");
    const completion = document.querySelector("[data-subsidy-completion]");
    if (stageStatus) {
      stageStatus.textContent = enabled ? "辦理中" : "未申請";
      stageStatus.classList.remove("done");
    }
    if (!completion) return;
    completion.classList.add("has-missing");
    completion.classList.remove("is-ready");
    const title = completion.querySelector("strong");
    const description = completion.querySelector("p");
    if (title) title.textContent = enabled ? "補助資料尚待補齊" : "目前未啟用補助申請";
    if (description) {
      description.textContent = enabled
        ? "可立即上傳文件；舊車資料與補助項目填妥後，再儲存補助資料。"
        : "已上傳的文件仍會保留；再次啟用後可繼續補齊資料。";
    }
  }

  async function persistSubsidyToggle() {
    if (!subsidyForm || !subsidyToggle || !revisionInput) return;
    const previousEnabled = subsidyForm.dataset.wasEnabled === "true";
    const enabled = subsidyToggle.checked;
    if (!enabled && previousEnabled && subsidyForm.dataset.hasDocuments === "true") {
      const confirmed = window.confirm("關閉補助申請後，既有文件仍會保留，但上傳按鈕會暫時隱藏。確定關閉嗎？");
      if (!confirmed) {
        subsidyToggle.checked = previousEnabled;
        return;
      }
    }

    subsidyToggle.disabled = true;
    subsidyToggle.closest("label")?.setAttribute("aria-busy", "true");
    if (toggleMessage) toggleMessage.textContent = enabled ? "正在啟用補助申請…" : "正在關閉補助申請…";
    const body = new URLSearchParams({
      enabled: enabled ? "1" : "0",
      _order_revision: revisionInput.value,
    });
    try {
      const response = await fetch(subsidyForm.dataset.subsidyToggleUrl, {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": subsidyForm.querySelector("[name='csrfmiddlewaretoken']").value,
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        body,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "補助狀態未能儲存，請稍後再試。");
      }
      subsidyForm.dataset.wasEnabled = payload.enabled ? "true" : "false";
      subsidyForm.classList.remove("has-toggle-error");
      revisionInput.value = String(payload.revision);
      document.dispatchEvent(new CustomEvent('workspace-subsidy-toggle', {detail: payload}));
      subsidyToggle.checked = payload.enabled;
      setUploadControls(payload.enabled);
      setCompletionState(payload.enabled);
      if (toggleMessage) toggleMessage.textContent = payload.message;
    } catch (error) {
      subsidyToggle.checked = previousEnabled;
      setUploadControls(previousEnabled);
      subsidyForm.classList.add("has-toggle-error");
      if (toggleMessage) toggleMessage.textContent = error.message;
    } finally {
      subsidyToggle.disabled = false;
      subsidyToggle.closest("label")?.removeAttribute("aria-busy");
    }
  }

  if (subsidyToggle) {
    setUploadControls(subsidyForm.dataset.wasEnabled === "true");
    subsidyToggle.addEventListener("change", persistSubsidyToggle);
  }

  const list = section.querySelector("[data-form-list]");
  const template = section.querySelector("[data-empty-form]");
  const total = section.querySelector("input[name$='-TOTAL_FORMS']");
  const refreshTotal = () => {
    let sum = 0;
    list.querySelectorAll('[data-form-row]').forEach(row => {
      if (row.querySelector('[name$="-DELETE"]')?.checked) return;
      const value = Number((row.querySelector('[name$="-expected_amount"]')?.value || '0').replaceAll(',', ''));
      if (Number.isFinite(value)) sum += value;
    });
    const output = section.querySelector('[data-subsidy-total]');
    if (output) output.textContent = sum.toLocaleString('zh-TW', {maximumFractionDigits: 2});
  };
  section.addEventListener('input', refreshTotal); section.addEventListener('change', refreshTotal); refreshTotal();
  section.querySelector("[data-add-form]")?.addEventListener("click", () => {
    const index = Number(total.value);
    const fragment = template.content.cloneNode(true);
    fragment.querySelectorAll("[name],[id],[for]").forEach(element => {
      for (const attribute of ["name", "id", "for"]) {
        if (element.hasAttribute(attribute)) {
          element.setAttribute(attribute, element.getAttribute(attribute).replaceAll("__prefix__", String(index)));
        }
      }
    });
    list.append(fragment);
    total.value = index + 1;
    section.querySelector("[data-subsidy-empty]")?.setAttribute("hidden", "");
    list.lastElementChild?.querySelector("input:not([type=hidden]), select")?.focus({preventScroll: true});
    refreshTotal();
  });
  list.addEventListener("change", event => {
    if (!event.target.matches("input[name$='-DELETE']")) return;
    event.target.closest("[data-form-row]")?.classList.toggle("is-deleted", event.target.checked);
  });
});
