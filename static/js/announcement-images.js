document.querySelectorAll('[data-announcement-upload]').forEach(input => {
  const form = input.closest('form');
  const container = form.querySelector('[data-announcement-previews]');
  const status = form.querySelector('[data-announcement-upload-status]');
  let urls = [], generation = 0;
  const clear = () => { urls.forEach(url => URL.revokeObjectURL(url)); urls = []; container.replaceChildren(); };
  input.addEventListener('change', () => {
    const current = ++generation;
    clear(); input.setCustomValidity('');
    const files = [...input.files];
    if (files.length > 8 || files.reduce((n, file) => n + file.size, 0) > 24 * 1024 * 1024 ||
        files.some(file => !file.size || file.size > 8 * 1024 * 1024 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type))) {
      status.textContent = '請選 JPEG／PNG／WebP，每張最多 8 MB；最多 8 張、合計 24 MB。';
      input.setCustomValidity(status.textContent); return;
    }
    status.textContent = files.length ? `已選 ${files.length} 張，預覽中（尚未儲存）。` : '';
    files.forEach(file => {
      const figure = document.createElement('figure'), image = document.createElement('img'), caption = document.createElement('figcaption');
      const url = URL.createObjectURL(file); urls.push(url);
      image.alt = file.name; image.src = url; caption.textContent = file.name;
      image.onerror = () => { if (generation === current) { status.textContent = '有圖片無法讀取，請重新選擇。'; input.setCustomValidity(status.textContent); } };
      figure.append(image, caption); container.append(figure);
    });
  });
  window.addEventListener('pagehide', () => { ++generation; clear(); });
});
