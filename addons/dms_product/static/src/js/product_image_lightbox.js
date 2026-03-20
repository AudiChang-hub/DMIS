/** @odoo-module **/

/**
 * DMS 產品圖片手機 Lightbox
 *
 * 在觸控裝置上，點擊表單的 oe_avatar 縮圖時以全螢幕 overlay 顯示大圖。
 * 電腦版保留 Odoo 原生 zoom（hover 效果），不干擾。
 */

document.addEventListener('click', (ev) => {
    // 只處理觸控裝置
    if (!('ontouchstart' in window)) return;

    const img = ev.target.closest('.o_field_image.oe_avatar img, .oe_avatar .o_field_image img');
    if (!img) return;

    ev.preventDefault();
    ev.stopImmediatePropagation();

    // 將 URL 中的縮圖尺寸替換為 image_1920 取得原圖
    const src = img.src.replace(/\/image_\d+(?=\/|$|\?)/, '/image_1920');

    const overlay = document.createElement('div');
    overlay.className = 'dms-img-lightbox';

    const bigImg = document.createElement('img');
    bigImg.src = src;
    bigImg.alt = img.alt || '';
    bigImg.className = 'dms-img-lightbox-img';

    const hint = document.createElement('p');
    hint.className = 'dms-img-lightbox-hint';
    hint.textContent = '點擊任意處關閉';

    overlay.appendChild(bigImg);
    overlay.appendChild(hint);
    overlay.addEventListener('click', () => overlay.remove());
    document.body.appendChild(overlay);
}, { capture: true });
