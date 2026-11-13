/* T-164 車種類別設定：發布前檢查以對話框呈現；未歸類型號可整列點選、全選本頁並顯示已選數量。 */
function classificationBatchText(count) {
  return count ? `已選 ${count} 個型號` : '勾選型號後選類別';
}
if (typeof module !== 'undefined') module.exports = {classificationBatchText};
if (typeof document !== 'undefined') (() => {
  'use strict';
  const dialog = document.querySelector('[data-publish-dialog]');
  if (dialog?.open && typeof dialog.showModal === 'function') {
    // 沒有 JavaScript 時以一般區塊顯示；有的話改為置中的對話框。
    dialog.close(); dialog.showModal();
    dialog.querySelector('input[name="confirm"]')?.focus();
  }
  const form = document.querySelector('[data-batch-form]');
  if (!form) return;
  const boxes = [...form.querySelectorAll('input[name="models"]')];
  const all = form.querySelector('[data-select-all]');
  const count = form.querySelector('[data-batch-count]');
  const refresh = () => {
    const selected = boxes.filter(box => box.checked).length;
    count.textContent = classificationBatchText(selected);
    form.querySelector('[data-batch-bar]').dataset.active = String(selected > 0);
    all.checked = selected > 0 && selected === boxes.length;
    all.indeterminate = selected > 0 && selected < boxes.length;
    boxes.forEach(box => box.closest('tr').classList.toggle('is-selected', box.checked));
  };
  all?.addEventListener('change', () => { boxes.forEach(box => { box.checked = all.checked; }); refresh(); });
  form.addEventListener('change', event => { if (event.target.name === 'models') refresh(); });
  form.addEventListener('click', event => {
    const row = event.target.closest('[data-select-row]');
    if (!row || event.target.closest('input,label,a,button,select')) return;
    const box = row.querySelector('input[name="models"]');
    if (box) { box.checked = !box.checked; refresh(); }
  });
  refresh();
})();
