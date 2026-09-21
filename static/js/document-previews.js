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
    button.addEventListener('click', () => show(url.href, name, pdf)); link.before(button);
  });
  scan(); new MutationObserver(scan).observe(document.body, {childList: true, subtree: true});
  document.querySelectorAll('[data-trade-in-uploads]').forEach(section => {
    const field = section.closest('form').querySelector('[name="trade_in_intent"]');
    const update = () => { section.hidden = field?.value !== 'yes'; };
    field?.addEventListener('change', update); update();
  });
})();
