/* 圖表互動只讀取伺服器已授權資料；不修改報表或訂單。 */
function reportPointText(data, metric) {
  if (data.pointSummary) return data.pointSummary;
  let text = `${data.pointLabel}\n${metric}：${data.pointDisplay}`;
  if (metric !== "訂單台數") text += `\n訂單台數：${data.pointCount}`;
  if (data.pointPercentage !== "" && Number.isFinite(Number(data.pointPercentage))) text += `\n占${data.pointScope || '完整篩選範圍'}：${Number(data.pointPercentage).toFixed(1)}%`;
  return text;
}
function reportOverviewColor(label, fallback) {
  return {'馭盛':'#737373','車行':'#7ac36a','網路平台':'#f15a60','店內員工':'#faa75a','展場':'#5a9bd4',
    '白牌電車':'#737373','速克達':'#f15a60','綠牌電車':'#7ac36a','擋車':'#5a9bd4','微型電車':'#faa75a'}[label] || fallback;
}
function reportElectricColor(label, fallback) {
  const colors = ['#737373','#f15a60','#7ac36a','#5a9bd4','#faa75a','#9e67ab','#ce7058','#d17fb1','#7dd3ef','#ee8ab5'];
  const models = ['EV060L','EV062','EV076S','EV076','EV076SZV','EV070V','EV062FL','EZ1','EZZY','SHINE','TSV57','JEGO','GogoroVIVAMIX','Gogoro2D','VIVABASIC','Ur2','BOBE','S2ABS','M02','M01'];
  const index = models.indexOf(label);
  return {'馭盛':colors[0],'車行':colors[1],'網路平台':colors[2],'店內員工':colors[3],'展場':colors[4]}[label] || (index >= 0 ? colors[index % colors.length] : fallback);
}
function reportReaderColor(layout, label, fallback, energy) {
  if (layout === 'analysis_overview') return reportAnalysisColor(label, fallback);
  const palette = ['#737373','#f15a60','#7ac36a','#5a9bd4','#faa75a','#9e67ab','#ce7058','#d17fb1','#7dd3ef','#ee8ab5'];
  if (layout === 'gasoline_overview') {
    const models = ['UQ125DA','UQ125','UC125DA','UC125','UT125XDA','UT125XZ','UG125','GSX-R150','GSX250F','GSX250'];
    const i=models.indexOf(label);
    return i<0 ? reportElectricColor(label,fallback) : palette[i];
  }
  if (layout === 'platform_overview') {
    const platforms = energy === '油車' ? ['YAHOO','FRIDAY','百利市','PC','小樹購','燦坤','YAHOO+假展場'] : ['MOMO','小樹購員購','PC','YAHOO','蝦皮','MOMO員購','燦坤'];
    const i=platforms.indexOf(label); return i<0 ? fallback : palette[i];
  }
  return layout === 'electric_overview' ? reportElectricColor(label,fallback) : reportOverviewColor(label,fallback);
}
function reportMonthSummary(label, segments, total) {
  return [label, ...segments.filter(item => Number(item.value)).map(item => `${item.label}：${item.display}`), `總計：${total}`].join('\n');
}
function resizeReportDonutLabels(root = document) {
  root.querySelectorAll('.report-sales-overview .report-donut').forEach(svg => {
    const width = svg.getBoundingClientRect().width;
    if (width) svg.querySelectorAll('text').forEach(text => { text.style.fontSize = `${16 * 300 / width}px`; });
  });
}
if (typeof window !== 'undefined') window.addEventListener('resize', () => resizeReportDonutLabels());
function reportFraction(value, total) {
  if (!Number.isFinite(Number(value)) || !Number.isFinite(Number(total)) || Number(total) <= 0) return 0;
  return Math.max(0, Math.min(100, Number(value) / Number(total) * 100));
}
function reportScopeCount(selected, texts) {
  return selected + texts.reduce((sum, text) => sum + new Set(text.split(/\r?\n/).map(line => line.trim()).filter(Boolean)).size, 0);
}
function reportPageRange(total, size, requested) {
  size = [10, 25, 50, 100].includes(size) ? size : 25;
  const pages = Math.max(1, Math.ceil(total / size));
  const page = Math.max(1, Math.min(pages, Number.isInteger(requested) ? requested : 1));
  return {page, pages, start: (page - 1) * size, end: Math.min(total, page * size)};
}
function initReportTablePagination(table) {
  const rows = [...table.tBodies[0].rows];
  if (rows.length <= 10) return;
  const doc = table.ownerDocument;
  let page = 1;
  const nav = doc.createElement('nav'); nav.className = 'site-pagination report-pagination';
  nav.setAttribute('aria-label', '彙總表分頁');
  const sizeLabel = doc.createElement('label'); sizeLabel.textContent = '每頁群組 ';
  const size = doc.createElement('select'); size.setAttribute('aria-label', '彙總表每頁群組');
  [10,25,50,100].forEach(value => { const option = doc.createElement('option'); option.value = value; option.textContent = value; size.append(option); });
  size.value = '25'; sizeLabel.append(size);
  const button = text => { const b = doc.createElement('button'); b.type = 'button'; b.className = 'button ghost small secondary site-pagination__link'; b.textContent = text; return b; };
  const first = button('第一頁'), previous = button('上一頁'), next = button('下一頁'), last = button('最後一頁');
  const status = doc.createElement('strong'); status.className = 'site-pagination__status'; status.setAttribute('aria-live', 'polite');
  const jump = doc.createElement('form'); jump.className = 'site-pagination__jump';
  const label = doc.createElement('label'); label.append('前往第 ');
  const input = doc.createElement('input'); input.type = 'number'; input.min = '1'; input.step = '1'; input.required = true; input.inputMode = 'numeric'; input.setAttribute('aria-label', '輸入要前往的頁碼');
  label.append(input, ' 頁'); const go = button('前往'); go.type = 'submit'; jump.append(label, go);
  const render = () => {
    const range = reportPageRange(rows.length, Number(size.value), page); page = range.page;
    rows.forEach((row, index) => { row.hidden = index < range.start || index >= range.end; });
    status.textContent = `第 ${page}／${range.pages} 頁 · 顯示第 ${range.start + 1}–${range.end} 群，共 ${rows.length} 群`;
    input.value = String(page); input.max = String(range.pages);
    first.disabled = previous.disabled = page === 1; last.disabled = next.disabled = page === range.pages;
  };
  first.addEventListener('click', () => { page = 1; render(); });
  previous.addEventListener('click', () => { page--; render(); });
  next.addEventListener('click', () => { page++; render(); });
  last.addEventListener('click', () => { page = reportPageRange(rows.length, Number(size.value), 1).pages; render(); });
  jump.addEventListener('submit', event => {
    event.preventDefault();
    if (!jump.reportValidity()) return;
    page = Number(input.value); render();
  });
  size.addEventListener('change', () => { page = 1; render(); });
  nav.append(sizeLabel, first, previous, status, jump, next, last);
  table.closest('.report-table-wrap').after(nav); render();
}
function reportToggleSelection(selected, card, group, grain, multiple) {
  const previous = selected.find(item => item.card === card);
  const groups = previous && previous.grain === grain ? [].concat(previous.group) : [];
  const next = multiple ? (groups.includes(group) ? groups.filter(value => value !== group) : [...groups, group]) : (groups.length === 1 && groups[0] === group ? [] : [group]);
  if (next.length > 200) throw new Error("同一張圖最多選取 200 個分類。");
  return [...selected.filter(item => item.card !== card), ...(next.length ? [{card, group:next.length === 1 ? next[0] : next, grain}] : [])];
}
function reportAxisMaximum(values) {
  const maximum = Math.max(0, ...values.filter(Number.isFinite));
  if (!maximum) return 4;
  const rough = maximum / 4, power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].find(value => value * power >= rough) * power;
  return Math.max(4, Math.ceil(step) * 4);
}
function reportDebounce(run, delay = 300, timers = globalThis) {
  let timer;
  return {
    cancel() { timers.clearTimeout(timer); },
    schedule(value) { timers.clearTimeout(timer); timer = timers.setTimeout(() => run(value), delay); }
  };
}
function reportUpdateError(error) {
  if (error.name === 'AbortError') return '更新逾時，保留上次成功畫面；請重試。';
  if (error.name === 'TypeError') return '暫時無法連線，保留上次成功畫面；請確認網路後重試。';
  return error.message || '無法完成更新，請稍後重試。';
}
if (typeof module !== "undefined" && module.exports) module.exports = {reportPointText, reportFraction, reportScopeCount, reportPageRange, reportToggleSelection, reportAxisMaximum, reportDebounce, reportUpdateError, reportOverviewColor, reportElectricColor, reportMonthSummary, initReportTablePagination};
function initReportVisuals(root) {
  "use strict";
  if (typeof document === "undefined") return;
  const updateScope = scope => {
    const count = reportScopeCount(scope.querySelectorAll('input[type="checkbox"]:checked').length,
      [...scope.querySelectorAll('textarea')].map(field => field.value));
    scope.querySelector("[data-scope-count]").textContent = count ? `已選 ${count} 項` : "沿用報表範圍";
  };
  const initMulti = root => root.querySelectorAll("[data-report-multi]").forEach(control => {
    if (control.dataset.multiReady) return;
    control.dataset.multiReady = "true";
    const inputs = [...control.querySelectorAll('input[type="checkbox"]')];
    const fieldName = inputs[0]?.name;
    const sourceStyle = control.closest('.report-sales-overview .report-filter-grid') && ['months','legacy_source','legacy_dealer'].includes(fieldName);
    const form = control.closest('form');
    const emptyField = sourceStyle && form.elements.namedItem(`empty_${fieldName}`);
    if (sourceStyle) {
      control.syncFromServer = () => {
        if (!inputs.some(input => input.checked) && !['True','true','1'].includes(emptyField.value)) inputs.forEach(input => { input.checked = true; });
      };
      control.syncFromServer();
      control.querySelector('[data-multi-clear]').textContent = '全部取消';
      control.querySelector('.report-multi-options > small').textContent = '全部勾選表示不限；全部取消則不顯示資料。可點「只選此項」。';
      form.addEventListener('formdata', event => {
        const selected = inputs.filter(input => input.checked);
        if (selected.length === inputs.length) event.formData.delete(fieldName);
        event.formData.set(`empty_${fieldName}`, selected.length ? '' : '1');
      });
      inputs.forEach(input => {
        const only = document.createElement('button'); only.type = 'button'; only.textContent = '只選此項';
        only.addEventListener('click', event => { event.preventDefault(); inputs.forEach(other => { other.checked = other === input; }); control.dispatchEvent(new Event('change', {bubbles:true})); });
        input.closest('label').append(only);
      });
    }
    const update = () => {
      const selected = inputs.filter(input => input.checked);
      control.querySelector("[data-multi-summary]").textContent = sourceStyle ? (selected.length === inputs.length ? '全部' : selected.length ? `已選 ${selected.length} 項` : '未選取（無資料）') : selected.length ? `已選 ${selected.length} 項` : "不限（可複選）";
      const scope = control.closest(".report-card-scope");
      if (scope) updateScope(scope);
    };
    control.addEventListener("change", update);
    control.querySelector("[data-multi-search]").addEventListener("input", event => {
      const query = event.target.value.trim().toLocaleLowerCase();
      control.querySelectorAll("[data-multi-option]").forEach(option => { option.hidden = !option.textContent.toLocaleLowerCase().includes(query); });
    });
    control.querySelector("[data-multi-all]").addEventListener("click", () => {
      inputs.filter(input => !input.closest("label").hidden).forEach(input => { input.checked = true; });
      control.dispatchEvent(new Event("change", {bubbles:true}));
    });
    control.querySelector("[data-multi-clear]").addEventListener("click", () => { inputs.forEach(input => { input.checked = false; }); control.dispatchEvent(new Event("change", {bubbles:true})); });
    control.addEventListener("toggle", () => {
      if (control.open) document.querySelectorAll("[data-report-multi]").forEach(other => { if (other !== control) other.open = false; });
    });
    control.addEventListener("keydown", event => { if (event.key === "Escape") { control.open = false; control.querySelector("summary").focus(); } });
    update();
  });
  initMulti(root);
  root.addEventListener("input", event => {
    const scope = event.target.closest(".report-card-scope");
    if (!scope || event.target.tagName !== "TEXTAREA") return;
    updateScope(scope);
  });
  const editorCards = document.querySelector("[data-report-cards]");
  if (editorCards) new MutationObserver(() => initMulti(editorCards)).observe(editorCards, {childList:true});

  root.querySelectorAll('[data-chart="table"] table.report-results').forEach(initReportTablePagination);

  const palette = ["#4257a5", "#278168", "#b65b33", "#9269af", "#28789d", "#a86e11", "#b3446c", "#5c6b78"];
  root.querySelectorAll(".report-chart").forEach((chart, chartIndex) => {
    const rows = [...chart.querySelectorAll("[data-point-value]")];
    const tip = document.createElement("div");
    tip.className = "report-point-tooltip"; tip.id = `report-tooltip-${chartIndex}`; tip.setAttribute("role", "tooltip"); tip.hidden = true; chart.append(tip);
    let hideTimer;
    if (typeof tip.showPopover === 'function') tip.setAttribute('popover','manual');
    const hideTip = () => { if(typeof tip.hidePopover === 'function' && tip.matches(':popover-open')) tip.hidePopover(); tip.hidden = true; };
    tip.addEventListener('pointerenter', () => clearTimeout(hideTimer));
    tip.addEventListener('pointerleave', hideTip);
    tip.addEventListener('keydown', event => { if(event.key === 'Escape') hideTip(); });
    const describe = row => row.reportTooltip ? reportBarTooltipText(row.reportTooltip, row.dataset.seriesLabel) : reportPointText(row.dataset, chart.dataset.metricLabel);
      const attach = (target, row) => {
        const link = row.querySelector("[data-report-drill]");
        if (link) target.dataset.selectionGroup = new URL(link.href).searchParams.get("group");
      target.setAttribute("tabindex", "0"); target.setAttribute("role", link ? "button" : "img");
      target.setAttribute("aria-label", describe(row)); target.setAttribute("aria-describedby", tip.id);
      const show = event => {
        if (chart.dataset.showTooltip === 'hide') return;
        clearTimeout(hideTimer);
        if(row.reportTooltip) renderReportBarTooltip(tip, row.reportTooltip, row.dataset.seriesLabel);
        else { tip.classList.remove('report-tooltip-rich'); tip.textContent = describe(row); }
        tip.hidden = false;
        if (typeof tip.showPopover === 'function') tip.showPopover();
        const box = target.getBoundingClientRect();
        const x = event?.clientX || box.left + box.width / 2;
        const y = event?.clientY || box.top;
        tip.style.left = `${Math.max(8, Math.min(x + 12, window.innerWidth - tip.offsetWidth - 8))}px`;
        tip.style.top = `${Math.max(8, Math.min(y + 14, window.innerHeight - tip.offsetHeight - 8))}px`;
      };
      target.addEventListener("pointerenter", show); target.addEventListener("pointermove", show);
      target.addEventListener("focus", show); target.addEventListener("pointerleave", () => { hideTimer = setTimeout(hideTip, 150); });
      target.addEventListener("blur", hideTip);
      target.addEventListener("click", event => {
        if (link && link.contains(event.target)) { hideTip(); return; }
        hideTip();
        link?.dispatchEvent(new MouseEvent("click", {bubbles:true, cancelable:true, ctrlKey:event.ctrlKey, metaKey:event.metaKey, shiftKey:event.shiftKey}));
      });
      target.addEventListener("keydown", event => {
        if (event.key === "Escape") hideTip();
        if (row.reportTooltip && !tip.hidden && ['PageDown','PageUp'].includes(event.key)) {
          event.preventDefault(); tip.scrollBy(0,(event.key === 'PageDown' ? 1 : -1)*tip.clientHeight*.8);
        }
        if (link && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); hideTip(); link.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, ctrlKey:event.ctrlKey, metaKey:event.metaKey, shiftKey:event.shiftKey})); }
      });
    };
    const overview = chart.closest('.report-sales-overview');
    const layout = overview?.dataset.readerLayout;
    const legendColors = new Map([...chart.querySelectorAll('.report-series-legend span')].map((entry,i)=>[entry.textContent.trim(),['#737373','#f15a60','#7ac36a','#5a9bd4','#faa75a','#9e67ab','#ce7058','#d17fb1','#7dd3ef','#ee8ab5'][i%10]]));
    const contrast = ['#0072b2','#d55e00','#009e73','#cc79a7','#e69f00','#56b4e9','#333333','#806400'];
    const overviewColor = (label, fallback) => chart.dataset.palette === 'accessible' ? contrast[[...label].reduce((sum, ch) => (sum * 31 + ch.codePointAt(0)) >>> 0, 0) % contrast.length] : chart.dataset.classificationColors === 'true' ? fallback : layout === 'dealer_overview' ? legendColors.get(label)||fallback : reportReaderColor(layout, label, fallback, overview?.dataset.reportEnergy);
    if (overview || chart.dataset.palette === 'accessible') {
      rows.forEach(row => { row.dataset.pointColor = overviewColor(row.dataset.pointLabel, row.dataset.pointColor); });
      chart.querySelectorAll('.report-series-legend span').forEach(entry => {
        const dot = entry.querySelector('i'); if (dot) dot.style.background = overviewColor(entry.textContent.trim(), dot.style.background);
      });
      rows.forEach(row => {
        row.dataset.pointScope = chart.querySelector('.report-candidate-note') ? '候選分類範圍' : '完整篩選範圍';
        if (row.hasAttribute('data-stack-segment')) row.dataset.pointPercentage = reportFraction(row.dataset.pointValue, chart.dataset.total);
      });
      const explanation = overview?.querySelector('.report-reader-description');
      chart.querySelectorAll('.report-notice').forEach(note => {
        if (!explanation) return;
        if (!note.textContent.trim().startsWith('比對用分類：')) return;
        const exists = [...explanation.querySelectorAll('[data-overview-classification]')].some(item => item.textContent === note.textContent);
        if (exists) note.remove();
        else { note.dataset.overviewClassification = 'true'; explanation.append(note); }
      });
    }
    if (['stacked','bar'].includes(chart.dataset.chart)) {
      const mainRows = [...chart.querySelectorAll('.report-results tr[data-point-value]')];
      const groups = [...chart.querySelectorAll('.report-stack-row')];
      mainRows.forEach((row,index) => {
        const segments = chart.dataset.chart === 'stacked' ? [...groups[index].querySelectorAll('[data-stack-segment]')] : null;
        const bar = row.querySelector('.report-bar-track');
        if (bar && !overview && chart.dataset.palette !== 'accessible') row.dataset.pointColor = getComputedStyle(bar.firstElementChild).backgroundColor;
        if (bar && chart.dataset.palette === 'accessible') bar.firstElementChild.style.backgroundColor = row.dataset.pointColor;
        const values = segments?.map(segment => ({label:segment.dataset.seriesLabel,value:segment.dataset.pointValue,
          display:segment.dataset.pointDisplay,color:(overview || chart.dataset.palette === 'accessible') ? overviewColor(segment.dataset.seriesLabel,segment.style.backgroundColor) : segment.style.backgroundColor}));
        if (chart.dataset.palette === 'accessible') segments?.forEach(segment => { segment.style.backgroundColor = overviewColor(segment.dataset.seriesLabel, segment.style.backgroundColor); });
        row.reportTooltip = reportBarTooltip(row.dataset,values,chart.dataset.metricLabel,chart.dataset.total,chart.querySelector('.report-candidate-note') ? '候選分類範圍' : '完整篩選範圍');
        segments?.forEach(segment => { segment.reportTooltip = row.reportTooltip; });
        if(bar) {
          attach(bar,row);
          const value = row.querySelector('td > span'); value.hidden = true;
          const end = document.createElement('span'); end.className = 'report-bar-end-value'; end.textContent = row.dataset.pointDisplay;
          bar.firstElementChild.append(end); bar.classList.add('report-bar-total-only');
        }
      });
    }
    rows.filter(row => row.hasAttribute('data-stack-segment')).forEach(row => {
      attach(row,row);
      const link = row.querySelector('[data-report-drill]'); if(link) link.tabIndex = -1;
    });
    if (layout === 'analysis_overview' && ['stacked','bar'].includes(chart.dataset.chart)) renderReportAnalysis(chart, attach);
    if (overview && layout !== 'analysis_overview' && chart.dataset.chart === 'stacked') {
      const stacks = chart.querySelector('.report-stacks');
      const groups = [...stacks.querySelectorAll('.report-stack-row')];
      if (groups.length) {
        const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
        const wideElectric = (['electric_overview','gasoline_overview'].includes(layout) && chart.classList.contains('report-chart--wide')) || ['platform_overview','dealer_overview'].includes(layout);
        const width = wideElectric ? Math.max(740, chart.clientWidth - 24) : 740;
        const left = layout === 'dealer_overview' ? 190 : 108, right = 100, top = 8, rowHeight = 26;
        const bottom = top + rowHeight * groups.length, plotWidth = width - left - right;
        const totals = [...chart.querySelectorAll('.report-results tr[data-point-value]')].map(row => Number(row.dataset.pointValue));
        const monthRows = [...chart.querySelectorAll('.report-results tr[data-point-value]')];
        const maximum = reportAxisMaximum(totals);
        svg.classList.add('report-overview-plot'); svg.setAttribute('viewBox', `0 0 ${width} ${bottom + 30}`);
        svg.setAttribute('aria-label', chart.querySelector('h2').textContent + ' 水平堆疊圖');
        const element = (tag, attrs, text) => {
          const item = document.createElementNS(ns, tag);
          Object.entries(attrs).forEach(([key, value]) => item.setAttribute(key, String(value)));
          if (text !== undefined) item.textContent = text;
          svg.append(item); return item;
        };
        for (let index = 0; index <= 4; index++) {
          const x = left + plotWidth * index / 4;
          element('line', {x1:x,x2:x,y1:top,y2:bottom,stroke:'var(--line)'});
          element('text', {x,y:bottom+22,'text-anchor':'middle',fill:'currentColor','font-size':17}, String(maximum * index / 4));
        }
        groups.forEach((group, index) => {
          const y = top + index * rowHeight;
          const month = monthRows[index];
          const segments = [...group.querySelectorAll('[data-stack-segment]')];
          month.dataset.pointSummary = reportMonthSummary(month.dataset.pointLabel, segments.map(segment => ({label:segment.dataset.seriesLabel,value:segment.dataset.pointValue,display:segment.dataset.pointDisplay})), month.dataset.pointDisplay);
          element('text', {x:left-8,y:y+20,'text-anchor':'end',fill:'currentColor','font-size':17}, group.querySelector('.report-stack-caption strong').textContent);
          let offset = 0;
          group.querySelectorAll('[data-stack-segment]').forEach(segment => {
            const value = Number(segment.dataset.pointValue || 0), segmentWidth = Math.max(0, value) / maximum * plotWidth;
            if (!segmentWidth) return;
            const rect = element('rect', {x:left+offset,y:y+2,width:segmentWidth,height:23,fill:overviewColor(segment.dataset.seriesLabel, segment.style.backgroundColor)});
            if (layout === 'dealer_overview') attach(rect, segment);
            else rect.setAttribute('aria-hidden', 'true');
            offset += segmentWidth;
          });
          const totalX = left + Math.max(0,Number(month.dataset.pointValue)) / maximum * plotWidth + 10;
          element('text', {x:totalX,y:y+20,fill:'currentColor','font-size':17,'class':'report-bar-total-label','pointer-events':'none'}, month.dataset.pointDisplay);
          // 整列包含短小系列與空白處，滑鼠提示及點選皆使用月份，不誤變為月份加通路。
          const hit = element('rect', {x:layout === 'dealer_overview' ? 0 : left,y:y+1,width:layout === 'dealer_overview' ? left-5 : plotWidth,height:24,fill:'transparent'});
          hit.classList.add('report-month-target'); attach(hit, month);
        });
        let brushStart = null, brushing = false, suppressClick = false;
        const points = [...svg.querySelectorAll('.report-month-target')];
        const clearBrush = () => points.forEach(point => point.classList.remove('report-brush-candidate'));
        const range = (a,b) => points.filter(point => { const r=point.getBoundingClientRect(); return r.bottom >= Math.min(a,b) && r.top <= Math.max(a,b); });
        svg.addEventListener('pointerdown', event => {
          if (event.button !== 0 || event.pointerType === 'touch' || !event.target.closest('.report-month-target')) return;
          brushStart = event.clientY; brushing = false;
        });
        svg.addEventListener('pointermove', event => {
          if (brushStart === null || !event.buttons) return;
          if (Math.abs(event.clientY-brushStart) > 5) {
            brushing = true; svg.setPointerCapture(event.pointerId); hideTip(); clearBrush();
            range(brushStart,event.clientY).forEach(point => point.classList.add('report-brush-candidate'));
          }
        });
        svg.addEventListener('pointerup', event => {
          if (brushing) {
            suppressClick = true;
            chart.dispatchEvent(new CustomEvent('report-view-change',{bubbles:true,detail:{card:Number(chart.dataset.chartIndex),groups:range(brushStart,event.clientY).map(point=>point.dataset.selectionGroup),additive:event.ctrlKey || event.metaKey}}));
            setTimeout(()=>{ suppressClick=false; },0);
          }
          brushStart = null; brushing = false; clearBrush();
          if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
        });
        svg.addEventListener('pointercancel',()=>{ brushStart=null; brushing=false; clearBrush(); });
        svg.addEventListener('click',event=>{ if (suppressClick) { event.preventDefault(); event.stopImmediatePropagation(); } },true);
        stacks.before(svg);
      }
      // 已有可聚焦的圖形及提示；保留原 DOM 作為連結來源，不重複呈現展開操作。
      stacks.hidden = true;
    }
    if (chart.dataset.chart === "line") {
      const validRows = rows.filter(row => row.dataset.pointValue !== "" && Number.isFinite(Number(row.dataset.pointValue)));
      chart.querySelectorAll("svg circle").forEach((dot, index) => { dot.setAttribute("r", "7"); attach(dot, validRows[index]); });
      chart.querySelectorAll("svg polyline").forEach(line => { line.style.pointerEvents = "none"; });
    }
    if (chart.dataset.chart === "donut") {
      const total = Number(chart.dataset.total);
      const host = chart.querySelector("[data-line-chart]");
      if (total > 0 && rows.length) {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", "0 0 300 300"); svg.classList.add("report-donut");
        const solid = layout === 'analysis_overview' && overview.querySelectorAll('[data-chart-index]').length === 4;
        if (solid) svg.classList.add('report-solid-pie');
        const ring = (color, fraction, offset) => {
          const circle = document.createElementNS(ns, "circle");
          for (const [key, value] of Object.entries({cx:150,cy:150,r:solid?75:100,fill:"none",stroke:color,"stroke-width":solid?150:46,pathLength:100,"stroke-dasharray":`${fraction} ${100-fraction}`,"stroke-dashoffset":-offset,transform:"rotate(-90 150 150)"})) circle.setAttribute(key, String(value));
          svg.append(circle); return circle;
        };
        ring("var(--line)", 100, 0); let offset = 0;
        rows.forEach((row, index) => {
          const fraction = reportFraction(row.dataset.pointValue, total);
          if (!fraction) return;
          const color = row.dataset.pointColor || palette[index % palette.length];
          attach(ring(color, fraction, offset), row);
          if (overview && fraction >= 2) {
            const angle = (offset + fraction / 2) * Math.PI / 50 - Math.PI / 2;
            const label = document.createElementNS(ns, 'text');
            for (const [key,value] of Object.entries({x:150+100*Math.cos(angle),y:155+100*Math.sin(angle),'text-anchor':'middle',fill:'#fff','font-size':14,'pointer-events':'none'})) label.setAttribute(key,String(value));
            label.textContent = `${fraction.toFixed(1)}%`; svg.append(label);
          }
          offset += fraction;
          const swatch = document.createElement("span"); swatch.className = "report-legend-dot"; swatch.style.background = color;
          row.querySelector("th").prepend(swatch);
        });
        if (!overview) { const text = document.createElementNS(ns, "text"); text.setAttribute("x", "150"); text.setAttribute("y", "154"); text.setAttribute("text-anchor", "middle"); text.setAttribute("fill", "currentColor"); text.textContent = chart.querySelector(".report-score strong").textContent; svg.append(text); }
        host.append(svg);
        if (overview) resizeReportDonutLabels(chart);
        if (offset < 99.99) { const note = document.createElement("p"); note.className = "report-muted"; note.textContent = "灰色區域為未顯示群組；占比以完整篩選範圍計算。"; host.append(note); }
      } else host.textContent = "目前沒有可呈現的正值資料。";
    }
    if (overview) {
      const table = chart.querySelector('.report-table-wrap');
      if (table && chart.dataset.chart === 'donut') {
        const legend = document.createElement('div'); legend.className = 'report-overview-legend';
        rows.forEach(row => {
          const link = row.querySelector('[data-report-drill]');
          if (!link) return;
          const entry = link.cloneNode(true), dot = document.createElement('i'); dot.style.background = row.dataset.pointColor;
          entry.prepend(dot); entry.append(` ${Number(row.dataset.pointPercentage || 0).toFixed(1)}%`); legend.append(entry);
        });
        chart.querySelector('[data-line-chart]').before(legend);
      }
      if (table) {
        if (['stacked', 'donut'].includes(chart.dataset.chart)) table.hidden = true;
      }
      if (typeof initReportOverviewTools === 'function') initReportOverviewTools(chart);
    }
    const fontSize = Number(chart.dataset.fontSize);
    if ([16,18,20,24].includes(fontSize)) {
      chart.style.fontSize = `${fontSize}px`;
      chart.querySelectorAll('svg text, .report-overview-legend, .report-series-legend, .report-results, .report-card-toolbar h2').forEach(el => el.style.fontSize = `${fontSize}px`);
    }
    if (['left','center','right'].includes(chart.dataset.titleAlign)) {
      const heading = chart.querySelector('.report-card-toolbar h2'); if (heading) heading.style.setProperty('text-align', chart.dataset.titleAlign, 'important');
    }
    if (chart.dataset.showLegend === 'hide') chart.querySelectorAll('.report-overview-legend,.report-series-legend').forEach(el => el.hidden = true);
    chart.querySelector("[data-chart-fullscreen]")?.addEventListener("click", () => {
      // 使用頁內放大，不倚賴瀏覽器全螢幕授權；Escape 或原按鈕即可返回。
      const expanded = chart.classList.toggle("report-chart-expanded");
      chart.querySelector("[data-chart-fullscreen]").textContent = expanded ? "返回原大小" : "放大圖表";
      if (expanded) chart.scrollIntoView({block:"start", behavior:"smooth"});
    });
    chart.addEventListener("keydown", event => { if (event.key === "Escape") { chart.classList.remove("report-chart-expanded"); const button = chart.querySelector("[data-chart-fullscreen]"); if (button) button.textContent = "放大圖表"; } });
  });

}
if (typeof document !== "undefined") initReportVisuals(document);
(() => {
  if (typeof document === "undefined") return;
  document.addEventListener("click", event => {
    document.querySelectorAll("[data-report-multi]").forEach(control => { if (!control.contains(event.target)) control.open = false; });
  });
  const panel = document.querySelector("[data-inline-detail]");
  if (!panel) return;
  let controller, sequence = 0, currentUrl = null;
  const body = panel.querySelector("[data-detail-body]");
  const status = panel.querySelector("[data-detail-status]");
  const selection = panel.querySelector("[data-detail-selection]");
  let updateController, updateSequence = 0, desiredUrl = new URL((window.reportPreviewLocation || location.href)), failedUrl, syncingFilters = false;
  const selectionQueue = reportDebounce(url => updateReport(url));
  const reader = document.querySelector(".report-reader-main");
  const overview = reader.classList.contains('report-sales-overview');
  if (overview && matchMedia('(pointer: coarse)').matches) reader.querySelector('[data-report-selection-hint]').textContent = '點選查看數字並連動 · 連點複選 · 再點取消';
  if (reader.classList.contains('report-sales-overview')) {
    const description = reader.querySelector('.report-reader-description');
    reader.querySelectorAll(':scope > .report-context,:scope > .report-scope-summary').forEach(item => description.append(item));
  }
  const updateStatus = reader.querySelector("[data-report-update-status]");
  const retry = reader.querySelector("[data-report-retry]");
  function queueOverviewUpdate(url, message) {
    ++updateSequence; updateController?.abort(); selectionQueue.cancel();
    desiredUrl = new URL(url, (window.reportPreviewLocation || location.href)); paintSelection();
    reader.setAttribute('aria-busy', 'true'); retry.hidden = true;
    updateStatus.textContent = message;
    selectionQueue.schedule(desiredUrl.href);
  }
  const selectedItems = () => { try { return JSON.parse(desiredUrl.searchParams.get("focus") || "[]"); } catch { return []; } };
  function paintSelection() {
    const selected = selectedItems();
    reader.querySelectorAll("[data-report-drill]").forEach(link => {
      const card = Number(link.closest("[data-chart-index]")?.dataset.chartIndex);
      const group = new URL(link.href).searchParams.get("group");
      const active = selected.some(item => item.card === card && [].concat(item.group).includes(group));
        link.setAttribute("role", "button");
        link.setAttribute("aria-pressed", String(active));
        (link.closest("[data-point-value]") || link).classList.toggle("report-row-selected", active);
      });
      reader.querySelectorAll("[data-selection-group]").forEach(target => {
        const card = Number(target.closest("[data-chart-index]")?.dataset.chartIndex);
        const active = selected.some(item => item.card === card && [].concat(item.group).includes(target.dataset.selectionGroup));
        target.setAttribute("aria-pressed", String(active));
        target.classList.toggle("report-point-selected", active);
      });
  }
  async function updateReport(url, push = true) {
    selectionQueue.cancel();
    updateController?.abort(); updateController = new AbortController();
    const own = updateController, ticket = ++updateSequence;
    desiredUrl = new URL(url, (window.reportPreviewLocation || location.href)); failedUrl = desiredUrl.href;
    const target = desiredUrl.href;
    reader.setAttribute("aria-busy", "true"); updateStatus.textContent = "正在連動更新…"; retry.hidden = true;
    const timer = setTimeout(() => own.abort(), 20000);
    try {
      const response = await (window.reportPreviewFetch || fetch)(target, {signal:own.signal, credentials:"same-origin", headers:{"X-Requested-With":"XMLHttpRequest"}});
      if (!response.ok || response.redirected) throw new Error(response.status === 409 ? "報表版本已更新，請重新整理後再操作。" : "更新失敗，請確認登入與查看權限。");
      const doc = new DOMParser().parseFromString(await response.text(), "text/html");
      const next = doc.querySelector(".report-reader-main"), nextGrid = next?.querySelector(".report-grid");
      if (!nextGrid || next.querySelector('[role="alert"]') || next.querySelector(".errorlist")) throw new Error("篩選無法套用，請檢查條件或重新整理。");
      if (ticket !== updateSequence) return;
      const grid = reader.querySelector(".report-grid");
      const focused = document.activeElement;
      const focusPoint = overview && grid.contains(focused) && focused.dataset.selectionGroup ? {
        card: focused.closest('[data-chart-index]').dataset.chartIndex, group: focused.dataset.selectionGroup
      } : null;
      grid.replaceWith(document.importNode(nextGrid, true));
      for (const selector of [".report-context", "[data-report-selection-tags]"]) {
        reader.querySelector(selector).replaceWith(document.importNode(next.querySelector(selector), true));
      }
      const oldRecords = reader.querySelector(".report-record-panel"), newRecords = next.querySelector(".report-record-panel");
      if (newRecords) {
        const imported = document.importNode(newRecords, true);
        if (oldRecords) oldRecords.replaceWith(imported); else reader.querySelector("[data-report-exploration]").after(imported);
      } else oldRecords?.remove();
      const currentForm = reader.querySelector('.report-filter'), nextForm = next.querySelector('.report-filter');
      for (const field of currentForm.elements) {
        if (!field.name) continue;
        const sources = [...nextForm.elements].filter(input => input.name === field.name);
        if (field.type === 'checkbox' || field.type === 'radio') field.checked = sources.some(input => input.value === field.value && input.checked);
        else if (sources.length) field.value = sources[0].value;
      }
      syncingFilters = true;
      try { currentForm.querySelectorAll('[data-report-multi]').forEach(control => { control.syncFromServer?.(); control.dispatchEvent(new Event('change', {bubbles:true})); }); }
      finally { syncingFilters = false; }
      currentForm.querySelector('.report-advanced-filter summary').textContent = nextForm.querySelector('.report-advanced-filter summary').textContent;
      ++sequence; controller?.abort(); panel.hidden = true; body.replaceChildren();
      reader.querySelector("[data-report-exploration]").classList.remove("has-detail");
      const newGrid = reader.querySelector(".report-grid");
      renderReportLines(newGrid); initReportVisuals(newGrid); paintSelection();
      if (focusPoint) {
        const replacement = [...newGrid.querySelectorAll('[data-selection-group]')].find(point => point.dataset.selectionGroup === focusPoint.group && point.closest('[data-chart-index]').dataset.chartIndex === focusPoint.card);
        replacement?.focus({preventScroll:true});
      }
      if (window.reportPreviewLocation) window.reportPreviewLocation = target;
      else if (push) history.pushState(null, "", target);
      updateStatus.textContent = "圖表與表格已同步更新";
      } catch (error) {
        if (ticket !== updateSequence) return;
        desiredUrl = new URL((window.reportPreviewLocation || location.href));
        paintSelection();
        updateStatus.textContent = reportUpdateError(error);
      retry.hidden = false;
    } finally { clearTimeout(timer); if (ticket === updateSequence) reader.removeAttribute("aria-busy"); }
  }
  paintSelection();
  reader.addEventListener('report-view-change', event => {
    const {card, sort, grain, reset, groups, additive} = event.detail;
    if (groups?.length && [...reader.querySelectorAll('[data-chart-index]')].find(item => item.dataset.chartIndex === String(card))?.dataset.crossFilter === 'off') return;
    const target = new URL(desiredUrl);
    target.searchParams.set('revision', reader.querySelector('.report-filter [name="revision"]').value);
    if (sort !== undefined) target.searchParams.set(`sort_${card}`, sort);
    if (grain !== undefined) target.searchParams.set(`grain_${card}`, grain);
    if (reset) { target.searchParams.delete(`sort_${card}`); target.searchParams.delete(`grain_${card}`); }
    if (grain !== undefined || reset) target.searchParams.set('focus', JSON.stringify(selectedItems().filter(item => item.card !== card)));
    if (groups?.length) {
      const selected = selectedItems();
      const currentGrain = target.searchParams.get(`grain_${card}`) || target.searchParams.get('grain') || '';
      const previous = selected.find(item => item.card === card && item.grain === currentGrain);
      const combined = [...new Set([...(additive && previous ? [].concat(previous.group) : []), ...groups])];
      target.searchParams.set('focus', JSON.stringify([...selected.filter(item=>item.card!==card),{card,group:combined,grain:currentGrain}]));
    }
    target.searchParams.delete('records_page');
    queueOverviewUpdate(target, '正在套用圖表查看方式…');
  });
  retry.addEventListener("click", () => updateReport(failedUrl));
  window.addEventListener("popstate", () => updateReport((window.reportPreviewLocation || location.href), false));
  if (overview) reader.querySelector('.report-filter').addEventListener('change', event => {
    if (syncingFilters || !event.target.closest('[data-report-multi]')) return;
    const target = new URL(new URL(window.reportPreviewLocation || location.href).pathname, (window.reportPreviewLocation || location.href));
    target.search = new URLSearchParams(new FormData(event.currentTarget)).toString();
    target.searchParams.set('focus', desiredUrl.searchParams.get('focus') || '');
    target.searchParams.delete('records_page');
    queueOverviewUpdate(target, '篩選已選取，可繼續選擇；圖表即將同步…');
  });
  document.addEventListener("click", event => {
    const clear = event.target.closest("[data-report-clear-filter],.report-filter-actions a,.report-record-panel .report-pagination a,[data-report-record-sort]");
    if (clear && !event.ctrlKey && !event.metaKey) { event.preventDefault(); updateReport(clear.href); }
  });
  reader.addEventListener("submit", event => {
    const form = event.target;
    if (!form.matches(".report-filter,.report-card-filters,[data-report-page-jump]")) return;
    event.preventDefault();
    const target = new URL(form.getAttribute("action") || new URL(window.reportPreviewLocation || location.href).pathname, (window.reportPreviewLocation || location.href));
    target.search = new URLSearchParams(new FormData(form)).toString();
    updateReport(target);
  });
  async function loadDetail(url, label) {
    controller?.abort(); controller = new AbortController(); const ownController = controller; const ticket = ++sequence;
    panel.hidden = false; panel.setAttribute("aria-busy", "true"); status.textContent = "正在讀取明細…";
    body.replaceChildren(); selection.textContent = label;
    document.querySelector("[data-report-exploration]").classList.add("has-detail");
    const target = new URL(url, (window.reportPreviewLocation || location.href)); target.searchParams.set("inline", "1"); currentUrl = target;
    const timeout = setTimeout(() => ownController.abort(), 15000);
    try {
      const response = await (window.reportPreviewFetch || fetch)(target, {signal:ownController.signal, credentials:"same-origin", headers:{"X-Requested-With":"XMLHttpRequest"}});
      if (!response.ok || response.redirected) throw new Error(response.status === 409 ? "報表已更新，請重新整理報表後再選取。" : "無法讀取明細，請確認登入與查看權限，或稍後再試。");
      const documentFragment = new DOMParser().parseFromString(await response.text(), "text/html");
      const content = documentFragment.querySelector("[data-detail-content]");
      if (!content) throw new Error("回應不是有效明細，請重新登入或稍後再試。");
      if (ticket !== sequence) return;
      body.replaceChildren(document.importNode(content, true)); status.textContent = "明細已更新，圖表與篩選條件保留。";
      selection.focus({preventScroll:true});
      if (window.innerWidth <= 1100) panel.scrollIntoView({block:"start", behavior:"smooth"});
    } catch (error) {
      if (ticket !== sequence) return;
      status.textContent = error.name === "AbortError" ? "讀取逾時，請重新點選分類再試。" : error.message;
    } finally { clearTimeout(timeout); if (ticket === sequence) panel.removeAttribute("aria-busy"); }
  }
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!form.matches('[data-detail-jump]')) return;
    event.preventDefault();
    const target = new URL(form.action, currentUrl);
    target.search = new URLSearchParams(new FormData(form)).toString();
    loadDetail(target, selection.textContent);
  });
  document.addEventListener("click", event => {
    const link = event.target.closest("a[data-report-drill],a[data-detail-page],a[data-report-open-detail]");
    if (!link || event.altKey || event.button || (!link.matches('[data-report-drill]') && (event.ctrlKey || event.metaKey || event.shiftKey))) return;
    event.preventDefault();
    if (link.matches("[data-report-open-detail]")) { loadDetail(link.href, "目前篩選的來源訂單"); return; }
    if (link.matches("[data-report-drill]")) {
      if (link.closest('[data-chart-index]')?.dataset.crossFilter === 'off') return;
      if (updateStatus) {
        const target = new URL(link.href);
        const group = target.searchParams.get("group");
        if (!group?.startsWith("o:")) {
          const filters = new URLSearchParams(desiredUrl.search);
          filters.set("revision", target.searchParams.get("revision"));
          let selected;
          try { selected = JSON.parse(filters.get("focus") || "[]"); } catch { selected = []; }
          const index = Number(link.closest("[data-chart-index]").dataset.chartIndex);
          try {
            selected = reportToggleSelection(selected, index, group, filters.get(`grain_${index}`) || filters.get("grain") || "", event.ctrlKey || event.metaKey || event.shiftKey || reader.querySelector("[data-report-multiple]")?.checked || (overview && matchMedia('(pointer: coarse)').matches));
          } catch (error) { updateStatus.textContent = error.message; return; }
          filters.set("focus", JSON.stringify(selected));
          filters.delete("group"); filters.delete("inline"); filters.delete("records_page");
          const nextUrl = `${new URL(window.reportPreviewLocation || location.href).pathname}?${filters.toString()}`;
          if (overview) {
            // 在等待下一次點選時即淘汰舊請求，避免舊回應替換使用者正在操作的圖形。
            queueOverviewUpdate(nextUrl, `已選 ${selected.reduce((sum, item) => sum + [].concat(item.group).length, 0)} 個分類，可繼續點選…`);
          } else updateReport(nextUrl);
          return;
        }
        // 動態 Top N 的其他集合不冒充穩定分類，保留既有的精確下鑽。
      }
      document.querySelectorAll(".report-row-selected").forEach(row => row.classList.remove("report-row-selected"));
      const row = link.closest("[data-point-label]") || link.closest(".report-stack-row");
      row?.classList.add("report-row-selected");
      loadDetail(link.href, `已選取：${row?.dataset.pointLabel || link.getAttribute("aria-label") || link.textContent.trim()}`);
    } else loadDetail(new URL(link.getAttribute("href"), currentUrl).href, selection.textContent);
  });
  panel.querySelector("[data-detail-clear]").addEventListener("click", () => {
    ++sequence; controller?.abort(); panel.hidden = true; body.replaceChildren();
    document.querySelector("[data-report-exploration]").classList.remove("has-detail");
    const selected = document.querySelector(".report-row-selected"); selected?.querySelector("a")?.focus(); selected?.classList.remove("report-row-selected");
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !panel.hidden) panel.querySelector('[data-detail-clear]').click(); });
})();
