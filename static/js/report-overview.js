/* 總車輛銷售的圖表工具：只操作已授權的畫面與唯讀查詢。 */
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
  const act = (label, run) => {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.addEventListener('click', async () => { button.disabled = true; button.setAttribute('aria-busy','true'); try { await run(); } catch (error) { status.className = 'report-notice'; status.textContent = error.message || '操作未完成，請重試。'; } finally { button.disabled = false; button.removeAttribute('aria-busy'); } });
    body.append(button); return button;
  };
  const notify = detail => { chart.dispatchEvent(new CustomEvent('report-view-change', {bubbles:true, detail:{card:Number(chart.dataset.chartIndex), ...detail}})); menu.open = false; };
  const form = chart.querySelector('.report-card-filters');
  if (form) {
    const sort = document.createElement('select'); sort.setAttribute('aria-label', '圖表排序');
    for (const [value, label] of [['','依原設計'],['key_desc','分類／日期由後到前'],['key','分類／日期由前到後'],['value','台數由高到低'],['value_asc','台數由低到高']]) {
      const option = document.createElement('option'); option.value = value; option.textContent = label; sort.append(option);
    }
    sort.value = form.querySelector('[name^="sort_"]').value; body.append(sort);
    sort.addEventListener('change', () => notify({sort:sort.value}));
    const grain = form.querySelector('[name^="grain_"]');
    if (grain) {
      const current = grain.value || chart.dataset.dimension;
      act('上探：按年', () => notify({grain:'year'})).disabled = current === 'year';
      act('下鑽：按月', () => notify({grain:'month'})).disabled = current === 'month';
    }
  }
  act('重設此圖選取與查看方式', () => notify({reset:true}));
  act('查看來源訂單', () => { menu.open = false; chart.querySelector('[data-report-open-detail]')?.click(); });
  act('放大／還原圖表', () => { menu.open = false; chart.querySelector('[data-chart-fullscreen]').click(); });
  const exportLink = chart.querySelector('.report-export');
  if (exportLink) {
    const formatLabel = document.createElement('label'); formatLabel.textContent = '匯出格式';
    const format = document.createElement('select'); format.setAttribute('aria-label','匯出格式');
    for (const [value, text] of [['csv','CSV'],['excel','CSV（Excel 相容）']]) { const option = document.createElement('option'); option.value = value; option.textContent = text; format.append(option); }
    formatLabel.append(format); body.append(formatLabel);
    const keepLabel = document.createElement('label'), keep = document.createElement('input'); keep.type = 'checkbox'; keepLabel.append(keep, ' 保留值格式'); body.append(keepLabel);
    act('匯出資料', () => { const url = new URL(exportLink.href); url.searchParams.set('format',format.value); url.searchParams.set('formatted',keep.checked ? '1' : '0'); const link = document.createElement('a'); link.href = url.href; link.download = ''; document.body.append(link); link.click(); link.remove(); menu.open = false; });
  }
  async function chartImage() {
    const source = chart.querySelector('svg'); if (!source) throw new Error('目前沒有可匯出的圖形。');
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
      const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height + 150;
      const context = canvas.getContext('2d'); context.fillStyle = getComputedStyle(chart).backgroundColor; context.fillRect(0,0,canvas.width,canvas.height);
      context.fillStyle = getComputedStyle(chart).color; context.font = '24px sans-serif'; context.fillText(chart.querySelector('h2').textContent, 24, 36);
      const entries = [...chart.querySelectorAll('.report-series-legend span,.report-overview-legend a')];
      let x = 24, y = 70; context.font = '20px sans-serif';
      entries.forEach(entry => { const label = entry.textContent.trim(), needed = context.measureText(label).width + 42; if (x + needed > width - 24) { x = 24; y += 30; } context.fillStyle = getComputedStyle(entry.querySelector('i')).backgroundColor; context.fillRect(x,y-15,16,16); context.fillStyle = getComputedStyle(chart).color; context.fillText(label,x+24,y); x += needed; });
      context.drawImage(image,0,150,width,height);
      return await new Promise((resolve,reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('無法產生圖片。')), 'image/png'));
    } finally { URL.revokeObjectURL(uri); }
  }
  act('另存為 PNG', async () => {
    const blob = await chartImage(), uri = URL.createObjectURL(blob);
    const dialog = document.createElement('dialog'); dialog.className = 'report-image-export'; dialog.setAttribute('aria-label','匯出圖表圖片');
    const heading = document.createElement('h2'); heading.textContent = '圖表圖片已準備好';
    const preview = document.createElement('img'); preview.src = uri; preview.alt = chart.querySelector('h2').textContent + ' PNG 預覽';
    const link = document.createElement('a'); link.className = 'button'; link.download = `${chart.querySelector('h2').textContent}.png`; link.href = uri; link.textContent = '下載 PNG';
    const close = document.createElement('button'); close.type='button'; close.className='button secondary'; close.textContent='關閉預覽'; close.addEventListener('click',()=>dialog.close());
    dialog.append(heading,preview,link,close); document.body.append(dialog);
    dialog.addEventListener('close',()=>{ URL.revokeObjectURL(uri); dialog.remove(); summary.focus(); },{once:true});
    menu.open = false; dialog.showModal();
  });
  if (navigator.clipboard?.write && typeof ClipboardItem !== 'undefined') act('複製圖表圖片', async () => { await navigator.clipboard.write([new ClipboardItem({'image/png':chartImage()})]); status.textContent = '已複製圖表圖片'; });
  act('複製此圖連結（含篩選）', async () => { const url = new URL(location.href); url.hash = chart.id; if (!navigator.clipboard?.writeText) throw new Error('瀏覽器不允許複製，請從網址列複製目前網址。'); await navigator.clipboard.writeText(url.href); status.textContent = '已複製連結；接收者仍須有報表權限。'; });
  act('查看資料口徑', () => { menu.open = false; const explanation = chart.closest('.report-sales-overview').querySelector('.report-reader-description'); explanation.open = true; explanation.scrollIntoView({block:'start',behavior:'smooth'}); });
  const editorUrl = chart.closest('.report-reader-main').dataset.reportEditorUrl;
  if (editorUrl) { const link = document.createElement('a'); link.href = editorUrl; link.textContent = '在報表設計器探索（admin）'; body.append(link); }
  chart.addEventListener('contextmenu', event => { if (!event.target.closest('svg')) return; event.preventDefault(); menu.open = true; summary.focus(); });
  menu.addEventListener('keydown', event => { if (event.key === 'Escape') { menu.open = false; summary.focus(); } });
  menu.addEventListener('toggle', () => { if (menu.open) document.querySelectorAll('.report-overview-tools').forEach(other => { if (other !== menu) other.open = false; }); });
}
