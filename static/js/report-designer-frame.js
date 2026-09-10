/* Sandboxed preview communicates only with its authenticated parent. */
(() => {
  'use strict';
  const boot = JSON.parse(document.getElementById('preview-boot').textContent);
  window.reportPreviewLocation = boot.url;
  const pending = new Map(); let id = 0, mode = 'edit', selected = 0, lastHeight = 0;
  const send = (type, extra = {}) => parent.postMessage({channel:boot.channel, type, ...extra}, '*');
  window.reportPreviewFetch = (url, options = {}) => new Promise((resolve, reject) => {
    const key = String(++id);
    const finish = (error, response) => { clearTimeout(timeout); pending.delete(key); options.signal?.removeEventListener('abort', abort); error ? reject(error) : resolve(response); };
    const abort = () => { send('cancel', {id:key}); finish(new DOMException('已取消預覽', 'AbortError')); };
    const timeout = setTimeout(() => { send('cancel', {id:key}); finish(new Error('預覽查詢逾時，請重試。')); }, 35000);
    pending.set(key, finish);
    if (options.signal?.aborted) { abort(); return; }
    options.signal?.addEventListener('abort', abort, {once:true});
    send('request', {id:key, url:String(url)});
  });
  const charts = () => [...document.querySelectorAll('.report-grid>.report-chart')];
  function measure() {
    const main = document.querySelector('main'); if (!main) return;
    const height = Math.ceil(main.getBoundingClientRect().bottom + window.scrollY + 20);
    if (Math.abs(height - lastHeight) > 2) { lastHeight = height; send('height', {height}); }
  }
  function overlays() {
    document.body.dataset.designerMode = mode;
    charts().forEach((chart, index) => {
      let overlay = chart.querySelector(':scope>.designer-chart-overlay');
      if (!overlay) {
        overlay = document.createElement('div'); overlay.className = 'designer-chart-overlay'; overlay.tabIndex = 0;
        overlay.setAttribute('role', 'button'); overlay.setAttribute('aria-label', `選取圖表 ${index + 1}；Enter 選取，右側設定可排序及調整大小`);
        const choose = () => { selected = index; send('select', {index}); overlays(); };
        overlay.addEventListener('click', choose);
        overlay.addEventListener('keydown', event => { if (event.target === overlay && ['Enter',' '].includes(event.key)) { event.preventDefault(); choose(); } });
        const drag = document.createElement('button'); drag.type = 'button'; drag.textContent = `⠿ 圖表 ${index + 1}`; drag.title = '拖曳排序；亦可在設定區使用上移／下移';
        const resize = document.createElement('button'); resize.type = 'button'; resize.dataset.resize = ''; resize.textContent = '↘'; resize.setAttribute('aria-label', '調整尺寸；方向鍵改變寬高');
        resize.addEventListener('keydown', event => {
          if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
          event.preventDefault(); send('resize', {index, width:event.key === 'ArrowLeft' ? 6 : event.key === 'ArrowRight' ? 12 : chart.classList.contains('report-chart--wide') ? 12 : 6, height:(parseInt(chart.style.minHeight) || 520) + (event.key === 'ArrowDown' ? 40 : event.key === 'ArrowUp' ? -40 : 0)});
        });
        function start(event, sizing) {
          if (event.button !== 0) return;
          event.preventDefault(); choose(); const x = event.clientX, y = event.clientY;
          const initial = parseInt(chart.style.minHeight) || 520; const rect = chart.getBoundingClientRect();
          const handle = event.currentTarget; handle.setPointerCapture(event.pointerId);
          const move = point => {
            if (sizing) { overlay.style.width = `${Math.max(100, rect.width + point.clientX-x)}px`; overlay.style.height = `${Math.max(100, rect.height + point.clientY-y)}px`; }
            else { overlay.style.transform = `translate(${point.clientX-x}px,${point.clientY-y}px)`; overlay.style.opacity = '.7'; }
          };
          const stop = end => {
            handle.removeEventListener('pointerup', stop); handle.removeEventListener('pointercancel', stop);
            handle.removeEventListener('pointermove', move); overlay.style.width = ''; overlay.style.height = ''; overlay.style.transform = ''; overlay.style.opacity = '';
            if (end.type === 'pointercancel' || Math.abs(end.clientX-x) + Math.abs(end.clientY-y) < 5) return;
            if (sizing) send('resize', {index, height:initial+end.clientY-y, width:end.clientX-rect.left > chart.parentElement.clientWidth * .7 ? 12 : 6});
            else {
              const target = charts().findIndex(item => { const r = item.getBoundingClientRect(); return end.clientX >= r.left && end.clientX <= r.right && end.clientY >= r.top && end.clientY <= r.bottom; });
              if (target >= 0) send('move', {index, target});
            }
          };
          handle.addEventListener('pointermove', move); handle.addEventListener('pointerup', stop); handle.addEventListener('pointercancel', stop);
        }
        drag.addEventListener('pointerdown', event => start(event, false)); resize.addEventListener('pointerdown', event => start(event, true));
        overlay.append(drag, resize); chart.append(overlay);
      }
      overlay.classList.toggle('is-selected', index === selected);
      overlay.setAttribute('aria-pressed', String(index === selected));
    });
  }
  window.addEventListener('message', event => {
    const msg = event.data; if (event.source !== parent || !msg || msg.channel !== boot.channel) return;
    if (msg.type === 'response') {
      const finish = pending.get(msg.id); if (!finish) return;
      if (msg.error) finish(new Error(msg.error));
      else finish(null, new Response(msg.document, {status:msg.status || 200, headers:{'Content-Type':msg.content_type || 'text/html'}}));
    }
    if (msg.type === 'state') { mode = msg.mode === 'preview' ? 'preview' : 'edit'; selected = msg.selected; overlays(); }
    if (msg.type === 'reveal') charts()[msg.index]?.scrollIntoView({block:'nearest'});
  });
  document.addEventListener('click', async event => {
    const link = event.target.closest('a'); if (!link) return;
    const url = new URL(link.href, window.reportPreviewLocation);
    if (url.pathname.endsWith('/export/')) {
      event.preventDefault(); event.stopImmediatePropagation();
      try {
        const response = await window.reportPreviewFetch(url);
        if (!response.ok) throw new Error('匯出失敗，請檢查篩選或權限。');
        const blob = await response.blob(), download = document.createElement('a'); download.href = URL.createObjectURL(blob); download.download = '報表預覽.csv';
        document.body.append(download); download.click(); download.remove(); setTimeout(() => URL.revokeObjectURL(download.href), 1000);
        send('notice', {message:'CSV 已產生，請至瀏覽器下載清單查看。'});
      } catch (error) { send('notice', {message:error.message}); }
    } else if (!['blob:', 'data:'].includes(url.protocol) && !url.pathname.startsWith('/reports/')) {
      event.preventDefault(); event.stopImmediatePropagation(); send('notice', {message:'設計預覽不會開啟或修改原訂單；請從已發布報表查看原訂單。'});
    }
  }, true);
  window.addEventListener('DOMContentLoaded', () => {
    overlays(); measure(); new ResizeObserver(measure).observe(document.querySelector('main'));
    let queued = false;
    new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; if (charts().some(chart => !chart.querySelector(':scope>.designer-chart-overlay'))) overlays(); measure(); }); } }).observe(document.querySelector('main'), {childList:true, subtree:true});
    send('ready');
  });
})();
