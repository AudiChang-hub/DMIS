(function () {
  'use strict';
  const MAX_BYTES = 8 * 1024 * 1024;
  async function validateFile(file) {
    if (!file.size) return '圖片是空檔案，請重新選擇。';
    if (file.size > MAX_BYTES) return '圖片最多 8 MB，請重新選擇。';
    if (file.type && !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      return '請使用 JPEG、PNG 或 WebP 圖片。';
    }
    const bytes = new Uint8Array(await file.slice(0, 12).arrayBuffer());
    const starts = values => values.every((value, i) => bytes[i] === value);
    const jpeg = starts([255, 216, 255]);
    const png = starts([137, 80, 78, 71, 13, 10, 26, 10]);
    const webp = starts([82, 73, 70, 70]) && [87, 69, 66, 80].every((v, i) => bytes[i + 8] === v);
    return jpeg || png || webp ? '' : '檔案內容不是 JPEG、PNG 或 WebP 圖片，請重新選擇。';
  }

  function attach(root, env) {
    const input = root.querySelector('input[type="file"]');
    const image = root.querySelector('[data-preview-image]');
    const placeholder = root.querySelector('[data-preview-placeholder]');
    const status = root.querySelector('[data-preview-status]');
    const cancel = root.querySelector('[data-preview-cancel]');
    const remove = root.querySelector('input[type="checkbox"]');
    const urlInput = root.querySelector('input[type="url"]');
    const options = urlInput ? [...root.querySelectorAll('[data-source-option]')] : [];
    const original = image.getAttribute('src') || '';
    let generation = 0, objectUrl = '', loader = null, urlTimer = 0;
    const describedBy = input.getAttribute('aria-describedby') || '';
    input.setAttribute('aria-describedby', `${describedBy} ${status.id}`.trim());

    function release() {
      if (loader) { loader.onload = null; loader.onerror = null; loader = null; }
      if (objectUrl) { env.URL.revokeObjectURL(objectUrl); objectUrl = ''; }
    }
    function originalImage() {
      if (original) image.setAttribute('src', original);
      else image.removeAttribute('src');
      image.hidden = !original;
      placeholder.hidden = !!original;
    }
    function message(text, state) {
      status.textContent = text;
      root.dataset.previewState = state;
      cancel.hidden = state === 'saved';
    }
    function validity(text) {
      input.setCustomValidity(text);
      if (text) input.setAttribute('aria-invalid', 'true');
      else input.removeAttribute('aria-invalid');
    }
    function mode() {
      return options.find(option => option.checked)?.value || 'file';
    }
    function clearUrl() {
      if (!urlInput) return;
      env.clearTimeout?.(urlTimer);
      urlInput.value = ''; urlInput.setCustomValidity(''); urlInput.removeAttribute('aria-invalid');
    }
    function reset() {
      generation += 1;
      release(); originalImage(); input.value = ''; validity(''); clearUrl();
      if (urlInput) root.dataset.sourceMode = mode();
      if (remove) remove.checked = false;
      message(original ? '目前顯示已儲存的圖片。' : '尚無已儲存的圖片。', 'saved');
    }
    function failed(text) {
      release(); originalImage(); input.value = ''; validity(text);
      message(text, 'error');
    }
    async function change() {
      const file = input.files[0];
      generation += 1;
      const current = generation;
      release(); originalImage(); clearUrl();
      if (remove) remove.checked = false;
      if (!file) { reset(); return; }
      validity('圖片檢查中，請稍候。');
      message('正在檢查圖片，尚未上傳…', 'checking');
      try {
        const error = await validateFile(file);
        if (current !== generation) return;
        if (error) { failed(error); return; }
        objectUrl = env.URL.createObjectURL(file);
        loader = new env.Image();
        loader.onload = () => {
          if (current !== generation) return;
          image.src = objectUrl; image.hidden = false; placeholder.hidden = true;
          loader.onload = null; loader.onerror = null; loader = null;
          validity(''); message(`尚未儲存：${file.name}`, 'pending');
        };
        loader.onerror = () => {
          if (current === generation) failed('無法讀取這張圖片，請選擇完整且有效的圖片檔案。');
        };
        loader.src = objectUrl;
      } catch (_) {
        if (current === generation) failed('無法讀取這張圖片，請重新選擇。');
      }
    }
    function removeChange() {
      const checked = remove.checked;
      reset();
      if (checked) {
        remove.checked = true; image.hidden = true; placeholder.hidden = false;
        message('尚未儲存：儲存後移除此車色圖片，原始檔仍保留。', 'pending');
      }
    }
    function urlFailed(text) {
      urlInput.setCustomValidity(text); urlInput.setAttribute('aria-invalid', 'true');
      message(text, 'error');
    }
    function urlChange() {
      env.clearTimeout?.(urlTimer);
      generation += 1;
      const current = generation;
      release(); originalImage(); input.value = ''; validity('');
      urlInput.setCustomValidity(''); urlInput.removeAttribute('aria-invalid');
      if (remove) remove.checked = false;
      const value = urlInput.value.trim();
      if (!value) { message(original ? '目前顯示已儲存的圖片。' : '尚無已儲存的圖片。', 'saved'); return; }
      let parsed;
      try { parsed = new URL(value); } catch (_) { urlFailed('圖片連結格式不正確，請貼上完整網址（含 https://）。'); return; }
      if (!['http:', 'https:'].includes(parsed.protocol)) { urlFailed('只接受 http:// 或 https:// 開頭的圖片連結。'); return; }
      message('正在載入連結預覽…', 'checking');
      loader = new env.Image();
      loader.referrerPolicy = 'no-referrer';
      loader.onload = () => {
        if (current !== generation) return;
        image.src = value; image.hidden = false; placeholder.hidden = true;
        loader.onload = null; loader.onerror = null; loader = null;
        message(`尚未儲存：套用時會從 ${parsed.hostname} 下載這張圖片並存入系統。`, 'pending');
      };
      loader.onerror = () => {
        if (current !== generation) return;
        loader.onload = null; loader.onerror = null; loader = null;
        message(root.querySelector('.catalog-remote-error')
          ? '瀏覽器也無法預覽這個連結；請改貼圖片本身的網址，或改用上傳檔案。'
          : '瀏覽器無法預覽這個連結（可能不是圖片網址，或對方網站不允許外部顯示）。仍可套用，系統會下載並檢查；失敗會在這裡說明。', 'warning');
      };
      loader.src = value;
    }
    function switchMode() {
      const next = mode();
      root.dataset.sourceMode = next;
      reset();
      (next === 'url' ? urlInput : input).focus();
    }
    if (urlInput) {
      urlInput.setAttribute('aria-describedby', `${urlInput.getAttribute('aria-describedby') || ''} ${status.id}`.trim());
      urlInput.addEventListener('change', urlChange);
      urlInput.addEventListener('input', () => {
        env.clearTimeout?.(urlTimer);
        urlTimer = env.setTimeout ? env.setTimeout(urlChange, 400) : 0;
      });
      options.forEach(option => option.addEventListener('change', switchMode));
      root.dataset.sourceMode = mode();
    }
    input.addEventListener('change', change);
    input.addEventListener('invalid', () => {
      const details = root.closest('details');
      if (details) details.open = true;
    });
    cancel.addEventListener('click', () => { reset(); (urlInput && mode() === 'url' ? urlInput : input).focus(); });
    if (remove) remove.addEventListener('change', removeChange);
    if (remove?.checked) removeChange();
    else if (urlInput?.value.trim()) urlChange();
    else message(original ? '目前顯示已儲存的圖片。' : '尚無已儲存的圖片。', 'saved');
    return {reset, dispose() { generation += 1; release(); }};
  }

  if (typeof module !== 'undefined') module.exports = {validateFile, attach, MAX_BYTES};
  if (typeof document === 'undefined') return;
  // 儲存後表單會原地換成伺服器新版（inplace-regions.js）：舊預覽釋放，新卡片重新綁定。
  let controllers = [];
  function bindAll() {
    controllers.filter(item => !item.root.isConnected).forEach(item => item.controller.dispose());
    controllers = controllers.filter(item => item.root.isConnected);
    const fresh = [...document.querySelectorAll('[data-catalog-image-preview]')]
      .filter(root => !controllers.some(item => item.root === root))
      .map(root => ({root, controller: attach(root, window)}));
    controllers.push(...fresh);
    new Set(fresh.map(({root}) => root.closest('form'))).forEach(form => {
      if (!form || form.dataset.previewResetBound) return;
      form.dataset.previewResetBound = '1';
      form.addEventListener('reset', () => window.setTimeout(() => {
        controllers.filter(item => item.root.closest('form') === form).forEach(item => item.controller.reset());
      }, 0));
    });
  }
  bindAll();
  document.addEventListener('inplace:updated', bindAll);
  window.addEventListener('pagehide', event => {
    if (!event.persisted) controllers.forEach(item => item.controller.dispose());
  });
}());
