/* 資料維護區草稿保留（使用者 2026-10-15）：輸入隨打隨存在這台裝置，離開再回來不會不見；
   這些設定會影響計價，仍要按「套用」才生效。密碼、檔案與隱藏欄位不保存。 */
(() => {
  const PREFIX = 'dmis-form-draft:';
  const MAX_AGE = 7 * 24 * 60 * 60 * 1000;
  const storage = (() => {
    try { const probe = '__dmis_probe__'; localStorage.setItem(probe, '1'); localStorage.removeItem(probe); return localStorage; } catch (_error) { return null; }
  })();
  const SKIPPED_TYPES = new Set(['password', 'file', 'hidden', 'submit', 'button', 'reset', 'image']);
  const keep = field => field.name && !field.disabled && !SKIPPED_TYPES.has(field.type) && field.name !== 'csrfmiddlewaretoken' && !field.closest('[data-no-draft]');
  const fieldValue = field => field.type === 'checkbox' || field.type === 'radio' ? field.checked : field.tagName === 'SELECT' && field.multiple ? [...field.selectedOptions].map(o => o.value) : field.value;
  const snapshot = form => [...form.elements].filter(keep).map((field, index) => [`${field.name}#${index}`, fieldValue(field)]);
  const time = stamp => new Date(stamp).toLocaleString('zh-TW', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false});

  function eligible(form) {
    if ((form.getAttribute('method') || '').toLowerCase() !== 'post') return false;
    if (form.hasAttribute('data-no-draft') || form.closest('[data-order-workspace]') || form.target === '_blank') return false;
    return [...form.elements].some(field => keep(field) && ['text', 'number', 'date', 'email', 'tel', 'url', 'textarea', 'select-one', 'select-multiple', 'search'].includes(field.type));
  }

  function setup(form, index) {
    const key = `${PREFIX}${location.pathname}${location.search}:${form.getAttribute('action') || ''}:${index}`;
    const initial = JSON.stringify(snapshot(form));
    let timer = null;
    const save = () => {
      const current = JSON.stringify(snapshot(form));
      try {
        if (current === initial) storage.removeItem(key);
        else storage.setItem(key, JSON.stringify({savedAt: Date.now(), values: current}));
      } catch (_error) { /* 儲存空間滿或被封鎖時不影響填寫 */ }
    };
    form.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(save, 400); });
    form.addEventListener('change', save);
    // 按「套用」送出後清掉草稿；伺服器驗證失敗時頁面會帶回剛送出的內容，不會遺失。
    form.addEventListener('submit', () => { clearTimeout(timer); try { storage.removeItem(key); } catch (_error) { /* 略過 */ } });

    let draft = null;
    try { draft = JSON.parse(storage.getItem(key) || 'null'); } catch (_error) { draft = null; }
    if (!draft || Date.now() - draft.savedAt > MAX_AGE || draft.values === initial) {
      try { storage.removeItem(key); } catch (_error) { /* 略過 */ }
      return;
    }
    // 伺服器帶回驗證錯誤時以畫面上剛送出的內容為準，不覆蓋。
    if (form.querySelector('.errorlist, .field-error, [aria-invalid="true"]')) return;
    const values = new Map(JSON.parse(draft.values));
    [...form.elements].filter(keep).forEach((field, position) => {
      const stored = values.get(`${field.name}#${position}`);
      if (stored === undefined) return;
      if (field.type === 'checkbox' || field.type === 'radio') field.checked = Boolean(stored);
      else if (Array.isArray(stored)) [...field.options].forEach(option => { option.selected = stored.includes(option.value); });
      else field.value = stored;
      field.dispatchEvent(new Event('input', {bubbles: true}));
      field.dispatchEvent(new Event('change', {bubbles: true}));
    });
    const banner = document.createElement('div');
    banner.className = 'form-draft-banner';
    banner.setAttribute('role', 'status');
    banner.innerHTML = '<span><strong>已帶回上次還沒套用的輸入</strong><small></small></span><button type="button" class="button ghost compact">捨棄草稿</button>';
    banner.querySelector('small').textContent = `${time(draft.savedAt)} 保留在這台裝置；按「套用」後才會生效。`;
    banner.querySelector('button').addEventListener('click', () => {
      try { storage.removeItem(key); } catch (_error) { /* 略過 */ }
      location.reload();
    });
    form.prepend(banner);
  }

  if (!storage) return;
  document.querySelectorAll('main form').forEach((form, index) => { if (eligible(form)) setup(form, index); });
})();
