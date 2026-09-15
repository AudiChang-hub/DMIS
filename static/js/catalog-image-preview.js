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
    const original = image.getAttribute('src') || '';
    let generation = 0, objectUrl = '', loader = null;
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
    function reset() {
      generation += 1;
      release(); originalImage(); input.value = ''; validity('');
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
      release(); originalImage();
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
    input.addEventListener('change', change);
    input.addEventListener('invalid', () => {
      const details = root.closest('details');
      if (details) details.open = true;
    });
    cancel.addEventListener('click', () => { reset(); input.focus(); });
    if (remove) remove.addEventListener('change', removeChange);
    if (remove?.checked) removeChange();
    else message(original ? '目前顯示已儲存的圖片。' : '尚無已儲存的圖片。', 'saved');
    return {reset, dispose() { generation += 1; release(); }};
  }

  if (typeof module !== 'undefined') module.exports = {validateFile, attach, MAX_BYTES};
  if (typeof document === 'undefined') return;
  const controllers = [...document.querySelectorAll('[data-catalog-image-preview]')]
    .map(root => ({root, controller: attach(root, window)}));
  const forms = new Set(controllers.map(({root}) => root.closest('form')));
  forms.forEach(form => form?.addEventListener('reset', () => window.setTimeout(() => {
    controllers.filter(item => item.root.closest('form') === form).forEach(item => item.controller.reset());
  }, 0)));
  window.addEventListener('pagehide', event => {
    if (!event.persisted) controllers.forEach(item => item.controller.dispose());
  });
}());
