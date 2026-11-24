/* T-311 台數統計（#13 #14，count_overview）：點車行名稱就在表格裡展開該車行的訂單，不用捲到下面的全部明細再找。
   展開內容由原本的 report_detail（同一個網址、同一個 group，加 view=count）提供，欄位沿用明細的口徑；
   金額欄的 0 顯示成淡灰「—」。Ctrl／⌘／中鍵點名稱仍照原連結開新頁。 */
function initReportCountExpand(root) {
  root.querySelectorAll('.report-reader-main[data-reader-layout="count_overview"] .report-summary-table').forEach(table => {
    if (table.dataset.countExpandReady) return;
    table.dataset.countExpandReady = 'true';
    const doc = table.ownerDocument;
    const columns = table.tHead ? table.tHead.rows[0].cells.length : 1;
    [...table.tBodies[0].rows, ...(table.tFoot ? table.tFoot.rows : [])].forEach(row => {
      row.querySelectorAll('td.is-zero').forEach(cell => {
        if (cell.querySelector('.report-count-cell')) return; // 台數欄有長條，保留數字
        cell.setAttribute('aria-label', '0'); cell.textContent = '—';
      });
    });
    [...table.tBodies[0].rows].forEach((row, position) => {
      const link = row.querySelector('th [data-report-drill]');
      if (!link) return;
      const name = link.textContent.trim();
      const panelId = `report-count-orders-${position}`;
      link.removeAttribute('data-report-drill');
      link.classList.add('report-count-toggle');
      link.setAttribute('role', 'button');
      link.setAttribute('aria-expanded', 'false');
      link.setAttribute('aria-controls', panelId);
      link.setAttribute('aria-label', `展開 ${name} 的訂單`);
      let detail = null;
      link.addEventListener('click', event => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.button === 1) return;
        event.preventDefault();
        const open = link.getAttribute('aria-expanded') !== 'true';
        link.setAttribute('aria-expanded', String(open));
        row.classList.toggle('is-expanded', open);
        if (detail) { detail.hidden = !open; return; }
        detail = doc.createElement('tr'); detail.className = 'report-count-detail'; detail.id = panelId;
        const cell = doc.createElement('td'); cell.colSpan = columns;
        const status = doc.createElement('p'); status.className = 'report-count-detail__status'; status.setAttribute('role', 'status'); status.textContent = '正在載入訂單…';
        cell.append(status); detail.append(cell); row.after(detail);
        const url = new URL(link.href, location.href);
        url.searchParams.set('inline', '1'); url.searchParams.set('view', 'count'); url.searchParams.set('label', name);
        fetch(url, {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}})
          .then(response => { if (!response.ok) throw new Error(String(response.status)); return response.text(); })
          .then(html => {
            const content = new DOMParser().parseFromString(html, 'text/html').querySelector('[data-count-orders]');
            if (!content) throw new Error('empty');
            cell.replaceChildren(doc.importNode(content, true));
          })
          .catch(() => {
            status.textContent = '訂單載入失敗。';
            const retry = doc.createElement('a'); retry.href = link.href; retry.textContent = '改看完整明細 →'; status.append(' ', retry);
          });
      });
    });
  });
}

/* T-311 共用基礎：閱讀版型的明細預設只顯示常用欄，「顯示其他 N 欄」切換其餘欄位。
   狀態記在 .report-reader-main（明細原地換新後仍維持），按鈕文字由 CSS 依狀態切換。 */
if (typeof document !== 'undefined') document.addEventListener('click', event => {
  const button = event.target.closest('[data-record-extra-toggle]');
  if (!button) return;
  const reader = button.closest('.report-reader-main');
  if (!reader) return;
  const show = !reader.hasAttribute('data-show-record-extra');
  reader.toggleAttribute('data-show-record-extra', show);
  reader.querySelectorAll('[data-record-extra-toggle]').forEach(item => item.setAttribute('aria-pressed', String(show)));
});
