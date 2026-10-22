/* 同一份 DOM 切換；自動儲存（2026-10-15）、樂觀鎖、跨頁籤輸入保留。 */
(() => {
  const canonical = (field, value) => {
    if (field.type === 'checkbox') return value === true || value === 'true' || value === 'on';
    if (field.type === 'number') return Number(value || 0);
    return value == null ? '' : String(value);
  };
  const decision = (before, local, remote) => local === before ? 'update' : remote === before || remote === local ? 'keep' : 'conflict';
  // radio 只看選中的那個；同名欄位（例如補助方案勾選組）合併成一個值，避免互相覆蓋而永遠判定未儲存。
  const value = field => field.type === 'file' ? [...field.files].map(f => f.name + f.size + f.lastModified).join('|')
    : field.type === 'radio' ? (field.checked ? field.value : '')
    : canonical(field, field.type === 'checkbox' ? field.checked : field.value);
  const snapshot = list => list.reduce((map, f) => map.set(f.name, map.has(f.name) ? `${map.get(f.name)}|${value(f)}` : value(f)), new Map());
  // 儲存後重編明細：送出時已標記刪除的列移除；已存列排前面（INITIAL_FORMS），未存列接在後面保留。
  const rowPlan = rows => {
    const kept = rows.filter(row => !row.deletedWhenSent);
    const saved = kept.filter(row => row.saved);
    return {removed: rows.filter(row => row.deletedWhenSent), order: [...saved, ...kept.filter(row => !row.saved)], initial: saved.length};
  };
  if (typeof module !== 'undefined') module.exports = {canonical, decision, snapshot, rowPlan};
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
  const fields = form => [...form.elements].filter(f => f.name && !['submit', 'button'].includes(f.type));
  const capture = form => snapshot(fields(form));
  const changedNames = (form, base = bases.get(form)) => [...capture(form)].filter(([name, current]) => current !== base?.get(name)).map(([name]) => name);
  const dirty = form => changedNames(form).some(name => !['csrfmiddlewaretoken', '_order_revision', 'operations-financial_revision'].includes(name));
  const notify = (text, error = false) => { message.hidden = false; message.textContent = text; message.classList.toggle('is-error', error); };
  const stepOf = field => field.closest('[data-step-key]')?.dataset.stepKey || 'order';
  const behavior = () => reduceMotion.matches ? 'instant' : 'smooth';
  function indicators() {
    const changed = new Set();
    forms.forEach(form => {
      const names = new Set(changedNames(form).filter(name => !name.endsWith('revision')));
      fields(form).forEach(f => { if (names.has(f.name)) changed.add(stepOf(f)); });
    });
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
  // 精簡列疊在內容上（order-compact-bar.js），停點要扣掉它的高度；隱藏時仍保有版面尺寸可量測。
  const compactBarHeight = () => root.querySelector('[data-order-compact-bar]')?.offsetHeight || 0;
  // 停點＝目前步驟區塊的頂端（使用者 2026-10-21）：進頁與從左側切換步驟，一律把該區最上方停在標頭與精簡列下方，
  // 不帶到區塊裡的欄位；頁面不夠長時捲到底即可，不在下方補空白。
  function stageTop() {
    const panel = tabbed ? panelOf(activeKey) : null;
    if (!panel || panel.hidden) return null;
    return Math.max(0, Math.round(window.scrollY + panel.getBoundingClientRect().top - headerHeight() - compactBarHeight() - 16));
  }
  function land(smooth) {
    // 原地更新後為了回到原位補的下方空間（見下方 restore）在換步驟時清掉。
    const room = root.querySelector('.order-steps');
    if (room) room.style.paddingBottom = '';
    const top = stageTop();
    if (top === null) return false;
    const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    window.scrollTo({top: Math.min(top, max), behavior: smooth ? behavior() : 'instant'});
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
    // 左側步驟：直接停在該區最上方（瞬間定位，不播捲動動畫；使用者 2026-10-21）。
    if (tab) { event.preventDefault(); activate(tab.dataset.stepLink, {focusTab: true}); if (tab.closest('[data-order-nav]')) showBar(false); return; }
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
  // 「已確認」勾選不鎖：勾錯取消勾選並存好後，該列解鎖可再修改（使用者 2026-10-17）。
  const LOCKED_PAYMENT_FIELDS = ['receipt_kind', 'received_amount', 'received_on', 'payment_method', 'receiving_account', 'card_principal', 'card_fee_charged', 'bank_card_fee'];
  function lockPayments(ids) {
    root.querySelectorAll('[data-payment-row]').forEach(row => {
      const id = row.querySelector('[name$="-id"]');
      if (!id?.value) return;
      const locked = ids.includes(id.value);
      if (!locked && !row.hasAttribute('data-payment-locked')) return;
      const prefix = id.name.slice(0, -2);
      LOCKED_PAYMENT_FIELDS.forEach(name => { const field = row.querySelector(`[name="${prefix}${name}"]`); if (field) field.disabled = locked; });
      row.classList.toggle('is-locked', locked); row.toggleAttribute('data-payment-locked', locked);
      row.querySelectorAll('[data-payment-locked-only], .receipt-amount .help-text').forEach(node => { node.hidden = !locked; });
    });
  }
  // 訂金步驟（使用者 2026-10-20 T-29）：已收妥即入帳，金額、日期、方式一起鎖定（訂單表單已不帶訂金欄位，10-21 T-44）；
  // 同步更新步驟摘要與側欄狀態，不必重新載入。
  const STEP_STATES = ['done', 'current', 'todo', 'optional', 'locked', 'reference'];
  function setStepState(node, state) {
    if (!node) return;
    STEP_STATES.forEach(name => node.classList.remove(`is-${name}`));
    node.classList.add(`is-${state}`);
  }
  function applyDeposit(state) {
    const form = root.querySelector('[data-deposit-step]');
    if (form) {
      form.classList.toggle('is-received', state.confirmed);
      ['amount', 'received_on', 'method'].forEach(name => { const field = form.elements.namedItem(`deposit-${name}`); if (field) field.disabled = state.locked; });
      const toggle = form.elements.namedItem('deposit-confirmed');
      if (toggle) toggle.checked = state.confirmed;
      const title = form.querySelector('[data-deposit-title]'); if (title) title.textContent = state.confirmed ? '訂金已收妥' : '訂金待收妥';
      const hint = form.querySelector('[data-deposit-hint]'); if (hint) hint.textContent = state.confirmed ? '已入帳；要修改先關掉。' : '收到款項後打開，即入帳。';
    }
    const panel = document.getElementById('panel-deposit');
    setStepState(panel, state.step_state);
    const summary = panel?.querySelector('.order-step__heading p'); if (summary) summary.textContent = state.summary;
    const badge = panel?.querySelector('.order-step__state');
    if (badge) { setStepState(badge, state.step_state); badge.textContent = state.step_state_label; }
    const headMarker = panel?.querySelector('.order-step__marker'); if (headMarker && state.step_marker_html != null) headMarker.innerHTML = state.step_marker_html;
    const tab = document.getElementById('tab-deposit');
    if (tab) {
      setStepState(tab, state.step_state);
      const label = tab.querySelector('.order-step-tab__state'); if (label) label.textContent = state.step_state_label;
      const marker = tab.querySelector('.order-step-tab__marker'); if (marker && state.step_marker_html != null) marker.innerHTML = state.step_marker_html;
    }
  }
  function merge(payload, savedForm, typed = new Set()) {
    if (payload.deposit) applyDeposit(payload.deposit);
    if (payload.customer_balance_due != null) {
      root.querySelectorAll('[data-customer-balance]').forEach(node => { node.textContent = '$' + Number(payload.customer_balance_due).toLocaleString('zh-TW'); });
    }
    if (payload.customer_receivable_total != null) {
      root.querySelectorAll('[data-customer-receivable]').forEach(node => { node.textContent = '$' + Number(payload.customer_receivable_total).toLocaleString('zh-TW'); });
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
      // 與頁面同一判斷（使用者 2026-10-21 T-56）：尾款可在交車表單一併登記時不擋；
      // 但頁面載入時沒有尾款欄位（當時已收妥）就無法在這裡收，改用含尾款的判斷。原因清單同步顯示在按鈕下方。
      const canCollect = Boolean(root.querySelector('#delivery-balance'));
      const blockers = Array.isArray(payload.delivery_blockers)
        ? (payload.delivery_collect_balance && !canCollect ? payload.delivery_blockers_strict : payload.delivery_blockers)
        : (payload.delivery_ready ? [] : [payload.delivery_blocker].filter(Boolean));
      const ready = blockers.length === 0;
      root.querySelectorAll('.delivery-completion-actions button[type="submit"]').forEach(button => {
        // 尾款實收不足（delivery-form.js 標記 balanceShort）時維持停用（使用者 2026-10-22 T-75）。
        button.disabled = !ready || button.dataset.balanceShort === '1'; button.setAttribute('aria-disabled', String(button.disabled));
        button.textContent = !ready ? '尚未符合交車條件' : (canCollect && payload.delivery_collect_balance ? '收尾款並完成交車' : '確認完成交付');
        if (!ready && blockers[0]) button.title = blockers[0];
        if (ready) { button.removeAttribute('title'); button.dataset.confirm = '確認完成交付嗎？完成後訂單與實體車輛將鎖定。'; }
      });
      root.querySelectorAll('[data-delivery-blockers]').forEach(list => {
        list.replaceChildren(...blockers.map(text => { const item = document.createElement('li'); item.textContent = text; return item; }));
        list.hidden = ready;
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
  function acceptRows(form, payload, sent) {
    for (const [name, savedValue] of Object.entries(payload.values || {})) {
      const field = form.elements.namedItem(name); if (field) field.value = savedValue;
    }
    // 新增明細轉為既有明細；已刪除列移除並重編，避免再次儲存產生重複。
    // 應收設定列也屬同一組明細，必須一起重編，否則新列會與它撞號，之後的修改被覆蓋。
    // 儲存期間才新增、或尚未存入的空白列保留排在最後，使用者正在輸入的內容不會消失。
    const renamed = new Map();
    [...form.querySelectorAll('[name$="-TOTAL_FORMS"]')].forEach(total => {
      const prefix = total.name.replace(/-TOTAL_FORMS$/, '');
      const idOf = row => [...row.querySelectorAll('input')].find(f => f.name.startsWith(prefix + '-') && f.name.endsWith('-id'));
      // 以 form 屬性併入、放在表單外的明細列（例如「訂金與費用」步驟的其他費用）也要一起重編。
      const rows = [...document.querySelectorAll('[data-dynamic-row],[data-payment-row],[data-payment-expectation],[data-form-row]')].filter(row => idOf(row)?.form === form);
      // 送出後才按刪除的列不算已刪除，留到下一次儲存。
      const plan = rowPlan(rows.map(row => {
        const del = row.querySelector('[name$="-DELETE"]');
        return {row, saved: Boolean(idOf(row).value), deletedWhenSent: Boolean(del?.checked && sent.get(del.name) === true)};
      }));
      plan.removed.forEach(({row}) => row.remove());
      plan.order.forEach(({row}, index) => {
        const old = idOf(row).name.slice(0, -2), next = `${prefix}-${index}-`;
        if (old === next) return;
        row.querySelectorAll('[name],[id],[for]').forEach(field => {
          ['name', 'id', 'for'].forEach(attr => {
            const text = field.getAttribute(attr); if (!text) return;
            field.setAttribute(attr, text.replace(old, next));
            if (attr === 'name') renamed.set(text, field.getAttribute(attr));
          });
        });
      });
      total.value = plan.order.length;
      const initial = form.elements.namedItem(prefix + '-INITIAL_FORMS'); if (initial) initial.value = plan.initial;
    });
    return renamed;
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
    // 表單外、以 form 屬性併入的欄位（例如頁首小卡的訂單來源）旁也顯示同一則儲存狀態。
    const mirrors = form.id ? [...document.querySelectorAll(`[data-autosave-mirror="${form.id}"]`)] : [];
    [node, ...mirrors].forEach(target => { target.textContent = text; target.dataset.state = state; });
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
  function onAutosaveInput(form, event) {
    if (event.isTrusted) touched.add(form);
    indicators();
    event.target.removeAttribute('aria-invalid');
    if (event.target.type !== 'file') schedule(form);
  }
  function onAutosaveChange(form, event) {
    const field = event.target;
    if (event.isTrusted) touched.add(form);
    if (field.type === 'checkbox' && field.checked && field.dataset.autosaveConfirm && !confirm(field.dataset.autosaveConfirm)) {
      field.checked = false; indicators(); return;
    }
    indicators();
    if (field.type === 'file') return;
    schedule(form, field.matches('select, [type="checkbox"], [type="radio"], [type="date"]') ? 250 : AUTOSAVE_DELAY);
  }
  // 放在表單外、以 form 屬性併入的欄位，事件不會冒泡到表單：改由文件層轉給所屬表單的自動儲存（使用者 2026-10-21）。
  const ownedOutside = event => {
    const form = event.target?.form;
    return form && forms.includes(form) && autosaving(form) && !form.contains(event.target) ? form : null;
  };
  document.addEventListener('input', event => { const form = ownedOutside(event); if (form) onAutosaveInput(form, event); });
  document.addEventListener('change', event => { const form = ownedOutside(event); if (form) onAutosaveChange(form, event); });
  forms.forEach(form => {
    bases.set(form, capture(form));
    if (!autosaving(form)) {
      form.addEventListener('input', indicators); form.addEventListener('change', indicators);
    } else {
      form.noValidate = true;
      form.dataset.autosave = '';
      form.addEventListener('input', event => onAutosaveInput(form, event));
      form.addEventListener('change', event => onAutosaveChange(form, event));
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
        // 重編後欄位會改名；送出後才打的字改用新名稱保留，基準仍取送出時的值（新名稱 → 送出時名稱）。
        const typedBefore = changedNames(form, sent);
        const renamed = acceptRows(form, payload, sent);
        const typedFrom = new Map(typedBefore.map(old => [renamed.get(old) ?? old, old]));
        const typed = new Set(typedFrom.keys());
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
        if (payload.origin_html) {
          // 訂單編號下方的來源標記（頁首含最後修改人；側欄與總覽對話框為精簡版）。
          document.querySelectorAll('[data-order-origin]').forEach(mark => {
            mark.outerHTML = payload.origin_html[mark.hasAttribute('data-order-origin-detail') ? 'detail' : 'compact'];
          });
        }
        if (payload.registration_html) {
          const completion = root.querySelector('[data-registration-completion]');
          if (completion) completion.outerHTML = payload.registration_html;
        }
        const base = capture(form);
        typedFrom.forEach((old, name) => base.set(name, sent.get(old)));
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
    // 原地送出（inplace-regions.js）不離開頁面，不必先存完其他區塊，也不解除離頁提醒。
    if (target.matches('[data-inplace-form]') && target.dataset.inplaceSuccess !== 'reload') return;
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
  // 跨步驟動作（完成交車、訂金入帳等）完成後重新載入：回到送出前的分頁與畫面位置，不跳到固定停點。
  const restore = tabbed ? window.DMISInplace?.takeRestore?.() : null;
  if (restore) {
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
    activate(panelOf(restore.tab) ? restore.tab : activeKey, {animate: false, url: false, announce: false});
    let touched = false;
    const align = () => {
      if (touched) return;
      const anchor = restore.anchor && document.getElementById(restore.anchor);
      const top = Math.max(0, Math.round(anchor ? window.scrollY + anchor.getBoundingClientRect().top - restore.offset : restore.y));
      // 完成後內容變短（例如表單換成入帳結果）時，比照 land() 在下方補足空白，才回得到同一個位置。
      const room = root.querySelector('.order-steps');
      if (room) room.style.paddingBottom = '';
      const short = top - (document.documentElement.scrollHeight - window.innerHeight);
      if (room && short > 0) room.style.paddingBottom = `${Math.ceil(short)}px`;
      window.scrollTo({top, behavior: 'instant'});
    };
    align();
    const resized = 'ResizeObserver' in window ? new ResizeObserver(align) : null;
    const stop = () => { touched = true; resized?.disconnect(); };
    ['wheel', 'touchstart', 'keydown', 'pointerdown'].forEach(type => window.addEventListener(type, stop, {once: true, passive: true}));
    resized?.observe(root);
    window.addEventListener('load', () => { align(); setTimeout(stop, 1500); }, {once: true});
    document.fonts?.ready.then(align);
    updateOverflow();
  } else if (tabbed) {
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
