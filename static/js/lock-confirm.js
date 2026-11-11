/* 鎖定前確認卡（T-130 第 3 層，使用者 2026-11-07）：條件齊全時不再自動完成並鎖定，
 * 先列出系統實際存下的值，按「確認完成」才送出；按取消維持未完成，可以繼續修改。
 *
 * 用法：
 * - 送出按鈕加 data-lock-confirm="標題"（選填 data-lock-lead、data-lock-confirm-label）。
 *   值的來源二選一：表單內 <dl data-lock-values>（伺服器依資料庫現值輸出），
 *   或 data-lock-fields="欄位名 …"（取畫面上即將送出的值；data-lock-required 列出不可空白的欄位）。
 * - 勾選類（確認入帳）由 order-workspace.js 呼叫 DMISLockConfirm.fromElement(勾選框)。
 * - 領牌不再使用確認卡：領牌日與車牌填好存檔即自動完成，之後仍可修改（使用者 2026-11-11 T-147）。
 */
(() => {
  const fieldName = name => name.replace(/^.*-/, '');
  const formatDate = value => value.replaceAll('-', '/');
  function labelText(field) {
    const label = (field.id && document.querySelector(`label[for="${CSS.escape(field.id)}"]`)) || field.labels?.[0];
    const text = label?.textContent || field.getAttribute('aria-label') || field.closest('[data-label]')?.dataset.label || '';
    return text.replace(/必填|選填|（選填）/g, '').replace(/\s+/g, ' ').trim();
  }
  function shownValue(field) {
    if (!field) return '';
    if (field.tagName === 'SELECT') {
      const option = field.selectedOptions[0];
      return option && option.value !== '' ? option.textContent.trim() : '';
    }
    const value = (field.value || '').trim();
    if (!value) return '';
    if (field.type === 'date') return formatDate(value);
    if (field.type === 'datetime-local') return formatDate(value.replace('T', ' '));
    if (field.inputMode === 'numeric' || field.type === 'number') {
      const amount = Number(value.replace(/,/g, ''));
      return Number.isFinite(amount) ? `${amount.toLocaleString('zh-TW')} 元` : value;
    }
    return value;
  }
  function findField(scope, name) {
    // 表單外以 form 屬性併入的欄位（例如交車表單的尾款）也算：表單用 elements 取。
    const list = scope.elements ? [...scope.elements] : [...scope.querySelectorAll('[name]')];
    return list.find(field => field.name && field.type !== 'hidden' && (field.name === name || fieldName(field.name) === name));
  }
  // 依按鈕或勾選框上的設定組出要列的值。
  function rowsFor(trigger) {
    // 收款明細每一列各自一組欄位，只取同一列的值。
    const scope = trigger.closest('[data-lock-scope], [data-payment-row]') || trigger.form || trigger.closest('form') || document;
    const fixed = scope.querySelector('dl[data-lock-values]');
    if (fixed) {
      return [...fixed.querySelectorAll(':scope > div')].map(item => ({
        label: item.querySelector('dt')?.textContent.trim() || '',
        value: item.querySelector('dd')?.textContent.trim() || '',
        missing: item.hasAttribute('data-missing'),
      }));
    }
    // data-lock-required：「欄位」一律必填；「欄位?條件欄位」＝條件欄位有值時才必填（例如有收尾款才要收款日期）。
    const rules = (trigger.dataset.lockRequired || '').split(/\s+/).filter(Boolean).map(rule => rule.split('?'));
    const needed = name => rules.some(([field, when]) => field === name && (!when || shownValue(findField(scope, when)) !== ''));
    return (trigger.dataset.lockFields || '').split(/\s+/).filter(Boolean).map(name => {
      const field = findField(scope, name);
      if (!field || field.closest('[hidden]')) return null;
      const value = shownValue(field);
      return {label: labelText(field) || name, value, missing: needed(name) && !value, field};
    }).filter(Boolean);
  }

  let dialog = null;
  function build() {
    dialog = document.createElement('dialog');
    dialog.className = 'lock-confirm';
    dialog.setAttribute('aria-labelledby', 'lock-confirm-title');
    dialog.setAttribute('aria-describedby', 'lock-confirm-lead');
    dialog.innerHTML = `
      <div class="lock-confirm__sheet">
        <div class="lock-confirm__head">
          <span class="lock-confirm__seal" aria-hidden="true"><svg viewBox="0 0 24 24" width="22" height="22"><rect x="5" y="10.5" width="14" height="10" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></span>
          <div>
            <p class="lock-confirm__eyebrow">確認後會鎖定</p>
            <h2 class="lock-confirm__title" id="lock-confirm-title"></h2>
          </div>
        </div>
        <p class="lock-confirm__lead" id="lock-confirm-lead"></p>
        <dl class="lock-confirm__values"></dl>
        <p class="lock-confirm__missing" role="alert" hidden></p>
        <div class="lock-confirm__actions">
          <button type="button" class="button ghost" data-lock-cancel></button>
          <button type="button" class="button primary" data-lock-ok></button>
        </div>
      </div>`;
    document.body.append(dialog);
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close('cancel'); });
    return dialog;
  }
  let pending = null;
  function ask({title, lead = '', rows = [], confirmLabel = '確認完成', cancelLabel = '先不要，繼續修改'}) {
    if (pending) return Promise.resolve(false);
    const card = dialog || build();
    card.querySelector('.lock-confirm__title').textContent = title;
    card.querySelector('.lock-confirm__lead').textContent = lead;
    card.querySelector('.lock-confirm__lead').hidden = !lead;
    const list = card.querySelector('.lock-confirm__values');
    list.replaceChildren(...rows.map(row => {
      const item = document.createElement('div');
      item.className = row.missing ? 'is-missing' : '';
      const term = document.createElement('dt'); term.textContent = row.label;
      const value = document.createElement('dd'); value.textContent = row.value || '未填';
      item.append(term, value);
      return item;
    }));
    list.hidden = rows.length === 0;
    const missing = rows.filter(row => row.missing);
    const note = card.querySelector('.lock-confirm__missing');
    note.hidden = missing.length === 0;
    note.textContent = missing.length ? `請先填寫${missing.map(row => `「${row.label}」`).join('、')}，才能確認。` : '';
    const ok = card.querySelector('[data-lock-ok]');
    const cancel = card.querySelector('[data-lock-cancel]');
    ok.textContent = confirmLabel; cancel.textContent = missing.length ? '回去填寫' : cancelLabel;
    ok.disabled = missing.length > 0;
    return new Promise(resolve => {
      pending = resolve;
      const finish = result => {
        ok.onclick = null; cancel.onclick = null; pending = null;
        resolve(result);
        if (!result && missing[0]?.field) { missing[0].field.focus(); missing[0].field.scrollIntoView({block: 'center', behavior: 'instant'}); }
      };
      ok.onclick = () => { card.close('ok'); };
      cancel.onclick = () => { card.close('cancel'); };
      card.addEventListener('close', () => finish(card.returnValue === 'ok'), {once: true});
      card.returnValue = '';
      card.showModal();
      (missing.length ? cancel : ok).focus();
    });
  }
  const fromElement = trigger => ask({
    title: trigger.dataset.lockConfirm,
    lead: trigger.dataset.lockLead || '',
    rows: rowsFor(trigger),
    confirmLabel: trigger.dataset.lockConfirmLabel || '確認完成',
  });

  // 送出按鈕：在捕捉階段先攔下（早於 form-feedback.js 的重複送出鎖與原地送出），確認後再照原按鈕送出一次。
  document.addEventListener('submit', event => {
    const button = event.submitter;
    if (!button?.dataset.lockConfirm) return;
    if (button.dataset.lockConfirmed === '1') { delete button.dataset.lockConfirmed; return; }
    event.preventDefault();
    event.stopImmediatePropagation();
    const form = event.target;
    fromElement(button).then(ok => {
      if (!ok) return;
      button.dataset.lockConfirmed = '1';
      form.requestSubmit(button);
    });
  }, true);

  window.DMISLockConfirm = {ask, fromElement, rowsFor};
})();
