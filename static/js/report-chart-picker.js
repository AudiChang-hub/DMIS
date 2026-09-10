/* 圖像選擇器只代理原生 select；資料驗證與儲存仍由既有表單處理。 */
const reportChartExamples = Object.freeze({
  bar: {help: '比較不同分類的數量或金額。', art: '<path d="M18 12v62h104" fill="none" stroke="#9ca8c6"/><path d="M22 20h75v12H22zm0 21h48v12H22zm0 21h91v12H22z" fill="#4658a8"/>'},
  line: {help: '觀察數值隨日期變化的趨勢。', art: '<path d="M18 12v62h104" fill="none" stroke="#9ca8c6"/><path d="m22 61 23-22 24 10 23-29 25 9" fill="none" stroke="#4658a8" stroke-width="4"/><g fill="#25877d"><circle cx="22" cy="61" r="4"/><circle cx="45" cy="39" r="4"/><circle cx="69" cy="49" r="4"/><circle cx="92" cy="20" r="4"/><circle cx="117" cy="29" r="4"/></g>'},
  donut: {help: '查看各分類占整體的比例。', art: '<g fill="none" stroke-width="17" transform="rotate(-90 70 43)"><circle cx="70" cy="43" r="28" stroke="#e2e6f4"/><circle cx="70" cy="43" r="28" stroke="#4658a8" stroke-dasharray="88 176"/><circle cx="70" cy="43" r="28" stroke="#25877d" stroke-dasharray="52 176" stroke-dashoffset="-88"/><circle cx="70" cy="43" r="28" stroke="#de963b" stroke-dasharray="36 176" stroke-dashoffset="-140"/></g>'},
  table: {help: '以列與欄比較分類和詳細數字。', art: '<rect x="16" y="12" width="108" height="62" rx="4" fill="#eef0f9" stroke="#9ca8c6"/><path d="M16 29h108" stroke="#4658a8" stroke-width="17"/><path d="M16 47h108M16 60h108M60 38v36M94 38v36" stroke="#a4afca"/>'},
  score: {help: '醒目呈現單一彙總數字。', art: '<rect x="16" y="12" width="108" height="62" rx="6" fill="#eef0f9"/><path d="M28 25h40" stroke="#9ca8c6" stroke-width="4"/><text x="70" y="58" text-anchor="middle" fill="#4658a8" font-size="27" font-weight="700">1,280</text>'},
  stacked: {help: '比較總量及其中的細分系列。', art: '<path d="M18 12v62h104" fill="none" stroke="#9ca8c6"/><path d="M22 20h40v12H22zm0 21h25v12H22zm0 21h52v12H22z" fill="#4658a8"/><path d="M62 20h25v12H62zm-15 21h30v12H47zm27 21h23v12H74z" fill="#25877d"/><path d="M87 20h22v12H87zM77 41h15v12H77zm20 21h21v12H97z" fill="#de963b"/>'},
});
function reportChartNextIndex(index, key, length) {
  const delta = {ArrowRight: 1, ArrowLeft: -1, ArrowDown: 2, ArrowUp: -2}[key];
  if (key === 'Home') return 0;
  if (key === 'End') return length - 1;
  return delta === undefined ? index : Math.max(0, Math.min(length - 1, index + delta));
}
function reportChartChoose(select, value) {
  if (!Object.hasOwn(reportChartExamples, value) || ![...select.options].some(option => option.value === value && !option.disabled) || select.value === value) return false;
  select.value = value;
  select.dispatchEvent(new Event('change', {bubbles:true}));
  return true;
}
if (typeof module !== 'undefined') module.exports = {reportChartExamples, reportChartNextIndex, reportChartChoose};
if (typeof document !== 'undefined') (() => {
  'use strict';
  const forms = document.querySelector('[data-report-cards]');
  if (!forms || typeof HTMLDialogElement === 'undefined' || !HTMLDialogElement.prototype.showModal) return;
  const dialog = document.createElement('dialog'); dialog.className = 'chart-type-dialog';
  dialog.id = 'chart-type-dialog'; dialog.setAttribute('aria-labelledby', 'chart-type-heading');
  dialog.setAttribute('aria-describedby', 'chart-type-help');
  dialog.innerHTML = '<header><h2 id="chart-type-heading">選擇圖表呈現方式</h2><button type="button" class="chart-type-close" aria-label="關閉圖表選擇器">關閉 ✕</button></header><p id="chart-type-help">示意圖使用範例資料；選取後會更新本次預覽，尚未儲存或發布。</p><div class="chart-type-options" role="group" aria-label="六種圖表呈現方式"></div>';
  document.body.append(dialog);
  const grid = dialog.querySelector('.chart-type-options'), initialized = new WeakSet();
  let activeSelect, trigger;
  const icon = value => `<svg viewBox="0 0 140 86" aria-hidden="true" focusable="false">${reportChartExamples[value].art}</svg>`;
  function open(select, button) {
    activeSelect = select; trigger = button; grid.replaceChildren();
    [...select.options].filter(option => Object.hasOwn(reportChartExamples, option.value)).forEach(option => {
      const tile = document.createElement('button'); tile.type = 'button'; tile.className = 'chart-type-option';
      tile.dataset.chartChoice = option.value; tile.disabled = option.disabled;
      tile.setAttribute('aria-pressed', String(option.value === select.value));
      tile.setAttribute('aria-label', option.text);
      tile.innerHTML = `${icon(option.value)}<strong></strong><span class="chart-type-description"></span><span class="chart-type-check" aria-hidden="true">✓</span>`;
      tile.querySelector('strong').textContent = option.text;
      const description = tile.querySelector('.chart-type-description');
      description.id = `chart-type-${option.value}-help`;
      description.textContent = reportChartExamples[option.value].help;
      tile.setAttribute('aria-describedby', description.id);
      tile.addEventListener('click', () => { reportChartChoose(select, option.value); dialog.close(); });
      grid.append(tile);
    });
    button.setAttribute('aria-expanded', 'true'); dialog.showModal();
    (grid.querySelector('[aria-pressed="true"]') || grid.querySelector('button'))?.focus();
  }
  function enhance() {
    forms.querySelectorAll('select[name$="-chart"]').forEach(select => {
      if (initialized.has(select) || !Object.hasOwn(reportChartExamples, select.value)) return;
      initialized.add(select);
      const button = document.createElement('button'); button.type = 'button'; button.className = 'chart-type-trigger';
      button.id = `${select.id}-visual`; button.setAttribute('aria-haspopup', 'dialog');
      button.setAttribute('aria-expanded', 'false'); button.setAttribute('aria-controls', dialog.id);
      const update = () => {
        if (!Object.hasOwn(reportChartExamples, select.value)) return;
        button.innerHTML = `${icon(select.value)}<span></span><span aria-hidden="true">⌄</span>`;
        const name = select.selectedOptions[0].text;
        button.querySelector('span').textContent = name;
        button.setAttribute('aria-label', `呈現方式：${name}，開啟圖像選擇器`);
      };
      select.after(button); update(); select.hidden = true; select.dataset.visualChartSelect = '';
      const label = select.closest('.report-field').querySelector('label'); if (label) label.htmlFor = button.id;
      select.addEventListener('change', update);
      select.addEventListener('invalid', event => { event.preventDefault(); button.focus(); });
      button.addEventListener('click', () => open(select, button));
    });
  }
  dialog.querySelector('.chart-type-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { trigger?.setAttribute('aria-expanded', 'false'); if (trigger?.isConnected) trigger.focus(); activeSelect = null; });
  dialog.addEventListener('click', event => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } });
  grid.addEventListener('keydown', event => {
    if (!['ArrowRight','ArrowLeft','ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
    const tiles = [...grid.querySelectorAll('button:not(:disabled)')];
    const index = tiles.indexOf(event.target); if (index < 0) return;
    event.preventDefault(); tiles[reportChartNextIndex(index, event.key, tiles.length)]?.focus();
  });
  new MutationObserver(() => { if (activeSelect && (!activeSelect.isConnected || activeSelect.closest('[data-report-card]').hidden)) dialog.close(); enhance(); }).observe(forms, {childList:true, subtree:true});
  enhance();
})();
