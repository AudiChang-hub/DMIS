/* 同一份 DOM 切換；明確儲存、樂觀鎖、跨頁籤輸入保留。 */
(() => {
  const canonical = (field, value) => {
    if (field.type === 'checkbox') return value === true || value === 'true' || value === 'on';
    if (field.type === 'number') return Number(value || 0);
    return value == null ? '' : String(value);
  };
  const decision = (before, local, remote) => local === before ? 'update' : remote === before || remote === local ? 'keep' : 'conflict';
  if (typeof module !== 'undefined') module.exports = {canonical, decision};
  if (typeof document === 'undefined') return;
  const root = document.querySelector('[data-order-workspace]');
  if (!root) return;
  // 步驟式工作台：每個步驟是一個 <details data-step-key>，同頁儲存沿用既有機制。
  const steps = [...root.querySelectorAll('details[data-step-key]')];
  const stepLinks = [...root.querySelectorAll('[data-step-link]')];
  const forms = [...root.querySelectorAll('form[data-workspace-save]')];
  const bases = new Map();
  const conflicts = new Set();
  const message = root.querySelector('[data-workspace-message]');
  let busy = false;
  let allowLeave = false;
  const value = field => field.type === 'file' ? [...field.files].map(f => f.name + f.size + f.lastModified).join('|') : canonical(field, field.type === 'checkbox' ? field.checked : field.value);
  const fields = form => [...form.elements].filter(f => f.name && !['submit', 'button'].includes(f.type));
  const capture = form => new Map(fields(form).map(f => [f.name, value(f)]));
  const dirty = form => fields(form).some(f => !['csrfmiddlewaretoken', '_order_revision', 'operations-financial_revision'].includes(f.name) && value(f) !== bases.get(form)?.get(f.name));
  const notify = (text, error = false) => { message.hidden = false; message.textContent = text; message.classList.toggle('is-error', error); };
  const stepOf = field => field.closest('[data-step-key]')?.dataset.stepKey || 'order';
  function indicators() {
    const changed = new Set();
    forms.forEach(form => fields(form).forEach(f => {
      if (!f.name.endsWith('revision') && value(f) !== bases.get(form)?.get(f.name)) changed.add(stepOf(f));
    }));
    steps.forEach(step => {
      const marker = step.querySelector(':scope > summary [data-dirty-indicator]');
      if (marker) marker.hidden = !changed.has(step.dataset.stepKey);
    });
    stepLinks.forEach(link => {
      const marker = link.querySelector('[data-dirty-indicator]');
      if (marker) marker.hidden = !changed.has(link.dataset.stepLink);
      link.title = changed.has(link.dataset.stepLink) ? '有未儲存修改' : '';
    });
  }
  function activate(key, update = true) {
    const step = steps.find(item => item.dataset.stepKey === key);
    if (!step) return;
    step.open = true;
    step.scrollIntoView({block: 'start', behavior: 'smooth'});
    if (update) { const url = new URL(location.href); url.searchParams.set('tab', key); history.replaceState(null, '', url); }
    root.querySelectorAll('[data-workspace-edit-link]').forEach(a => { const url = new URL(a.href); url.searchParams.set('tab', key); a.href = url.href; });
    window.dispatchEvent(new CustomEvent('order-tab-change', {detail: {tab: key}}));
  }
  function reveal(field) {
    for (let parent = field.parentElement; parent && parent !== root; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
    field.scrollIntoView({block: 'center', behavior: 'smooth'});
    field.focus({preventScroll: true});
  }
  root.addEventListener('click', event => {
    const go = event.target.closest('[data-workspace-go]');
    if (go) { event.preventDefault(); activate(go.dataset.workspaceGo); }
    const stepLink = event.target.closest('[data-step-link]');
    if (stepLink) { event.preventDefault(); activate(stepLink.dataset.stepLink); }
    const link = event.target.closest('a[data-target-tab]');
    if (link) {
      event.preventDefault();
      const key = link.dataset.targetTab;
      activate(key);
      const section = link.dataset.targetAnchor && document.getElementById(link.dataset.targetAnchor);
      if (section) { if (section.tagName === 'DETAILS') section.open = true; section.scrollIntoView({block: 'start', behavior: 'smooth'}); }
    }
  });
  root.addEventListener('invalid', event => reveal(event.target), true);

  function updateField(field, remote) {
    if (field.type === 'checkbox') field.checked = canonical(field, remote);
    else field.value = remote == null ? '' : String(remote);
  }
  // 已確認收款即入帳；同頁儲存後立即鎖定，與伺服器端防改一致。
  const LOCKED_PAYMENT_FIELDS = ['confirmed', 'receipt_kind', 'received_amount', 'received_on', 'payment_method', 'receiving_account', 'card_principal', 'card_fee_charged', 'bank_card_fee'];
  function lockPayments(ids) {
    root.querySelectorAll('[data-payment-row]').forEach(row => {
      const id = row.querySelector('[name$="-id"]');
      if (!id || !ids.includes(id.value)) return;
      const prefix = id.name.slice(0, -2);
      LOCKED_PAYMENT_FIELDS.forEach(name => { const field = row.querySelector(`[name="${prefix}${name}"]`); if (field) field.disabled = true; });
      row.classList.add('is-locked'); row.dataset.paymentLocked = '';
      row.querySelector('[data-delete-payment]')?.remove();
    });
  }
  function merge(payload, savedForm) {
    if (payload.customer_balance_due != null) {
      root.querySelectorAll('[data-customer-balance]').forEach(node => { node.textContent = '$' + Number(payload.customer_balance_due).toLocaleString('zh-TW'); });
    }
    if (payload.discount) {
      root.querySelectorAll('[data-discount-summary]').forEach(node => { node.textContent = Number(payload.discount[node.dataset.discountSummary]).toLocaleString('zh-TW'); });
      root.querySelectorAll('[data-discount-total]').forEach(node => { node.dataset.discountTotal = payload.discount.before; });
    }
    if (payload.receipt_summary) {
      root.querySelectorAll('[data-receipt-value]').forEach(node => {
        node.textContent = Number(payload.receipt_summary[node.dataset.receiptValue]).toLocaleString('zh-TW');
      });
    }
    if (Array.isArray(payload.locked_payments)) lockPayments(payload.locked_payments);
    if (typeof payload.delivery_ready === 'boolean') {
      root.querySelectorAll('.delivery-completion-actions button[type="submit"]').forEach(button => {
        button.disabled = !payload.delivery_ready; button.setAttribute('aria-disabled', String(!payload.delivery_ready));
        button.textContent = payload.delivery_ready ? '確認完成交付' : '尚未符合交車條件';
        if (!payload.delivery_ready && payload.delivery_blocker) button.title = payload.delivery_blocker;
        if (payload.delivery_ready) { button.removeAttribute('title'); button.dataset.confirm = '確認完成交付嗎？'; }
      });
    }
    forms.forEach(form => {
      const updates = payload.sync?.[form.dataset.workspaceSave] || {};
      if (form.dataset.workspaceSave === 'operations' && payload.payment_values) {
        form.querySelectorAll('[data-payment-row], [data-payment-expectation]').forEach(row => {
          const id = row.querySelector('[name$="-id"]');
          const remote = id && payload.payment_values[id.value];
          if (!remote) return;
          const prefix = id.name.slice(0, -2);
          Object.entries(remote).forEach(([name, value]) => { updates[prefix + name] = value; });
        });
      }
      const base = bases.get(form);
      let conflict = false;
      for (const [name, remote] of Object.entries(updates)) {
        const field = form.elements.namedItem(name);
        if (!field || !field.tagName || ['change_reason', 'confirm_completed_correction', 'financial_revision'].some(k => name.endsWith(k))) continue;
        const next = canonical(field, remote);
        const mode = form === savedForm ? 'update' : decision(base.get(name), value(field), next);
        if (mode === 'conflict') { conflict = true; field.setAttribute('data-workspace-conflict', 'true'); }
        else {
          if (mode === 'update') updateField(field, remote);
          base.set(name, next);
        }
      }
      if (conflict) conflicts.add(form);
      if (!conflicts.has(form)) {
        for (const [name, next] of [['_order_revision', payload.revision], ['operations-financial_revision', payload.financial_revision]]) {
          const field = form.elements.namedItem(name);
          if (field && next != null) { field.value = next; base.set(name, value(field)); }
        }
      }
    });
  }
  function acceptRows(form, payload) {
    for (const [name, savedValue] of Object.entries(payload.values || {})) {
      const field = form.elements.namedItem(name); if (field) field.value = savedValue;
    }
    // 新增明細轉為既有明細；刪除／空白列移除並重編，避免再次儲存產生重複。
    [...form.querySelectorAll('[name$="-TOTAL_FORMS"]')].forEach(total => {
      const prefix = total.name.replace(/-TOTAL_FORMS$/, '');
      const rows = [...form.querySelectorAll('[data-dynamic-row],[data-payment-row],[data-form-row]')].filter(row => [...row.querySelectorAll('input')].some(f => f.name.startsWith(prefix + '-') && f.name.endsWith('-id')));
      let index = 0;
      rows.forEach(row => {
        const id = [...row.querySelectorAll('input')].find(f => f.name.startsWith(prefix + '-') && f.name.endsWith('-id'));
        const deleted = row.querySelector('[name$="-DELETE"]')?.checked;
        if (!id.value || deleted) { row.remove(); return; }
        const old = id.name.slice(0, -2);
        row.querySelectorAll('[name],[id],[for]').forEach(field => {
          ['name', 'id', 'for'].forEach(attr => { const text = field.getAttribute(attr); if (text) field.setAttribute(attr, text.replace(old, `${prefix}-${index}-`)); });
        });
        index++;
      });
      total.value = index;
      const initial = form.elements.namedItem(prefix + '-INITIAL_FORMS'); if (initial) initial.value = index;
    });
  }
  forms.forEach(form => {
    bases.set(form, capture(form));
    form.addEventListener('input', indicators); form.addEventListener('change', indicators);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy || conflicts.has(form)) {
        notify(busy ? '正在儲存，請稍候。' : '此區有與剛才更新重疊的欄位，未覆寫您的輸入。請記下修改後重新載入核對最新資料。', true);
        form.dispatchEvent(new CustomEvent('workspace-save-finished')); return;
      }
      busy = true;
      const button = event.submitter;
      const text = button?.textContent;
      if (button) { button.disabled = true; button.textContent = '正在儲存…'; }
      notify('正在儲存，請勿關閉頁面。');
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 45000);
      try {
        const response = await fetch(form.action || location.href, {method: 'POST', body: new FormData(form), headers: {'X-Order-Workspace': '1', 'Accept': 'application/json'}, signal: controller.signal});
        if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('登入狀態或權限可能已變更。您的輸入仍保留，請另開頁面確認後再試。');
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          const entries = Object.entries(payload.errors || {});
          notify([payload.error || '未能儲存。', ...entries.flatMap(([, errors]) => errors)].join('\n'), true);
          const first = entries.map(([name]) => form.elements.namedItem(name)).find(f => f?.focus);
          if (first) reveal(first);
          return;
        }
        acceptRows(form, payload);
        merge(payload, form);
        form.querySelectorAll('input[type=file]').forEach(field => { field.value = ''; });
        if (payload.summary_html) {
          const summary = document.getElementById('workspace-finance-summary');
          if (summary) summary.outerHTML = payload.summary_html;
        }
        bases.set(form, capture(form));
        form.dispatchEvent(new CustomEvent('workspace-saved'));
        indicators();
        notify(payload.message + (conflicts.size ? ' 其他區塊有重疊修改，輸入已保留，請核對後再儲存。' : ' 其他步驟的未儲存輸入仍保留。'), conflicts.size > 0);
      } catch (error) {
        notify(error.name === 'AbortError' ? '儲存回應逾時，結果尚未確認。請先另開此訂單確認是否已儲存，勿重複送出。' : error.message, true);
      } finally {
        clearTimeout(timeout); busy = false;
        if (button) { button.disabled = false; button.textContent = text; }
        form.dispatchEvent(new CustomEvent('workspace-save-finished'));
      }
    });
  });
  root.addEventListener('submit', event => {
    if (event.target.matches('[data-workspace-save]') || event.defaultPrevented || event.target.target === '_blank') return;
    if (forms.some(dirty) && !confirm('其他區塊尚未儲存。此操作會離開目前頁面，確定放棄未儲存修改嗎？')) { event.preventDefault(); return; }
    allowLeave = true;
  });
  window.addEventListener('beforeunload', event => {
    if (!allowLeave && (busy || forms.some(dirty))) { event.preventDefault(); event.returnValue = ''; }
  });
  // 由功能導回（?tab=）時捲到對應步驟；一般開啟則停在伺服器判定的目前步驟。
  const requested = new URL(location.href).searchParams.get('tab');
  if (requested) {
    const target = document.getElementById(`panel-${requested}`);
    if (target) { if (target.tagName === 'DETAILS') target.open = true; target.scrollIntoView({block: 'start'}); }
  }
  document.addEventListener('workspace-subsidy-toggle', event => {
    const orderForm = forms.find(form => form.dataset.workspaceSave === 'order');
    if (orderForm) { const field = orderForm.elements.namedItem('_order_revision'); field.value = event.detail.revision; bases.get(orderForm).set(field.name, value(field)); }
  });
  indicators();
})();
