(() => {
  const show = (url, name, pdf) => {
    const dialog = document.createElement('dialog'); dialog.className = 'document-preview-dialog';
    const close = document.createElement('button'); close.type = 'button'; close.textContent = '關閉預覽'; close.className = 'button ghost';
    const content = document.createElement(pdf ? 'iframe' : 'img'); content.src = url; content.title = name; content.alt = name;
    close.addEventListener('click', () => dialog.close()); dialog.addEventListener('close', () => dialog.remove());
    dialog.append(close, content); document.body.append(dialog); dialog.showModal(); close.focus();
  };
  const scan = () => document.querySelectorAll('a[data-preview-name]:not([data-preview-ready])').forEach(link => {
    link.dataset.previewReady = '1'; const url = new URL(link.href, location.href);
    if (url.origin !== location.origin) return;
    const name = link.dataset.previewName || link.textContent; const pdf = /\.pdf$/i.test(name);
    const image = /\.(jpe?g|png|webp)$/i.test(name);
    if (!pdf && !image) { link.classList.add('document-file-tile'); return; }
    url.searchParams.set('preview', '1');
    const button = document.createElement('button'); button.type = 'button'; button.className = 'document-thumbnail'; button.setAttribute('aria-label', `放大 ${name}`);
    if (image) { const img = document.createElement('img'); img.src = url.href; img.alt = name; img.loading = 'lazy'; button.append(img); }
    else { const frame = document.createElement('iframe'); frame.src = `${url.href}#toolbar=0&navpanes=0`; frame.title = `${name} 第一頁`; frame.loading = 'lazy'; frame.tabIndex = -1; button.append(frame); }
    button.addEventListener('click', () => show(url.href, name, pdf));
    const card = document.createElement('div'); card.className = 'document-card';
    const title = document.createElement('span'); title.className = 'document-card-title'; title.textContent = link.dataset.previewLabel || link.textContent;
    link.before(card); card.append(title, button, link);
    link.textContent = '下載檔案'; link.className = 'document-download'; link.setAttribute('download', name);
    link.removeAttribute('target');
  });
  scan(); new MutationObserver(scan).observe(document.body, {childList: true, subtree: true});
  document.querySelectorAll('[data-trade-in-uploads]').forEach(section => {
    const form = section.closest('form');
    const field = form.querySelector('[name="trade_in_intent"]');
    const same = form.querySelector('[name="old_owner_same_as_owner"]');
    const update = () => { section.hidden = field?.value !== 'yes' || same?.checked; section.querySelectorAll('input[type="file"]').forEach(input => input.disabled = section.hidden); };
    field?.addEventListener('change', update); same?.addEventListener('change', update); update();
  });
  const blobs = new Set();
  document.querySelectorAll('input[type="file"]').forEach(input => {
    if (!['owner_bankbook', 'old_id_front', 'old_id_back', 'old_bankbook', 'installment_document', 'supplement_documents'].includes(input.name)) return;
    const previews = document.createElement('div'); previews.className = 'document-card-list upload-previews'; input.after(previews);
    let urls = [];
    input.addEventListener('change', () => {
      urls.forEach(url => { URL.revokeObjectURL(url); blobs.delete(url); }); urls = []; previews.replaceChildren();
      Array.from(input.files || []).forEach(file => {
        const pdf = file.type === 'application/pdf';
        if (!pdf && !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) return;
        const url = URL.createObjectURL(file); urls.push(url); blobs.add(url);
        const card = document.createElement('div'); card.className = 'document-card';
        const title = document.createElement('span'); title.className = 'document-card-title'; title.textContent = file.name;
        const button = document.createElement('button'); button.type = 'button'; button.className = 'document-thumbnail'; button.setAttribute('aria-label', `預覽 ${file.name}`);
        const content = document.createElement(pdf ? 'iframe' : 'img'); content.src = url; content.alt = file.name; content.title = file.name; content.tabIndex = -1;
        button.append(content); button.addEventListener('click', () => show(url, file.name, pdf));
        const hint = document.createElement('small'); hint.textContent = '預覽，尚未儲存'; card.append(title, button, hint); previews.append(card);
      });
    });
  });
  window.addEventListener('pagehide', () => blobs.forEach(url => URL.revokeObjectURL(url)));
})();
