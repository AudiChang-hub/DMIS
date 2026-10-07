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
  // 步驟分頁：每個步驟是一個 role="tabpanel" 的區塊，一次只顯示一個；同頁儲存沿用既有機制。
  const steps = [...root.querySelectorAll('[role="tabpanel"][data-step-key]')];
  const tabs = [...root.querySelectorAll('[role="tab"][data-step-link]')];
  const stepLinks = [...root.querySelectorAll('[data-step-link]')];
  const bar = root.querySelector('[data-order-step-bar]');
  const scroller = root.querySelector('[data-step-scroller]');
  const tablist = root.querySelector('[data-step-tablist]');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const tabbed = tabs.length > 0 && steps.length > 0;
  let activeKey = tabs.find(tab => tab.getAttribute('aria-selected') === 'true')?.dataset.stepLink || steps[0]?.dataset.stepKey;
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
  const behavior = () => reduceMotion.matches ? 'auto' : 'smooth';
  function indicators() {
    const changed = new Set();
    forms.forEach(form => fields(form).forEach(f => {
      if (!f.name.endsWith('revision') && value(f) !== bases.get(form)?.get(f.name)) changed.add(stepOf(f));
    }));
    root.querySelectorAll('[data-step-key]').forEach(step => {
      const marker = step.querySelector(':scope > .order-step__header [data-dirty-indicator]');
      if (marker) marker.hidden = !changed.has(step.dataset.stepKey);
    });
    stepLinks.forEach(link => {
      const marker = link.querySelector('[data-dirty-indicator]');
      if (marker) marker.hidden = !changed.has(link.dataset.stepLink);
      link.title = changed.has(link.dataset.stepLink) ? '有未儲存修改' : '';
    });
  }
  const panelOf = key => steps.find(step => step.dataset.stepKey === key);
  // 分頁列可橫向捲動時，兩側淡出提示還有其他分頁。
  function updateOverflow() {
    if (!bar || !scroller) return;
    const max = scroller.scrollWidth - scroller.clientWidth;
    bar.classList.toggle('is-overflow-start', max > 1 && scroller.scrollLeft > 2);
    bar.classList.toggle('is-overflow-end', max > 1 && scroller.scrollLeft < max - 2);
  }
  // 只捲動分頁列本身，把目前分頁置中；不移動整頁。
  function centerTab(tab, smooth) {
    if (!scroller || scroller.scrollWidth <= scroller.clientWidth + 1) return;
    const box = scroller.getBoundingClientRect();
    const rect = tab.getBoundingClientRect();
    const left = scroller.scrollLeft + rect.left - box.left - (box.width - rect.width) / 2;
    scroller.scrollTo({left: Math.max(0, left), behavior: smooth ? behavior() : 'auto'});
  }
  // 分頁列不在畫面上半部時捲到分頁列，讓使用者看到切換結果。
  function showBar() {
    if (!bar) return;
    const top = bar.getBoundingClientRect().top;
    if (top < 0 || top > window.innerHeight * 0.6) bar.scrollIntoView({block: 'start', behavior: behavior()});
  }
  function activate(key, options = {}) {
    const panel = panelOf(key);
    if (!tabbed || !panel) return false;
    const changed = key !== activeKey;
    activeKey = key;
    tabs.forEach(tab => {
      const selected = tab.dataset.stepLink === key;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      tab.classList.toggle('is-active', selected);
    });
    steps.forEach(step => {
      const selected = step === panel;
      step.hidden = !selected;
      step.classList.toggle('is-active', selected);
      if (!selected) step.classList.remove('is-entering');
    });
    if (changed && options.animate !== false && !reduceMotion.matches) {
      panel.classList.remove('is-entering');
      void panel.offsetWidth;
      panel.classList.add('is-entering');
    }
    const tab = tabs.find(item => item.dataset.stepLink === key);
    if (tab) {
      centerTab(tab, options.animate !== false);
      if (options.focusTab) tab.focus({preventScroll: true});
    }
    if (options.url !== false) {
      const url = new URL(location.href);
      url.searchParams.set('tab', key);
      url.hash = options.anchor || `step-${key}`;
      history.replaceState(history.state, '', url);
    }
    root.querySelectorAll('[data-workspace-edit-link]').forEach(a => { const url = new URL(a.href); url.searchParams.set('tab', key); a.href = url.href; });
    if (changed || options.announce) window.dispatchEvent(new CustomEvent('order-tab-change', {detail: {tab: key}}));
    return true;
  }
  // 由其他位置（下一步建議、頁首按鈕、錨點）前往某步驟：切換分頁後捲到分頁列或指定區塊。
  function goTo(key, anchor, options = {}) {
    if (!activate(key, {...options, anchor: anchor?.id})) return false;
    if (anchor && anchor !== panelOf(key)) {
      for (let node = anchor; node && node !== root; node = node.parentElement) if (node.tagName === 'DETAILS') node.open = true;
      anchor.scrollIntoView({block: 'start', behavior: options.instant ? 'auto' : behavior()});
    } else {
      showBar();
      panelOf(key).focus({preventScroll: true});
    }
    return true;
  }
  // #step-<步驟>、舊的 #panel-<步驟>，或分頁內任何區塊的 id。
  function resolveHash(hash) {
    let id = (hash || '').replace(/^#/, '');
    try { id = decodeURIComponent(id); } catch (_error) { return null; }
    if (!id) return null;
    const named = id.match(/^(?:step|panel|tab)-([a-z]+)$/);
    if (named && panelOf(named[1])) return {key: named[1]};
    const target = document.getElementById(id);
    const panel = target?.closest('[role="tabpanel"][data-step-key]');
    return panel ? {key: panel.dataset.stepKey, anchor: target} : null;
  }
  function reveal(field) {
    const panel = field.closest('[role="tabpanel"][data-step-key]');
    if (panel && panel.hidden) activate(panel.dataset.stepKey, {animate: false});
    for (let parent = field.parentElement; parent && parent !== root; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
    field.scrollIntoView({block: 'center', behavior: behavior()});
    field.focus({preventScroll: true});
  }
  const plainClick = event => event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
  root.addEventListener('click', event => {
    if (!tabbed || !plainClick(event)) return;
    const go = event.target.closest('[data-workspace-go]');
    if (go && panelOf(go.dataset.workspaceGo)) { event.preventDefault(); goTo(go.dataset.workspaceGo); return; }
    const tab = event.target.closest('[role="tab"][data-step-link]');
    if (tab) { event.preventDefault(); activate(tab.dataset.stepLink, {focusTab: true}); return; }
    const link = event.target.closest('a[data-target-tab]');
    if (link && link.hasAttribute('href') && panelOf(link.dataset.targetTab)) {
      event.preventDefault();
      const anchor = link.dataset.targetAnchor && document.getElementById(link.dataset.targetAnchor);
      goTo(link.dataset.targetTab, anchor || null);
    }
  });
  // 鍵盤：左右鍵切換相鄰分頁、Home／End 到頭尾（切換即顯示）；空白鍵等同點擊。
  tablist?.addEventListener('keydown', event => {
    const index = tabs.indexOf(event.target.closest('[role="tab"]'));
    if (index < 0) return;
    if (event.key === ' ' || event.key === 'Spacebar') { event.preventDefault(); activate(tabs[index].dataset.stepLink, {focusTab: true}); return; }
    const keys = {ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1};
    if (!(event.key in keys)) return;
    event.preventDefault();
    activate(tabs[(keys[event.key] + tabs.length) % tabs.length].dataset.stepLink, {focusTab: true});
  });
  root.addEventListener('invalid', event => reveal(event.target), true);
  // form-feedback.js 要聚焦隱藏分頁內的欄位時，先切到該分頁。
  root.addEventListener('order-tabpanel-reveal', event => {
    const panel = event.target.closest('[role="tabpanel"][data-step-key]');
    if (panel) activate(panel.dataset.stepKey, {animate: false});
  });
  window.addEventListener('hashchange', () => {
    const target = resolveHash(location.hash);
    if (target) goTo(target.key, target.anchor || null);
  });
  scroller?.addEventListener('scroll', updateOverflow, {passive: true});
  window.addEventListener('resize', () => {
    updateOverflow();
    const tab = tabs.find(item => item.dataset.stepLink === activeKey);
    if (tab) centerTab(tab, false);
  });

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
        if (payload.subsidy_summary_html) {
          const agencies = document.getElementById('subsidy-agency-summary');
          if (agencies) agencies.outerHTML = payload.subsidy_summary_html;
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
  // 初始分頁：網址錨點（#step-<步驟> 或分頁內區塊）優先，其次是含欄位錯誤的分頁，
  // 否則沿用伺服器依 ?tab= 或目前步驟選定的分頁（由功能導回時 ?tab= 與錨點一致）。
  if (tabbed) {
    const requested = new URL(location.href).searchParams.get('tab');
    let target = resolveHash(location.hash);
    if (!target) {
      const invalid = steps.map(step => step.querySelector('.errorlist, .field-error, [aria-invalid="true"]')).find(Boolean);
      if (invalid) target = {key: invalid.closest('[role="tabpanel"]').dataset.stepKey, anchor: invalid};
    }
    activate(target?.key || activeKey, {animate: false, url: false, announce: true});
    if (target?.anchor) goTo(target.key, target.anchor, {animate: false, url: false, instant: true});
    else if (target || requested) showBar();
    updateOverflow();
  }
  document.addEventListener('workspace-subsidy-toggle', event => {
    const orderForm = forms.find(form => form.dataset.workspaceSave === 'order');
    if (orderForm) { const field = orderForm.elements.namedItem('_order_revision'); field.value = event.detail.revision; bases.get(orderForm).set(field.name, value(field)); }
  });
  indicators();
})();
