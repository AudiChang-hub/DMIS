/* 圖表互動只讀取伺服器已授權資料；不修改報表或訂單。 */
function reportPointText(data, metric) {
  if (data.pointSummary) return data.pointSummary;
  let text = `${data.pointLabel}\n${metric}：${data.pointDisplay}`;
  if (metric !== "訂單台數") text += `\n訂單台數：${data.pointCount}`;
  if (data.pointPercentage !== "" && Number.isFinite(Number(data.pointPercentage))) text += `\n占${data.pointScope || '完整篩選範圍'}：${Number(data.pointPercentage).toFixed(1)}%`;
  return text;
}
/* 圖表分類色（T-182）：一律引用 app.css 的 --chart-s1～s8／--chart-other，淺深色自動切換。
   同一分類在每一頁固定同色（依固定清單順序），不依排名或篩選後的名次換色；「其他」類固定中性灰。 */
const REPORT_SERIES_COLORS = Array.from({length:8}, (_, index) => `var(--chart-s${index + 1})`);
const REPORT_OTHER_COLOR = 'var(--chart-other)';
const REPORT_FIXED_SLOTS = {'車行':0,'馭盛':1,'網路平台':2,'店內員工':3,'展場':4,
  '白牌電車':0,'速克達':1,'綠牌電車':2,'擋車':3,'微型電車':4};
const REPORT_NEUTRAL_LABELS = new Set(['公司或其他','其他','其他系列（合併）','生日未填','生日異常','未填寫或格式錯誤']);
function reportSlotColor(index) { return REPORT_SERIES_COLORS[((index % 8) + 8) % 8]; }
function reportOverviewColor(label, fallback) {
  if (REPORT_NEUTRAL_LABELS.has(label)) return REPORT_OTHER_COLOR;
  return label in REPORT_FIXED_SLOTS ? reportSlotColor(REPORT_FIXED_SLOTS[label]) : fallback;
}
function reportElectricColor(label, fallback) {
  const models = ['EV060L','EV062','EV076S','EV076','EV076SZV','EV070V','EV062FL','EZ1','EZZY','SHINE','TSV57','JEGO','GogoroVIVAMIX','Gogoro2D','VIVABASIC','Ur2','BOBE','S2ABS','M02','M01'];
  if (label in REPORT_FIXED_SLOTS || REPORT_NEUTRAL_LABELS.has(label)) return reportOverviewColor(label, fallback);
  const index = models.indexOf(label);
  return index >= 0 ? reportSlotColor(index) : fallback;
}
function reportReaderColor(layout, label, fallback, energy) {
  if (layout === 'analysis_overview') return reportAnalysisColor(label, fallback);
  if (REPORT_NEUTRAL_LABELS.has(label)) return REPORT_OTHER_COLOR;
  if (layout === 'gasoline_overview') {
    const models = ['UQ125DA','UQ125','UC125DA','UC125','UT125XDA','UT125XZ','UG125','GSX-R150','GSX250F','GSX250'];
    const i=models.indexOf(label);
    return i<0 ? reportElectricColor(label,fallback) : reportSlotColor(i);
  }
  if (layout === 'platform_overview') {
    const platforms = energy === '油車' ? ['YAHOO','FRIDAY','百利市','PC','小樹購','燦坤','YAHOO+假展場'] : ['MOMO','小樹購員購','PC','YAHOO','蝦皮','MOMO員購','燦坤'];
    const i=platforms.indexOf(label); return i<0 ? fallback : reportSlotColor(i);
  }
  return layout === 'electric_overview' ? reportElectricColor(label,fallback) : reportOverviewColor(label,fallback);
}
function reportMonthSummary(label, segments, total) {
  return [label, ...segments.filter(item => Number(item.value)).map(item => `${item.label}：${item.display}`), `總計：${total}`].join('\n');
}
/* 空狀態（T-182）：沒有資料時給圖示、原因與下一步，不只留一行小字。 */
function reportEmptyState(chart) {
  const doc = chart.ownerDocument;
  const box = doc.createElement('div'); box.className = 'report-empty'; box.setAttribute('role', 'status');
  box.innerHTML = '<span class="report-empty__icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 19.5h16M7 16v-5M12 16V7M17 16v-3"/></svg></span>';
  const title = doc.createElement('strong'); title.textContent = '這個範圍沒有可呈現的資料';
  const text = doc.createElement('p'); text.textContent = '目前沒有可呈現的正值資料。調整篩選條件，或清除篩選後再看。';
  box.append(title, text);
  const clear = doc.querySelector('.report-active-filters__clear, .report-active-filters [data-report-clear-filter]');
  if (clear) {
    const link = doc.createElement('a'); link.className = 'button ghost small'; link.href = clear.getAttribute('href'); link.dataset.reportClearFilter = '';
    link.textContent = clear.classList.contains('report-active-filters__clear') ? '全部清除篩選' : '移除篩選'; box.append(link);
  }
  return box;
}
function reportDateParts(label) {
  const match = /^(\d{4})(?:[/-](\d{1,2}))?(?:[/-](\d{1,2}))?$/.exec(String(label).trim());
  return match ? {year: match[1], month: match[2], day: match[3]} : null;
}
/* 堆疊圖（T-182）：依卡片實際寬度繪製，不再固定 740px 再撐出橫向捲動。
   月／年資料且卡片夠寬時畫直條（時間由左到右），其餘畫橫條；字級 12–13px，直條只標最高與最新的數字。 */
function reportStackPlot(chart, groups, totalsRows, {interactiveSegments = false, colorOf, attach}) {
  const ns = 'http://www.w3.org/2000/svg', doc = chart.ownerDocument, svg = doc.createElementNS(ns, 'svg');
  const box = chart.getBoundingClientRect(), style = getComputedStyle(chart);
  const inner = box.width - parseFloat(style.paddingLeft || 0) - parseFloat(style.paddingRight || 0) - parseFloat(style.borderLeftWidth || 0) - parseFloat(style.borderRightWidth || 0);
  const width = Math.max(260, Math.round(inner > 0 ? inner : 640));
  const element = (tag, attrs, text) => {
    const item = doc.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([key, value]) => item.setAttribute(key, String(value)));
    if (text !== undefined) item.textContent = text;
    svg.append(item); return item;
  };
  let order = groups.map((group, index) => ({group, row: totalsRows[index], label: group.querySelector('.report-stack-caption strong').textContent.trim()}));
  const dated = order.filter(item => reportDateParts(item.label)), undated = order.filter(item => !reportDateParts(item.label));
  const columns = ['month', 'year'].includes(chart.dataset.dimension) && dated.length >= 2 && width >= 560;
  if (columns) order = [...dated.sort((a, b) => a.label.localeCompare(b.label)), ...undated];
  const totals = order.map(item => Number(item.row.dataset.pointValue));
  const maximum = reportAxisMaximum(totals);
  order.forEach(item => {
    const segments = [...item.group.querySelectorAll('[data-stack-segment]')];
    item.row.dataset.pointSummary = reportMonthSummary(item.row.dataset.pointLabel, segments.map(segment => ({label:segment.dataset.seriesLabel,value:segment.dataset.pointValue,display:segment.dataset.pointDisplay})), item.row.dataset.pointDisplay);
  });
  svg.classList.add('report-overview-plot', columns ? 'report-overview-plot--columns' : 'report-overview-plot--rows');
  svg.setAttribute('aria-label', chart.querySelector('h2').textContent + (columns ? ' 直向堆疊圖' : ' 水平堆疊圖'));
  const peak = totals.indexOf(Math.max(...totals)), latest = columns ? dated.length - 1 : -1;
  const tick = value => Number(value).toLocaleString('zh-TW');
  if (columns) {
    const left = 44, right = 8, top = 24, plotHeight = width < 760 ? 200 : 240, bottom = top + plotHeight, plotWidth = width - left - right;
    const step = plotWidth / order.length, barWidth = Math.max(4, Math.min(40, step * .66));
    for (let index = 0; index <= 4; index++) {
      const y = bottom - plotHeight * index / 4;
      element('line', {x1:left, x2:width - right, y1:y, y2:y, class:index ? 'report-plot-grid' : 'report-plot-base'});
      element('text', {x:left - 8, y:y + 4, 'text-anchor':'end', class:'report-plot-tick'}, tick(maximum * index / 4));
    }
    const every = Math.max(1, Math.ceil(order.length / Math.max(1, Math.floor(plotWidth / 52))));
    let lastYear = '';
    order.forEach((item, index) => {
      const x = left + step * index + (step - barWidth) / 2;
      let offset = 0;
      item.group.querySelectorAll('[data-stack-segment]').forEach(segment => {
        const value = Math.max(0, Number(segment.dataset.pointValue || 0)), h = value / maximum * plotHeight;
        if (!h) return;
        const rect = element('rect', {x, y:bottom - offset - h, width:barWidth, height:h, fill:colorOf(segment.dataset.seriesLabel, segment.style.backgroundColor), class:'report-plot-segment'});
        if (interactiveSegments) attach(rect, segment); else rect.setAttribute('aria-hidden', 'true');
        offset += h;
      });
      if (index === peak || index === latest) element('text', {x:x + barWidth / 2, y:bottom - offset - 7, 'text-anchor':'middle', class:'report-bar-total-label report-plot-value', 'pointer-events':'none'}, item.row.dataset.pointDisplay);
      const parts = reportDateParts(item.label);
      if (index % every === 0 || index === order.length - 1) {
        element('text', {x:x + barWidth / 2, y:bottom + 17, 'text-anchor':'middle', class:'report-plot-tick'}, parts?.month ? `${Number(parts.month)}月` : item.label);
        if (parts?.month && parts.year !== lastYear) { element('text', {x:x + barWidth / 2, y:bottom + 32, 'text-anchor':'middle', class:'report-plot-tick report-plot-year'}, parts.year); lastYear = parts.year; }
      }
      const hit = element('rect', {x:left + step * index, y:top - 18, width:step, height:plotHeight + 18, fill:'transparent'});
      hit.classList.add('report-month-target'); attach(hit, item.row);
    });
    svg.setAttribute('viewBox', `0 0 ${width} ${bottom + 40}`);
  } else {
    const labelWidth = Math.round(interactiveSegments ? Math.min(180, width * .34) : Math.min(96, width * .26));
    const valueWidth = 52, top = 4, rowHeight = 30, barHeight = 18, plotWidth = width - labelWidth - valueWidth - 12;
    const bottom = top + rowHeight * order.length;
    // 估算字寬（中文約 13px、英數約 7.5px），超出標籤欄才截斷並保留完整名稱於提示。
    const fit = text => { let used = 0, out = ''; for (const ch of text) { used += ch.codePointAt(0) > 255 ? 13 : 7.5; if (used > labelWidth - 12) return out.slice(0, -1) + '…'; out += ch; } return out; };
    const steps = plotWidth < 260 ? 2 : 4; // 窄卡片只留 0、中間、最大三個刻度，數字不擠在一起。
    for (let index = 0; index <= steps; index++) {
      const x = labelWidth + plotWidth * index / steps;
      element('line', {x1:x, x2:x, y1:top, y2:bottom, class:index ? 'report-plot-grid' : 'report-plot-base'});
      element('text', {x, y:bottom + 18, 'text-anchor':index === 0 ? 'start' : index === steps ? 'end' : 'middle', class:'report-plot-tick'}, tick(maximum * index / steps));
    }
    order.forEach((item, index) => {
      const y = top + index * rowHeight;
      const short = fit(item.label);
      const name = element('text', {x:labelWidth - 10, y:y + rowHeight / 2 + 4, 'text-anchor':'end', class:'report-plot-label'}, short);
      if (short !== item.label) { const title = doc.createElementNS(ns, 'title'); title.textContent = item.label; name.append(title); }
      let offset = 0;
      item.group.querySelectorAll('[data-stack-segment]').forEach(segment => {
        const value = Math.max(0, Number(segment.dataset.pointValue || 0)), w = value / maximum * plotWidth;
        if (!w) return;
        const rect = element('rect', {x:labelWidth + offset, y:y + (rowHeight - barHeight) / 2, width:w, height:barHeight, fill:colorOf(segment.dataset.seriesLabel, segment.style.backgroundColor), class:'report-plot-segment'});
        if (interactiveSegments) attach(rect, segment); else rect.setAttribute('aria-hidden', 'true');
        offset += w;
      });
      element('text', {x:labelWidth + offset + 8, y:y + rowHeight / 2 + 4, class:'report-bar-total-label report-plot-value', 'pointer-events':'none'}, item.row.dataset.pointDisplay);
      // 整列包含短小系列與空白處，滑鼠提示及點選皆使用該分類，不誤變為分類加系列。
      const hit = element('rect', {x:interactiveSegments ? 0 : labelWidth, y:y + 1, width:interactiveSegments ? labelWidth - 5 : plotWidth, height:rowHeight - 2, fill:'transparent'});
      hit.classList.add('report-month-target'); attach(hit, item.row);
    });
    svg.setAttribute('viewBox', `0 0 ${width} ${bottom + 26}`);
  }
  return {svg, columns};
}
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
  const button = text => { const b = doc.createElement('button'); b.type = 'button'; b.className = 'button ghost small site-pagination__link'; b.textContent = text; return b; };
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
  // T-182：加入 2.5 倍刻度（僅限十位數以上，刻度仍為整數），96 台的軸頂是 100 而不是 200。
  const step = [1, 2, ...(power >= 10 ? [2.5] : []), 5, 10].find(value => value * power >= rough) * power;
  return Math.max(4, Math.ceil(step) * 4);
}
function reportDebounce(run, delay = 300, timers = globalThis) {
  let timer;
  return {
    cancel() { timers.clearTimeout(timer); },
    schedule(value, wait = delay) { timers.clearTimeout(timer); timer = timers.setTimeout(() => run(value), wait); }
  };
}
function reportUpdateError(error) {
  if (error.name === 'AbortError') return '更新逾時，保留上次成功畫面；請重試。';
  if (error.name === 'TypeError') return '暫時無法連線，保留上次成功畫面；請確認網路後重試。';
  return error.message || '無法完成更新，請稍後重試。';
}
// 篩選選了就自動套用（T-142）：回傳這次變更等多久再查詢，null 表示不觸發。
// 複選與下拉 300ms 防抖；日期等打完再查（鍵盤逐位輸入年份時 0002、0020 也是合法日期，不能拿去查）。
// 複選摘要（T-184）：拆成兩個選擇器時，這邊沒勾但另一邊有勾，代表這邊被排除，不是「不限」或「無資料」。
function reportMultiSummary(sourceStyle, selected, total, groupSelected) {
  if (selected && (!sourceStyle || selected < total)) return `已選 ${selected} 項`;
  if (sourceStyle && selected === total) return '全部';
  if (groupSelected) return '未選取';
  return sourceStyle ? '未選取（無資料）' : '不限（可複選）';
}

function reportFilterDelay(field) {
  const data = field?.dataset || {};
  if (!field || 'multiSearch' in data) return null;
  if ('reportMulti' in data || 'reportTreeProxy' in data) return 300;
  if (!field.name || ['hidden', 'search'].includes(field.type)) return null;
  if (field.type === 'date') return !field.value || Number(String(field.value).slice(0, 4)) >= 1900 ? 700 : null;
  return 300;
}
function reportDateRangeError(start, end) {
  return start && end && start > end ? '開始日期不可晚於結束日期，調整後會自動套用。' : '';
}
// 沒有原地更新的頁面（草稿核對）改為整頁送出；複選選單開著時等收合再送，避免勾到一半被重新載入。
function reportAutoSubmitFilters(form) {
  if (!form) return;
  const queue = reportDebounce(() => {
    const target = new URL(form.getAttribute('action') || location.pathname, location.href);
    target.search = new URLSearchParams([...new FormData(form)].filter(([, value]) => value !== '')).toString();
    location.assign(target);
  });
  let pendingMulti = null;
  form.addEventListener('change', event => {
    const wait = reportFilterDelay(event.target);
    const end = form.elements.namedItem('end');
    if (wait === null) return;
    const error = reportDateRangeError(form.elements.namedItem('start')?.value, end?.value);
    end?.setCustomValidity?.(error);
    if (error) { end.reportValidity?.(); queue.cancel(); return; }
    const multi = event.target.closest?.('[data-report-multi]');
    if (multi?.open) { pendingMulti = multi; return; }
    queue.schedule(null, wait);
  });
  form.addEventListener('toggle', event => {
    if (event.target !== pendingMulti || pendingMulti.open) return;
    pendingMulti = null; queue.schedule(null, 0);
  }, true);
}
if (typeof module !== "undefined" && module.exports) module.exports = {reportPointText, reportFraction, reportScopeCount, reportPageRange, reportToggleSelection, reportAxisMaximum, reportDebounce, reportUpdateError, reportOverviewColor, reportElectricColor, reportSlotColor, reportMonthSummary, initReportTablePagination};
if (typeof module !== "undefined" && module.exports) Object.assign(module.exports, {reportFilterDelay, reportDateRangeError, reportMultiSummary});
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
    const form = control.closest('form');
    // 車行／平台拆成兩個選擇器（T-184）：同名參數的勾選視為一組，全選、全部取消、只選此項都以整組判斷。
    const split = control.hasAttribute('data-multi-split') && form && fieldName;
    const groupInputs = () => split ? [...form.querySelectorAll('[data-multi-split] input[type="checkbox"]')].filter(input => input.name === fieldName) : inputs;
    const siblings = () => split ? [...form.querySelectorAll('[data-multi-split]')].filter(other => other.querySelector('input[type="checkbox"]')?.name === fieldName) : [control];
    const sourceStyle = control.closest('.report-sales-overview .report-filter-grid') && ['months','legacy_source','legacy_dealer'].includes(fieldName);
    const emptyField = sourceStyle && form.elements.namedItem(`empty_${fieldName}`);
    if (sourceStyle) {
      control.syncFromServer = () => {
        const group = groupInputs();
        if (!group.some(input => input.checked) && !['True','true','1'].includes(emptyField.value)) group.forEach(input => { input.checked = true; });
      };
      control.syncFromServer();
      control.querySelector('[data-multi-clear]').textContent = '全部取消';
      control.querySelector('.report-multi-options > small').textContent = '全部勾選表示不限；全部取消則不顯示資料。可點「只選此項」。';
      form.addEventListener('formdata', event => {
        const group = groupInputs(), selected = group.filter(input => input.checked);
        if (selected.length === group.length) event.formData.delete(fieldName);
        event.formData.set(`empty_${fieldName}`, selected.length ? '' : '1');
      });
      inputs.forEach(input => {
        const only = document.createElement('button'); only.type = 'button'; only.textContent = '只選此項';
        only.addEventListener('click', event => { event.preventDefault(); groupInputs().forEach(other => { other.checked = other === input; }); control.dispatchEvent(new Event('change', {bubbles:true})); });
        input.closest('label').append(only);
      });
    }
    const update = () => {
      const selected = inputs.filter(input => input.checked);
      const groupSelected = split && groupInputs().some(input => input.checked);
      control.querySelector("[data-multi-summary]").textContent = reportMultiSummary(sourceStyle, selected.length, inputs.length, groupSelected);
      const scope = control.closest(".report-card-scope");
      if (scope) updateScope(scope);
    };
    control.updateSummary = update;
    control.addEventListener("change", () => { siblings().forEach(other => (other.updateSummary || update)()); });
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
  // 台數統計（T-182）：台數欄加細長條、0 淡色、手機卡片的欄名。只處理 count_overview 的多欄彙總表。
  root.querySelectorAll('.report-reader-main[data-reader-layout="count_overview"] .report-summary-table').forEach(table => {
    if (table.dataset.countReady) return; table.dataset.countReady = 'true';
    const headers = [...table.tHead.rows[0].cells].map(cell => cell.textContent.replace(/[↕▲▼]/g, '').trim());
    const dims = table.tBodies[0].rows[0] ? [...table.tBodies[0].rows[0].cells].filter(cell => cell.tagName === 'TH').length : 1;
    const parse = text => Number(String(text).replace(/[^0-9.-]/g, ''));
    const counts = [...table.tBodies[0].rows].map(row => row.cells[dims]).filter(Boolean);
    const maximum = Math.max(0, ...counts.map(cell => parse(cell.textContent)).filter(Number.isFinite));
    [...table.tBodies[0].rows, ...(table.tFoot ? table.tFoot.rows : [])].forEach(row => {
      [...row.cells].filter(cell => cell.tagName === 'TD').forEach((cell, index) => {
        cell.dataset.label = headers[dims + index] || '';
        if (parse(cell.textContent) === 0 && cell.textContent.trim() !== '') cell.classList.add('is-zero');
      });
    });
    counts.forEach(cell => {
      const value = parse(cell.textContent), text = cell.textContent.trim();
      const wrap = document.createElement('span'); wrap.className = 'report-count-cell';
      const bar = document.createElement('span'); bar.className = 'report-count-cell__bar'; bar.setAttribute('aria-hidden', 'true');
      bar.style.width = `${maximum > 0 ? Math.max(0, value) / maximum * 100 : 0}%`;
      const label = document.createElement('span'); label.className = 'report-count-cell__value'; label.textContent = text;
      wrap.append(bar, label); cell.replaceChildren(wrap);
    });
  });

  const palette = REPORT_SERIES_COLORS;
  root.querySelectorAll(".report-chart").forEach((chart, chartIndex) => {
    const rows = [...chart.querySelectorAll("[data-point-value]")];
    // 空狀態（T-182）：表格只剩「此範圍沒有符合的訂單」或堆疊沒有任何列時，換成有圖示與下一步的空狀態（圓環圖另行處理）。
    if (chart.dataset.chart !== 'donut' && chart.dataset.chart !== 'score' && !rows.length && !chart.querySelector('.report-empty')
        && (chart.querySelector('.report-results tbody td[colspan]') || chart.querySelector('.report-stacks > p'))) {
      chart.querySelectorAll('.report-table-wrap, .report-stacks, .report-series-legend, [data-line-chart]').forEach(item => { item.hidden = true; });
      (chart.querySelector('.report-card-foot') || chart.lastElementChild).before(reportEmptyState(chart));
    }
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
    const legendColors = new Map([...chart.querySelectorAll('.report-series-legend span')].map((entry,i)=>[entry.textContent.trim(),REPORT_NEUTRAL_LABELS.has(entry.textContent.trim()) ? REPORT_OTHER_COLOR : reportSlotColor(i)]));
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
        const monthRows = [...chart.querySelectorAll('.report-results tr[data-point-value]')];
        const plot = reportStackPlot(chart, groups, monthRows, {interactiveSegments: layout === 'dealer_overview', colorOf: overviewColor, attach});
        const svg = plot.svg, columns = plot.columns;
        let brushStart = null, brushing = false, suppressClick = false;
        const points = [...svg.querySelectorAll('.report-month-target')];
        const clearBrush = () => points.forEach(point => point.classList.remove('report-brush-candidate'));
        const range = (a,b) => points.filter(point => { const r=point.getBoundingClientRect(); return columns ? r.right >= Math.min(a,b) && r.left <= Math.max(a,b) : r.bottom >= Math.min(a,b) && r.top <= Math.max(a,b); });
        const along = event => columns ? event.clientX : event.clientY;
        svg.addEventListener('pointerdown', event => {
          if (event.button !== 0 || event.pointerType === 'touch' || !event.target.closest('.report-month-target')) return;
          brushStart = along(event); brushing = false;
        });
        svg.addEventListener('pointermove', event => {
          if (brushStart === null || !event.buttons) return;
          if (Math.abs(along(event)-brushStart) > 5) {
            brushing = true; svg.setPointerCapture(event.pointerId); hideTip(); clearBrush();
            range(brushStart,along(event)).forEach(point => point.classList.add('report-brush-candidate'));
          }
        });
        svg.addEventListener('pointerup', event => {
          if (brushing) {
            suppressClick = true;
            chart.dispatchEvent(new CustomEvent('report-view-change',{bubbles:true,detail:{card:Number(chart.dataset.chartIndex),groups:range(brushStart,along(event)).map(point=>point.dataset.selectionGroup),additive:event.ctrlKey || event.metaKey}}));
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
        // T-182：甜甜圈固定比例、永遠完整；扇形之間留 2px 底色縫，中間放總數，占比移到下方圖例。
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", "0 0 300 300"); svg.classList.add("report-donut");
        svg.setAttribute("role", "group"); svg.setAttribute("aria-label", chart.querySelector("h2").textContent + " 圓環圖");
        const shown = rows.filter(row => reportFraction(row.dataset.pointValue, total) > 0);
        const ring = (color, fraction, offset, gap) => {
          const circle = document.createElementNS(ns, "circle");
          for (const [key, value] of Object.entries({cx:150,cy:150,r:104,fill:"none",stroke:color,"stroke-width":44,pathLength:100,"stroke-dasharray":`${Math.max(.01, fraction - gap)} ${100 - fraction + gap}`,"stroke-dashoffset":-offset,transform:"rotate(-90 150 150)"})) circle.setAttribute(key, String(value));
          svg.append(circle); return circle;
        };
        ring("var(--line-soft)", 100, 0, 0); let offset = 0;
        rows.forEach((row, index) => {
          const fraction = reportFraction(row.dataset.pointValue, total);
          if (!fraction) return;
          const color = row.dataset.pointColor || palette[index % palette.length];
          attach(ring(color, fraction, offset, shown.length > 1 ? .5 : 0), row);
          offset += fraction;
          const swatch = document.createElement("span"); swatch.className = "report-legend-dot"; swatch.style.background = color;
          row.querySelector("th").prepend(swatch);
        });
        const centre = (text, y, className) => { const item = document.createElementNS(ns, "text"); for (const [key, value] of Object.entries({x:150,y,"text-anchor":"middle",class:className})) item.setAttribute(key, String(value)); item.textContent = text; svg.append(item); };
        centre(chart.querySelector(".report-score strong")?.textContent.trim() || "", 160, "report-donut-total");
        centre(chart.dataset.metricLabel === "訂單台數" ? "張訂單" : chart.dataset.metricLabel || "", 188, "report-donut-caption");
        host.append(svg);
        if (offset < 99.99) { const note = document.createElement("p"); note.className = "report-muted"; note.textContent = "淡灰區域為未顯示群組；占比以完整篩選範圍計算。"; host.append(note); }
      } else host.replaceChildren(reportEmptyState(chart));
    }
    if (overview) {
      const table = chart.querySelector('.report-table-wrap');
      if (table && chart.dataset.chart === 'donut') {
        const legend = document.createElement('div'); legend.className = 'report-overview-legend';
        rows.forEach(row => {
          const link = row.querySelector('[data-report-drill]');
          if (!link) return;
          const entry = link.cloneNode(true), dot = document.createElement('i'); dot.style.background = row.dataset.pointColor;
          const name = document.createElement('span'); name.className = 'report-overview-legend__name'; name.append(...entry.childNodes);
          const value = document.createElement('span'); value.className = 'report-overview-legend__value'; value.textContent = row.dataset.pointDisplay;
          const share = document.createElement('span'); share.className = 'report-overview-legend__share'; share.textContent = `${Number(row.dataset.pointPercentage || 0).toFixed(1)}%`;
          entry.append(dot, name, value, share); legend.append(entry);
        });
        chart.querySelector('[data-line-chart]').after(legend);
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
  if (!panel) { reportAutoSubmitFilters(document.querySelector('.report-filter')); return; }
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
  function queueOverviewUpdate(url, message, wait) {
    ++updateSequence; updateController?.abort(); selectionQueue.cancel();
    desiredUrl = new URL(url, (window.reportPreviewLocation || location.href)); paintSelection();
    reader.setAttribute('aria-busy', 'true'); retry.hidden = true;
    updateStatus.textContent = message;
    selectionQueue.schedule(desiredUrl.href, wait);
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
      for (const selector of [".report-context", "[data-report-selection-tags]", "[data-report-active-filters]", "[data-report-kpis]"]) {
        const current = reader.querySelector(selector), incoming = next.querySelector(selector);
        if (current && incoming) current.replaceWith(document.importNode(incoming, true));
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
      // 篩選欄位已依伺服器結果同步；報表外的元件（大數據分析樹狀篩選，T-151）依此更新勾選與台數。
      document.dispatchEvent(new CustomEvent('report-filters-synced', {detail: {doc}}));
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
  // 所有報表的篩選都選了就自動套用（T-142）：條件寫回網址，圖表點選（focus）保留。
  const filterForm = reader.querySelector('.report-filter');
  filterForm?.addEventListener('change', event => {
    const wait = reportFilterDelay(event.target);
    if (syncingFilters || wait === null) return;
    const rangeError = reportDateRangeError(filterForm.elements.namedItem('start')?.value, filterForm.elements.namedItem('end')?.value);
    if (rangeError) { selectionQueue.cancel(); reader.removeAttribute('aria-busy'); updateStatus.textContent = rangeError; return; }
    const base = window.reportPreviewLocation || location.href;
    const target = new URL(new URL(base).pathname, base);
    // 空值等同不限，不寫進網址，分享出去的網址只留真正套用的條件。
    target.search = new URLSearchParams([...new FormData(filterForm)].filter(([, value]) => value !== '')).toString();
    const focus = desiredUrl.searchParams.get('focus');
    if (focus) target.searchParams.set('focus', focus); else target.searchParams.delete('focus');
    target.searchParams.delete('records_page');
    queueOverviewUpdate(target, event.target.closest('[data-report-multi]') ? '篩選已選取，可繼續選擇；圖表即將同步…' : '篩選已變更，圖表即將同步…', wait);
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
      if (matchMedia("(max-width:1100px)").matches) panel.scrollIntoView({block:"start", behavior:"smooth"});
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
