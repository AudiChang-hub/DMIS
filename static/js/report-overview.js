/* 銷售閱讀版型的圖表工具：只操作已授權的畫面與唯讀查詢。
   T-140（使用者 2026-11-11）：選單分組並加標題；匯出先按再選格式；圖片合併為一項；
   拿掉複製連結、查看資料口徑、報表設計器入口（設計器本身不動）。 */
const REPORT_EXPORT_FORMATS = [['csv', 'CSV', '一般試算表與系統匯入'], ['excel', 'CSV（Excel 相容）', 'Excel 直接開啟中文不亂碼']];
function reportExportUrl(href, format, formatted) {
  const url = new URL(href, typeof location === 'undefined' ? 'http://localhost/' : location.href);
  url.searchParams.set('format', format); url.searchParams.set('formatted', formatted ? '1' : '0');
  return url.href;
}
let reportDialogCount = 0;
function reportDialog(className, title, returnFocus) {
  const dialog = document.createElement('dialog'); dialog.className = `report-image-export ${className}`;
  const heading = document.createElement('h2'); heading.textContent = title; heading.id = `report-dialog-${++reportDialogCount}`;
  dialog.setAttribute('aria-labelledby', heading.id); dialog.append(heading); document.body.append(dialog);
  dialog.addEventListener('close', () => { dialog.remove(); returnFocus?.focus(); }, {once:true});
  return dialog;
}
/* 匯出資料：按下去才問格式（閱讀版選單與一般報表的「匯出 CSV」共用）。 */
function openReportExportDialog(link, returnFocus) {
  const dialog = reportDialog('report-export-dialog', '匯出資料', returnFocus || link);
  // 對話框表單只關閉視窗、觸發下載，不換頁：不顯示全站的處理中提示。
  const form = document.createElement('form'); form.method = 'dialog'; form.noValidate = true; form.dataset.noBusy = '';
  const fieldset = document.createElement('fieldset'); const legend = document.createElement('legend'); legend.textContent = '要匯出哪種格式？';
  fieldset.append(legend);
  for (const [value, label, hint] of REPORT_EXPORT_FORMATS) {
    const option = document.createElement('label'); option.className = 'report-export-choice';
    const radio = document.createElement('input'); radio.type = 'radio'; radio.name = 'format'; radio.value = value;
    const text = document.createElement('span'); const strong = document.createElement('strong'); strong.textContent = label;
    const small = document.createElement('small'); small.textContent = hint; text.append(strong, small);
    option.append(radio, text); fieldset.append(option);
  }
  // 沒選格式時在原地提示，不用瀏覽器必填檢查（避免觸發全站的「目前無法送出」提示）。
  const hint = document.createElement('p'); hint.className = 'report-export-hint'; hint.id = `${dialog.getAttribute('aria-labelledby')}-hint`; hint.hidden = true;
  hint.textContent = '請先選擇匯出格式。'; fieldset.append(hint); fieldset.setAttribute('aria-describedby', hint.id);
  fieldset.addEventListener('change', () => { hint.hidden = true; });
  const keepLabel = document.createElement('label'); keepLabel.className = 'report-export-keep';
  const keep = document.createElement('input'); keep.type = 'checkbox'; keep.name = 'formatted';
  keepLabel.append(keep, '保留畫面上的數值格式（千分位、百分比）');
  const actions = document.createElement('div'); actions.className = 'report-dialog-actions';
  const submit = document.createElement('button'); submit.className = 'button primary'; submit.textContent = '匯出'; submit.value = 'export';
  const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'button ghost'; cancel.textContent = '取消';
  cancel.addEventListener('click', () => dialog.close());
  actions.append(submit, cancel); form.append(fieldset, keepLabel, actions); dialog.append(form);
  form.addEventListener('submit', event => {
    const choice = form.querySelector('input[name="format"]:checked');
    if (!choice) { event.preventDefault(); hint.hidden = false; fieldset.querySelector('input').focus(); return; }
    const anchor = document.createElement('a'); anchor.href = reportExportUrl(link.href, choice.value, keep.checked); anchor.download = '';
    document.body.append(anchor); anchor.click(); anchor.remove();
  });
  dialog.showModal(); fieldset.querySelector('input').focus();
  return dialog;
}
if (typeof document !== 'undefined') document.addEventListener('click', event => {
  const link = event.target.closest?.('a.report-export');
  if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.button) return;
  event.preventDefault(); openReportExportDialog(link);
});
function initReportOverviewTools(chart) {
  if (!chart.closest('.report-sales-overview')) return;
  const toolbar = chart.querySelector('.report-card-toolbar');
  chart.classList.add('report-overview-tools-ready');
  const menu = document.createElement('details'); menu.className = 'report-overview-tools';
  const summary = document.createElement('summary'); summary.textContent = '圖表操作';
  summary.setAttribute('aria-label', `${chart.querySelector('h2').textContent}：圖表操作`);
  const body = document.createElement('div'); body.className = 'report-overview-tool-list';
  menu.append(summary, body); toolbar.append(menu);
  const status = document.createElement('span'); status.className = 'sr-only'; status.setAttribute('role', 'status'); body.append(status);
  let groupCount = 0;
  const group = title => {
    const box = document.createElement('div'); box.className = 'report-tool-group'; box.setAttribute('role', 'group');
    const heading = document.createElement('p'); heading.className = 'report-tool-group__title'; heading.textContent = title;
    heading.id = `${chart.id || 'chart'}-tools-${++groupCount}`; box.setAttribute('aria-labelledby', heading.id);
    box.append(heading); body.append(box); return box;
  };
  const act = (parent, label, run) => {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.addEventListener('click', async () => { button.disabled = true; button.setAttribute('aria-busy','true'); try { await run(); } catch (error) { status.className = 'report-notice'; status.textContent = error.message || '操作未完成，請重試。'; } finally { button.disabled = false; button.removeAttribute('aria-busy'); } });
    parent.append(button); return button;
  };
  const notify = detail => { chart.dispatchEvent(new CustomEvent('report-view-change', {bubbles:true, detail:{card:Number(chart.dataset.chartIndex), ...detail}})); menu.open = false; };
  const form = chart.querySelector('.report-card-filters');
  if (form) {
    const sortGroup = group('排序方式');
    const sort = document.createElement('select'); sort.setAttribute('aria-labelledby', sortGroup.getAttribute('aria-labelledby'));
    for (const [value, label] of [['','依原設計'],['key_desc','分類／日期由後到前'],['key','分類／日期由前到後'],['value','台數由高到低'],['value_asc','台數由低到高']]) {
      const option = document.createElement('option'); option.value = value; option.textContent = label; sort.append(option);
    }
    sort.value = form.querySelector('[name^="sort_"]').value; sortGroup.append(sort);
    sort.addEventListener('change', () => notify({sort:sort.value}));
    const grain = form.querySelector('[name^="grain_"]');
    if (grain) {
      const current = grain.value || chart.dataset.dimension, grainGroup = group('日期層級');
      act(grainGroup, '上探：按年', () => notify({grain:'year'})).disabled = current === 'year';
      act(grainGroup, '下鑽：按月', () => notify({grain:'month'})).disabled = current === 'month';
    }
  }
  if (chart.dataset.chart === 'table') {
    const cells = [...chart.querySelectorAll('.report-summary-table thead th')];
    cells.slice(0,2).forEach((cell,index) => {
      const button=document.createElement('button'); button.type='button'; button.className='report-table-sort';
      button.textContent=cell.textContent+' ↕';
      button.addEventListener('click',()=>{
        const current=form.querySelector('[name^="sort_"]').value;
        notify({sort:index===0 ? (current==='key'?'key_desc':'key') : (current==='value'?'value_asc':'value')});
      }); cell.replaceChildren(button);
    });
  }
  const viewGroup = group('查看');
  act(viewGroup, '重設此圖選取與查看方式', () => notify({reset:true}));
  act(viewGroup, '查看來源訂單', () => { menu.open = false; chart.querySelector('[data-report-open-detail]')?.click(); });
  act(viewGroup, '放大／還原圖表', () => { menu.open = false; chart.querySelector('[data-chart-fullscreen]').click(); });
  const exportGroup = group('匯出');
  const exportLink = chart.querySelector('.report-export');
  if (exportLink) act(exportGroup, '匯出資料…', () => { menu.open = false; openReportExportDialog(exportLink, summary); });
  async function chartImage() {
    const source = chart.querySelector('svg');
    if (!source && chart.dataset.chart === 'table') {
      const table=chart.querySelector('.report-results');
      const rows=[...table.rows].filter(row=>!row.hidden).map(row=>[...row.cells].map(cell=>cell.textContent.trim()));
      const canvas=document.createElement('canvas'), context=canvas.getContext('2d');
      const columns=Math.max(...rows.map(row=>row.length)), cellWidth=250, lineHeight=44;
      canvas.width=columns*cellWidth+40; canvas.height=rows.length*lineHeight+90;
      context.fillStyle='#fff'; context.fillRect(0,0,canvas.width,canvas.height); context.fillStyle='#142e4d'; context.font='22px sans-serif';
      context.fillText(chart.querySelector('h2').textContent+'（目前分頁）',20,35);
      rows.forEach((row,i)=>{ context.fillStyle=i%2?'#fff':'#f2f4fa'; context.fillRect(20,60+i*lineHeight,canvas.width-40,lineHeight); context.fillStyle='#142e4d'; context.font='20px sans-serif'; row.forEach((text,j)=>context.fillText(text,28+j*cellWidth,88+i*lineHeight,cellWidth-16)); });
      return await new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('無法產生表格圖片。')),'image/png'));
    }
    if (!source) throw new Error('目前沒有可匯出的圖形。');
    const clone = source.cloneNode(true);
    const originals = [source, ...source.querySelectorAll('*')], copies = [clone, ...clone.querySelectorAll('*')];
    originals.forEach((node, index) => {
      const style = getComputedStyle(node);
      for (const key of ['fill','stroke','stroke-width','font-family','font-size','font-weight','opacity']) copies[index].style.setProperty(key, style.getPropertyValue(key));
    });
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    const box = source.viewBox.baseVal; const width = Math.max(900, Math.round(source.getBoundingClientRect().width * 2));
    const height = Math.round(width * box.height / box.width);
    clone.setAttribute('width', width); clone.setAttribute('height', height);
    const uri = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], {type:'image/svg+xml'}));
    try {
      const image = new Image(); image.src = uri; await image.decode();
      const canvas = document.createElement('canvas'); canvas.width = width;
      const context = canvas.getContext('2d');
      const entries = [...chart.querySelectorAll('.report-series-legend span,.report-overview-legend a')];
      let x = 24, y = 70; context.font = '20px sans-serif';
      const legend = entries.map(entry => {
        const label = entry.textContent.trim(), needed = context.measureText(label).width + 42;
        if (x + needed > width - 24 && x > 24) { x = 24; y += 30; }
        const item = {label,x,y,color:getComputedStyle(entry.querySelector('i')).backgroundColor}; x += needed; return item;
      });
      const headerHeight = Math.max(110, y + 35);
      canvas.height = height + headerHeight;
      context.fillStyle = getComputedStyle(chart).backgroundColor; context.fillRect(0,0,canvas.width,canvas.height);
      context.fillStyle = getComputedStyle(chart).color; context.font = '24px sans-serif'; context.fillText(chart.querySelector('h2').textContent, 24, 36);
      context.font = '20px sans-serif';
      legend.forEach(item => { context.fillStyle=item.color; context.fillRect(item.x,item.y-15,16,16); context.fillStyle=getComputedStyle(chart).color; context.fillText(item.label,item.x+24,item.y,width-48); });
      context.drawImage(image,0,headerHeight,width,height);
      return await new Promise((resolve,reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('無法產生圖片。')), 'image/png'));
    } finally { URL.revokeObjectURL(uri); }
  }
  /* 「複製圖表圖片」與「另存為 PNG」合併成一項：先產生預覽，再選下載或複製。 */
  act(exportGroup, '圖表圖片（PNG）…', async () => {
    const blob = await chartImage(), uri = URL.createObjectURL(blob);
    const title = chart.querySelector('h2').textContent;
    const dialog = reportDialog('report-image-dialog', '圖表圖片已準備好', summary);
    dialog.addEventListener('close', () => URL.revokeObjectURL(uri), {once:true});
    const preview = document.createElement('img'); preview.src = uri; preview.alt = `${title} PNG 預覽`;
    const actions = document.createElement('div'); actions.className = 'report-dialog-actions';
    const link = document.createElement('a'); link.className = 'button primary'; link.download = `${title}.png`; link.href = uri; link.textContent = '下載 PNG';
    actions.append(link);
    if (navigator.clipboard?.write && typeof ClipboardItem !== 'undefined') {
      const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'button ghost'; copy.textContent = '複製圖片';
      copy.addEventListener('click', async () => {
        try { await navigator.clipboard.write([new ClipboardItem({'image/png':blob})]); copy.textContent = '已複製'; }
        catch { copy.textContent = '瀏覽器不允許複製，請改用下載'; }
      });
      actions.append(copy);
    }
    const close = document.createElement('button'); close.type='button'; close.className='button ghost'; close.textContent='關閉'; close.addEventListener('click',()=>dialog.close());
    actions.append(close); dialog.append(preview, actions);
    menu.open = false; dialog.showModal(); link.focus();
  });
  chart.addEventListener('contextmenu', event => { if (!event.target.closest('svg')) return; event.preventDefault(); menu.open = true; summary.focus(); });
  menu.addEventListener('keydown', event => { if (event.key === 'Escape') { menu.open = false; summary.focus(); } });
  menu.addEventListener('toggle', () => { if (menu.open) document.querySelectorAll('.report-overview-tools').forEach(other => { if (other !== menu) other.open = false; }); });
}
if (typeof module !== 'undefined' && module.exports) module.exports = {reportExportUrl, REPORT_EXPORT_FORMATS};
