(function () {
  'use strict';
  const MAX_BYTES = 8 * 1024 * 1024;

  async function validateFile(file) {
    if (!file || !file.size) return '圖片是空檔案，請重新選擇。';
    if (file.size > MAX_BYTES) return '圖片最多 8 MB，請重新選擇。';
    if (file.type && !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) return '請使用 JPEG、PNG 或 WebP 圖片。';
    const bytes = new Uint8Array(await file.slice(0, 12).arrayBuffer());
    const starts = values => values.every((value, i) => bytes[i] === value);
    const webp = starts([82, 73, 70, 70]) && [87, 69, 66, 80].every((v, i) => bytes[i + 8] === v);
    return starts([255, 216, 255]) || starts([137, 80, 78, 71, 13, 10, 26, 10]) || webp
      ? '' : '檔案內容不是 JPEG、PNG 或 WebP 圖片，請重新選擇。';
  }

  function linkError(value) {
    let parsed;
    try { parsed = new URL(value); } catch (_) { return '圖片連結格式不正確，請貼上完整網址（含 https://）。'; }
    return ['http:', 'https:'].includes(parsed.protocol) ? '' : '只接受 http:// 或 https:// 開頭的圖片連結。';
  }

  function createCell(cell, deps) {
    const q = selector => cell.querySelector(selector);
    const media = q('[data-photo-drop]'), img = q('[data-photo-img]'), message = q('[data-photo-message]');
    const fileInput = q('[data-photo-file]'), fileLabel = q('[data-photo-file-label]'), badge = q('[data-photo-badge]');
    const linkToggle = q('[data-photo-link-toggle]'), linkForm = q('[data-photo-link-form]'), urlInput = q('[data-photo-url]');
    const confirm = q('[data-photo-confirm]');
    let saved = img.hidden ? '' : img.getAttribute('src') || '', objectUrl = '', pending = null, busy = false;

    function setState(state, text) {
      cell.dataset.state = state;
      message.textContent = text || '';
      confirm.hidden = state !== 'confirm';
    }
    function release() {
      if (objectUrl) { deps.URL.revokeObjectURL(objectUrl); objectUrl = ''; }
    }
    function show(src) {
      if (src) { img.setAttribute('src', src); img.hidden = false; } else { img.removeAttribute('src'); img.hidden = true; }
    }
    function restore() { release(); show(saved); pending = null; }
    function openLink(open) {
      linkForm.hidden = !open;
      linkToggle.setAttribute('aria-expanded', String(open));
      if (open) urlInput.focus();
    }

    async function submit(payload) {
      busy = true; pending = null;
      setState('saving', payload.kind === 'url' ? '正在下載並檢查圖片…' : '正在上傳…');
      const body = new deps.FormData();
      body.append('expected', cell.dataset.expected || '');
      body.append(payload.kind === 'url' ? 'url' : 'image', payload.value);
      try {
        const response = await deps.fetch(cell.dataset.saveUrl, {
          method: 'POST', body, credentials: 'same-origin', headers: {'X-CSRFToken': deps.token},
        });
        let data = {};
        try { data = await response.json(); } catch (_) { /* 非 JSON 回應用通用訊息 */ }
        if (!response.ok || !data.ok) {
          throw Object.assign(new Error('save failed'), {userMessage: data.error || '儲存失敗，請稍後再試或改用上傳檔案。'});
        }
        const wasMissing = cell.dataset.hasPhoto !== '1';
        release();
        saved = data.thumb; show(saved);
        cell.dataset.expected = data.image; cell.dataset.hasPhoto = '1';
        cell.classList.add('is-fresh');
        badge.textContent = '已有圖'; fileLabel.textContent = '換圖';
        urlInput.value = ''; openLink(false);
        setState('saved', data.replaced ? '已換上新圖片。' : '已儲存。');
        deps.onSaved(cell, wasMissing);
      } catch (error) {
        restore();
        setState('error', error.userMessage || '無法連線到系統，請檢查網路後再試。');
      } finally {
        busy = false;
      }
    }

    async function accept(payload) {
      if (busy) return;
      restore();
      const error = payload.kind === 'url' ? linkError(payload.value) : await validateFile(payload.value);
      if (error) { setState('error', error); return; }
      if (payload.kind === 'url') show(payload.value);
      else { objectUrl = deps.URL.createObjectURL(payload.value); show(objectUrl); }
      if (cell.dataset.hasPhoto === '1') {
        pending = payload;
        setState('confirm', '');
        q('[data-photo-confirm-yes]').focus();
      } else {
        await submit(payload);
      }
    }

    media.addEventListener('click', () => {
      if (!busy && cell.dataset.hasPhoto !== '1') fileInput.click?.();
    });
    media.addEventListener('keydown', event => {
      if ((event.key === 'Enter' || event.key === ' ') && !busy && cell.dataset.hasPhoto !== '1') {
        event.preventDefault();
        fileInput.click?.();
      }
    });
    fileInput.addEventListener('change', () => {
      const file = fileInput.files[0];
      fileInput.value = '';
      if (file) accept({kind: 'file', value: file});
    });
    linkToggle.addEventListener('click', () => openLink(linkForm.hidden));
    linkForm.addEventListener('submit', event => {
      event.preventDefault();
      const value = urlInput.value.trim();
      if (value) accept({kind: 'url', value});
    });
    urlInput.addEventListener('keydown', event => { if (event.key === 'Escape') { openLink(false); linkToggle.focus(); } });
    q('[data-photo-confirm-yes]').addEventListener('click', () => { if (pending) submit(pending); });
    q('[data-photo-confirm-no]').addEventListener('click', () => { restore(); setState('idle', ''); media.focus(); });
    media.addEventListener('dragover', event => {
      if (busy || ![...(event.dataTransfer?.types || [])].some(type => type === 'Files' || type === 'text/uri-list')) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'copy';
      cell.classList.add('is-over');
    });
    media.addEventListener('dragleave', () => cell.classList.remove('is-over'));
    media.addEventListener('drop', event => {
      cell.classList.remove('is-over');
      const transfer = event.dataTransfer;
      if (!transfer) return;
      event.preventDefault();
      const file = transfer.files && transfer.files[0];
      const link = (transfer.getData('text/uri-list') || transfer.getData('text/plain') || '').split('\n')[0].trim();
      if (file) accept({kind: 'file', value: file});
      else if (link) accept({kind: 'url', value: link});
    });
    media.addEventListener('paste', event => {
      const data = event.clipboardData;
      if (!data) return;
      const file = [...(data.files || [])][0];
      const text = (data.getData('text') || '').trim();
      if (file || text) event.preventDefault();
      if (file) accept({kind: 'file', value: file});
      else if (text) accept({kind: 'url', value: text});
    });
    return {accept, submit, state: () => cell.dataset.state};
  }

  function createBoard(board, env) {
    const cells = [...board.querySelectorAll('[data-photo-cell]')];
    const total = Number(board.querySelector('[data-photo-total]').textContent) || 0;
    const toggle = board.querySelector('[data-photo-missing-only]');
    const done = board.querySelector('[data-photo-done]');
    let missing = Number(board.querySelector('[data-photo-missing]').textContent) || 0;

    function refresh() {
      const percent = total ? Math.round((total - missing) * 100 / total) : 100;
      board.querySelector('[data-photo-missing]').textContent = missing;
      board.querySelector('[data-photo-percent]').textContent = percent;
      const ring = board.querySelector('[data-photo-ring]');
      if (ring) ring.style.strokeDasharray = `${percent} 100`;
      done.hidden = !(missing === 0 && board.hasAttribute('data-missing-only'));
    }
    function onSaved(cell, wasMissing) {
      if (!wasMissing) return;
      missing -= 1;
      const model = cell.closest('[data-photo-model]');
      const left = Number(model.dataset.missing) - 1;
      model.dataset.missing = left;
      model.classList.add('is-fresh');
      const all = model.querySelectorAll('[data-photo-cell]').length;
      model.querySelector('[data-photo-model-count]').textContent = left ? `缺 ${left}／${all}` : '已齊全';
      const group = cell.closest('[data-photo-group]');
      group.dataset.missing = Number(group.dataset.missing) - 1;
      group.classList.add('is-fresh');
      group.querySelector('[data-photo-group-missing]').textContent = group.dataset.missing;
      const chip = board.querySelector(`[data-photo-brand-link="${group.id.replace('brand-', '')}"] [data-photo-brand-missing]`);
      if (chip) chip.textContent = group.dataset.missing;
      refresh();
    }
    function setMissingOnly(on) {
      board.querySelectorAll('.is-fresh').forEach(node => node.classList.remove('is-fresh'));
      board.toggleAttribute('data-missing-only', on);
      const url = new env.URL(env.location.href);
      if (on) url.searchParams.set('missing', '1'); else url.searchParams.delete('missing');
      env.history.replaceState(null, '', url);
      board.querySelectorAll('.photo-board__search input[name="missing"]').forEach(node => node.remove());
      if (on) {
        const hidden = env.document.createElement('input');
        Object.assign(hidden, {type: 'hidden', name: 'missing', value: '1'});
        board.querySelector('.photo-board__search').append(hidden);
      }
      refresh();
    }
    const token = board.querySelector('input[name="csrfmiddlewaretoken"]').value;
    const controllers = cells.map(cell => createCell(cell, {fetch: env.fetch.bind(env), FormData: env.FormData, URL: env.URL, token, onSaved}));
    toggle.addEventListener('change', () => setMissingOnly(toggle.checked));
    let depth = 0;
    env.addEventListener('dragenter', event => {
      if (![...(event.dataTransfer?.types || [])].includes('Files')) return;
      depth += 1; board.classList.add('is-dragging');
    });
    env.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) board.classList.remove('is-dragging'); });
    env.addEventListener('drop', event => {
      depth = 0; board.classList.remove('is-dragging');
      if ([...(event.dataTransfer?.types || [])].includes('Files')) event.preventDefault();  // 沒放進格子時不讓瀏覽器開啟檔案
    });
    env.addEventListener('dragover', event => { if ([...(event.dataTransfer?.types || [])].includes('Files')) event.preventDefault(); });
    refresh();
    return {controllers, setMissingOnly, onSaved, missing: () => missing};
  }

  if (typeof module !== 'undefined') module.exports = {validateFile, linkError, createCell, createBoard, MAX_BYTES};
  if (typeof document === 'undefined') return;
  const board = document.querySelector('[data-photo-board]');
  if (board) createBoard(board, window);
}());
