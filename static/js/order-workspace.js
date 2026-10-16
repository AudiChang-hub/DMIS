/* 同一份 DOM 切換；自動儲存（2026-10-15）、樂觀鎖、跨頁籤輸入保留。 */
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
  const behavior = () => reduceMotion.matches ? 'instant' : 'smooth';
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
  const headerHeight = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--app-header-height')) || 72;
  // 固定頁首縮成精簡列後的高度；尚未縮起時暫時套用精簡樣式量測（同步還原，不觸發 sticky-hero 的觀察器）。
  function compactHeroHeight() {
    const hero = root.querySelector('[data-sticky-hero]');
    if (!hero) return 0;
    if (hero.classList.contains('is-stuck')) return hero.offsetHeight;
    const transition = hero.style.transition;
    hero.style.transition = 'none';
    hero.classList.add('is-stuck');
    const height = hero.offsetHeight;
    hero.classList.remove('is-stuck');
    hero.style.transition = transition;
    return height;
  }
  // 固定停點：頁首縮成精簡列，下方從建議下一步開始，接著是步驟內容；進頁與切換步驟都停在同一處（使用者 2026-10-14）。
  function stageTop() {
    const marker = root.querySelector('[data-order-stage-start]');
    if (!marker || !root.querySelector('[data-sticky-hero]')) return null;
    let node = marker.nextElementSibling;
    while (node && !node.getBoundingClientRect().height) node = node.nextElementSibling;
    if (!node) return null;
    return Math.max(0, Math.round(window.scrollY + node.getBoundingClientRect().top - headerHeight() - compactHeroHeight() - 24));
  }
  function land(smooth) {
    const room = root.querySelector('.order-steps');
    if (room) room.style.paddingBottom = '';
    const top = stageTop();
    if (top === null) return false;
    // 內容較短的步驟（如訂金）在下方補足空白，才捲得到同一個停點。
    const short = top - (document.documentElement.scrollHeight - window.innerHeight);
    if (room && short > 0) room.style.paddingBottom = `${Math.ceil(short)}px`;
    window.scrollTo({top, behavior: smooth ? behavior() : 'instant'});
    return true;
  }
  // 步驟在左側側邊列：切換後回到固定停點；舊的上方分頁列則捲到分頁列。
  function showBar(smooth = true) {
    if (!bar) return;
    const inSidebar = bar.closest('[data-order-nav]');
    if (inSidebar && land(smooth)) return;
    const target = inSidebar ? panelOf(activeKey) : bar;
    if (!target) return;
    const top = target.getBoundingClientRect().top;
    if (top < headerHeight() || top > window.innerHeight * 0.6) target.scrollIntoView({block: 'start', behavior: smooth ? behavior() : 'instant'});
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
      anchor.scrollIntoView({block: 'start', behavior: options.instant ? 'instant' : behavior()});
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
    if (tab) { event.preventDefault(); activate(tab.dataset.stepLink, {focusTab: true}); if (tab.closest('[data-order-nav]')) showBar(); return; }
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
    const keys = {ArrowRight: index + 1, ArrowLeft: index - 1, ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: tabs.length - 1};
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
  function merge(payload, savedForm, typed = new Set()) {
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
        // 送出後才打的字不被伺服器回傳值蓋掉，留待下一次自動儲存。
        const mode = form === savedForm ? (typed.has(name) ? 'keep' : 'update') : decision(base.get(name), value(field), next);
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
  // 自動儲存（使用者 2026-10-15）：停止輸入約 1 秒、改選項或離開欄位就送出，不需要按儲存。
  // 欄位未填完只在該區塊顯示缺什麼，不搶焦點；有後果的勾選（例如確認入帳）先確認。
  const AUTOSAVE_DELAY = 1000;
  const timers = new Map();
  const queued = new Set();
  const autosaving = form => !form.hasAttribute('data-autosave-off');
  const clock = () => new Date().toLocaleTimeString('zh-TW', {hour: '2-digit', minute: '2-digit', hour12: false});
  const visible = field => field.type !== 'hidden' && !field.disabled && field.getClientRects().length > 0;
  function labelOf(field) {
    const label = field.id && root.querySelector(`label[for="${CSS.escape(field.id)}"]`);
    return (label?.textContent || field.getAttribute('aria-label') || field.name).replace(/必填|選填/g, '').trim();
  }
  function statusOf(form) {
    let node = form.querySelector('[data-autosave-status]');
    if (!node) {
      node = document.createElement('p');
      node.className = 'autosave-status';
      node.dataset.autosaveStatus = '';
      node.setAttribute('role', 'status');
      node.setAttribute('aria-live', 'polite');
      (form.querySelector(':scope > fieldset') || form).append(node);
    }
    return node;
  }
  function setStatus(form, text, state) {
    const node = statusOf(form);
    node.textContent = text;
    node.dataset.state = state;
  }
  function schedule(form, delay = AUTOSAVE_DELAY) {
    if (!autosaving(form)) return;
    clearTimeout(timers.get(form));
    timers.set(form, setTimeout(() => autosave(form), delay));
  }
  // 回傳 true 表示已送出或排入佇列（之後會觸發 workspace-save-finished）。
  function autosave(form) {
    clearTimeout(timers.get(form));
    timers.delete(form);
    if (!dirty(form) || conflicts.has(form)) return false;
    if (busy) { queued.add(form); return true; }
    const invalid = fields(form).find(field => visible(field) && field.willValidate && !field.checkValidity());
    if (invalid) {
      setStatus(form, `尚未儲存：請填寫「${labelOf(invalid)}」`, 'pending');
      invalid.setAttribute('aria-invalid', 'true');
      return false;
    }
    form.requestSubmit();
    return true;
  }
  function saveNow(form) {
    return new Promise(resolve => {
      form.addEventListener('workspace-save-finished', () => resolve(), {once: true});
      if (!autosave(form)) resolve();
    });
  }
  const flush = () => Promise.all(forms.filter(form => autosaving(form) && dirty(form)).map(saveNow));
  // 表單腳本（試算、帶價）在載入後才補值；使用者還沒動過的區塊重新記錄基準，
  // 只是打開訂單再離開，不會把系統試算值當成修改存進去。
  const touched = new Set();
  const rebase = () => forms.forEach(form => { if (!touched.has(form) && !timers.has(form)) bases.set(form, capture(form)); });
  window.addEventListener('load', () => { setTimeout(rebase, 0); setTimeout(() => { rebase(); indicators(); }, 2000); }, {once: true});
  forms.forEach(form => {
    bases.set(form, capture(form));
    if (!autosaving(form)) {
      form.addEventListener('input', indicators); form.addEventListener('change', indicators);
    } else {
      form.noValidate = true;
      form.dataset.autosave = '';
      form.addEventListener('input', event => {
        if (event.isTrusted) touched.add(form);
        indicators();
        event.target.removeAttribute('aria-invalid');
        if (event.target.type !== 'file') schedule(form);
      });
      form.addEventListener('change', event => {
        const field = event.target;
        if (event.isTrusted) touched.add(form);
        if (field.type === 'checkbox' && field.checked && field.dataset.autosaveConfirm && !confirm(field.dataset.autosaveConfirm)) {
          field.checked = false; indicators(); return;
        }
        indicators();
        if (field.type === 'file') return;
        schedule(form, field.matches('select, [type="checkbox"], [type="radio"], [type="date"]') ? 250 : AUTOSAVE_DELAY);
      });
      form.addEventListener('focusout', () => { if (timers.has(form)) schedule(form, 0); });
    }
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const button = event.submitter;
      const auto = autosaving(form) && !button;
      if (busy) {
        if (auto) { queued.add(form); return; }
        notify('正在儲存，請稍候。', true);
        form.dispatchEvent(new CustomEvent('workspace-save-finished')); return;
      }
      if (conflicts.has(form)) {
        notify('此區有與剛才更新重疊的欄位，未覆寫您的輸入。請記下修改後重新載入核對最新資料。', true);
        form.dispatchEvent(new CustomEvent('workspace-save-finished')); return;
      }
      const finishing = button?.hasAttribute('data-workspace-finish');
      if (finishing && !dirty(form)) {
        await flush();
        if (forms.some(dirty) && !confirm('有區塊還沒儲存成功（例如必填欄位未填），確定放棄這些修改並完成編輯嗎？')) return;
        allowLeave = true; location.href = button.dataset.finishUrl; return;
      }
      busy = true;
      const text = button?.textContent;
      if (button) { button.disabled = true; button.textContent = '正在儲存…'; }
      if (auto) setStatus(form, '儲存中…', 'saving');
      else notify('正在儲存，請勿關閉頁面。');
      const sent = capture(form);
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 45000);
      try {
        const response = await fetch(form.action || location.href, {method: 'POST', body: new FormData(form), headers: {'X-Order-Workspace': '1', 'Accept': 'application/json'}, signal: controller.signal});
        if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('登入狀態或權限可能已變更。您的輸入仍保留，請另開頁面確認後再試。');
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          const entries = Object.entries(payload.errors || {});
          const detail = [payload.error || '未能儲存。', ...entries.flatMap(([, errors]) => errors)];
          entries.forEach(([name]) => { const field = form.elements.namedItem(name); if (field?.setAttribute) field.setAttribute('aria-invalid', 'true'); });
          if (auto) { setStatus(form, '尚未儲存：' + detail.join(' '), 'error'); return; }
          notify(detail.join('\n'), true);
          const first = entries.map(([name]) => form.elements.namedItem(name)).find(f => f?.focus);
          if (first) reveal(first);
          return;
        }
        const typed = new Set(fields(form).filter(f => value(f) !== sent.get(f.name)).map(f => f.name));
        acceptRows(form, payload);
        merge(payload, form, typed);
        form.querySelectorAll('input[type=file]').forEach(field => { field.value = ''; });
        if (payload.summary_html) {
          const summary = document.getElementById('workspace-finance-summary');
          if (summary) summary.outerHTML = payload.summary_html;
        }
        if (payload.subsidy_summary_html) {
          const agencies = document.getElementById('subsidy-agency-summary');
          if (agencies) agencies.outerHTML = payload.subsidy_summary_html;
        }
        if (payload.registration_html) {
          const completion = root.querySelector('[data-registration-completion]');
          if (completion) completion.outerHTML = payload.registration_html;
        }
        const base = capture(form);
        typed.forEach(name => base.set(name, sent.get(name)));
        // 「本次更新說明」只跟著這一次儲存，存好就清空，下一次自動儲存不重複帶入。
        fields(form).filter(f => f.name.endsWith('change_reason') && !typed.has(f.name)).forEach(f => { f.value = ''; base.set(f.name, value(f)); });
        bases.set(form, base);
        form.dispatchEvent(new CustomEvent('workspace-saved'));
        indicators();
        if (auto) setStatus(form, conflicts.size ? '已自動儲存，但其他區塊有重疊修改，請核對。' : `已自動儲存 ${clock()}`, conflicts.size ? 'error' : 'saved');
        else notify(payload.message + (conflicts.size ? ' 其他區塊有重疊修改，輸入已保留，請核對後再儲存。' : ''), conflicts.size > 0);
        if (finishing && !conflicts.size) {
          await flush();
          if (!forms.some(dirty)) { allowLeave = true; location.href = button.dataset.finishUrl; return; }
        }
        if (typed.size) schedule(form);
      } catch (error) {
        const reason = error.name === 'AbortError' ? '儲存回應逾時，結果尚未確認。請先另開此訂單確認是否已儲存，勿重複送出。' : error.message;
        if (auto) setStatus(form, '尚未儲存：' + reason, 'error'); else notify(reason, true);
      } finally {
        clearTimeout(timeout); busy = false;
        if (button) { button.disabled = false; button.textContent = text; }
        form.dispatchEvent(new CustomEvent('workspace-save-finished'));
        const next = [...queued]; queued.clear();
        next.forEach(item => schedule(item, 0));
      }
    });
  });
  // 離開頁面前（送出其他表單、點連結）先把還沒送出的自動儲存存完。
  root.addEventListener('submit', async event => {
    const target = event.target;
    if (target.matches('[data-workspace-save]') || event.defaultPrevented || target.target === '_blank') return;
    if (target.dataset.flushed !== '1' && forms.some(dirty)) {
      event.preventDefault();
      await flush();
      if (forms.some(dirty) && !confirm('有區塊還沒儲存成功（例如必填欄位未填）。此操作會離開目前頁面，確定放棄這些輸入嗎？')) return;
      target.dataset.flushed = '1';
      allowLeave = true;
      target.requestSubmit(event.submitter && event.submitter.form === target ? event.submitter : undefined);
      return;
    }
    allowLeave = true;
  });
  document.addEventListener('click', async event => {
    const link = event.target.closest?.('a[href]');
    if (!link || event.defaultPrevented || link.target === '_blank' || link.hasAttribute('download') || event.metaKey || event.ctrlKey || event.shiftKey) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || (url.pathname === location.pathname && url.search === location.search)) return;
    if (!forms.some(dirty) && !busy) return;
    event.preventDefault();
    await flush();
    if (forms.some(dirty) && !confirm('有區塊還沒儲存成功（例如必填欄位未填）。確定離開並放棄這些輸入嗎？')) return;
    allowLeave = true; location.href = link.href;
  });
  window.addEventListener('beforeunload', event => {
    if (!allowLeave && (busy || forms.some(dirty))) { event.preventDefault(); event.returnValue = ''; }
  });
  // 初始分頁：網址錨點（#step-<步驟> 或分頁內區塊）優先，其次是含表單錯誤的分頁，
  // 否則沿用伺服器依 ?tab= 或目前步驟選定的分頁（由功能導回時 ?tab= 與錨點一致）。
  // 靜態提示（如 <p class="field-error">沒有可配車輛</p>）不算表單錯誤，不可搶走進頁分頁。
  if (tabbed) {
    let target = resolveHash(location.hash);
    if (!target) {
      const invalid = steps.map(step => step.querySelector('.errorlist, small.field-error, [aria-invalid="true"]')).find(Boolean);
      if (invalid) target = {key: invalid.closest('[role="tabpanel"]').dataset.stepKey, anchor: invalid};
    }
    activate(target?.key || activeKey, {animate: false, url: false, announce: true});
    // 分頁外的錨點（如 #commission-attribution）交給瀏覽器原生定位。
    let outsideAnchor = null;
    try { outsideAnchor = !target && location.hash.length > 1 && document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (_error) { /* 格式錯誤的錨點視同沒有 */ }
    if (target?.anchor) goTo(target.key, target.anchor, {animate: false, url: false, instant: true});
    else if (!outsideAnchor) {
      // 進頁直接定位到固定停點（不用平滑捲動：載入中的版面變動會讓動畫停在半路）；
      // 圖片、字型載入後版面若再變動，使用者還沒自行捲動就再對齊一次。
      if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
      showBar(false);
      let touched = false;
      const settle = () => { if (!touched) showBar(false); };
      const resized = 'ResizeObserver' in window ? new ResizeObserver(settle) : null;
      const stop = () => { touched = true; resized?.disconnect(); };
      ['wheel', 'touchstart', 'keydown', 'pointerdown'].forEach(type => window.addEventListener(type, stop, {once: true, passive: true}));
      resized?.observe(root);
      window.addEventListener('load', () => { settle(); setTimeout(stop, 1500); }, {once: true});
      document.fonts?.ready.then(settle);
    }
    updateOverflow();
  }
  document.addEventListener('workspace-subsidy-toggle', event => {
    const orderForm = forms.find(form => form.dataset.workspaceSave === 'order');
    if (orderForm) { const field = orderForm.elements.namedItem('_order_revision'); field.value = event.detail.revision; bases.get(orderForm).set(field.name, value(field)); }
  });
  indicators();
})();
