/* T-311 人口分析（analysis_overview）各圖依資料形狀換呈現；資料全部讀自頁面上原本的圖卡結果，只做重排與占比，口徑不變。
   - 細分是性別的堆疊（#15 年齡 × 性別、#16 車色 × 性別）→ 蝴蝶圖：女性往左、男性往右，都從中線起算；女左男右固定。
   - 車型顏色 × 年齡層（#17，family_color × age_group）→ 熱度矩陣：依車型分組、組內由多到少，格子單色藍階。
   - 車色長條（#10）→ 長條一律同一個藍色比長短，旁邊加實車顏色圓點（data-car-paint），數字附占該車型比例。
   回傳 true 表示已處理，否則由 report-analysis.js 照原本方式畫。 */
const REPORT_SEX_ORDER = ['女性', '男性'];

function reportAnalysisMake(doc, tag, className, text) {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function reportAnalysisHideOriginal(chart) {
  chart.querySelectorAll('.report-stacks, .report-table-wrap').forEach(node => { node.hidden = true; });
  chart.querySelector('.report-series-legend')?.setAttribute('hidden', '');
}

/* 蝴蝶圖 */
function renderReportButterfly(chart, attach) {
  const doc = chart.ownerDocument;
  const groups = [...chart.querySelectorAll('.report-stack-row')];
  const rows = [...chart.querySelectorAll('.report-results tr[data-point-value]')];
  if (!groups.length) return false;
  const unit = chart.dataset.metricLabel === '訂單台數' ? ' 張' : '';
  const data = groups.map((group, index) => {
    const segments = [...group.querySelectorAll('[data-stack-segment]')];
    const pick = label => segments.find(segment => segment.dataset.seriesLabel === label);
    const value = segment => Number(segment?.dataset.pointValue) || 0;
    const others = segments.filter(segment => !REPORT_SEX_ORDER.includes(segment.dataset.seriesLabel) && value(segment) > 0);
    return {label: group.querySelector('.report-stack-caption strong').textContent.trim(), row: rows[index],
      female: pick('女性'), male: pick('男性'), femaleValue: value(pick('女性')), maleValue: value(pick('男性')),
      others: others.map(segment => ({label: segment.dataset.seriesLabel, value: value(segment)})),
      total: Number(rows[index]?.dataset.pointValue) || segments.reduce((sum, segment) => sum + value(segment), 0)};
  });
  const maximum = Math.max(1, ...data.flatMap(item => [item.femaleValue, item.maleValue]));
  const share = (value, total) => (total > 0 ? `${(value / total * 100).toFixed(1)}%` : '');
  const box = reportAnalysisMake(doc, 'div', 'report-butterfly');
  box.setAttribute('role', 'table');
  box.setAttribute('aria-label', `${chart.querySelector('h2').textContent}：女性在左、男性在右，占比為該列合計的比例`);
  const head = reportAnalysisMake(doc, 'div', 'report-butterfly__row report-butterfly__head'); head.setAttribute('role', 'row');
  const legend = (label, side) => {
    const cell = reportAnalysisMake(doc, 'span', `report-butterfly__${side}`); cell.setAttribute('role', 'columnheader');
    const dot = reportAnalysisMake(doc, 'i'); dot.style.background = reportAnalysisColor(label, 'var(--chart-s1)'); dot.setAttribute('aria-hidden', 'true');
    cell.append(dot, label); return cell;
  };
  const middleHead = reportAnalysisMake(doc, 'span', 'report-butterfly__mid', chart.querySelector('.report-card-toolbar small')?.textContent.split('·')[0].split('（')[0].trim() || '分類');
  middleHead.setAttribute('role', 'columnheader');
  head.append(legend('女性', 'left'), middleHead, legend('男性', 'right'));
  box.append(head);
  data.forEach(item => {
    const line = reportAnalysisMake(doc, 'div', 'report-butterfly__row'); line.setAttribute('role', 'row');
    const side = (segment, value, label, position) => {
      const cell = reportAnalysisMake(doc, 'span', `report-butterfly__${position}`); cell.setAttribute('role', 'cell');
      const track = reportAnalysisMake(doc, 'span', 'report-butterfly__track');
      const bar = reportAnalysisMake(doc, 'span', 'report-butterfly__bar');
      bar.style.setProperty('--r', (value / maximum).toFixed(4));
      bar.style.background = reportAnalysisColor(label, 'var(--chart-s1)');
      const number = reportAnalysisMake(doc, 'span', 'report-butterfly__value');
      number.append(reportAnalysisMake(doc, 'strong', '', value.toLocaleString('zh-TW')), reportAnalysisMake(doc, 'small', '', share(value, item.total)));
      track.append(bar, number); // 數字緊貼長條尾端；左側用 row-reverse，長條從中線往左長
      cell.append(track);
      if (segment && value > 0) attach(cell, segment); else cell.setAttribute('aria-label', `${item.label} ${label}：0`);
      return cell;
    };
    const middle = reportAnalysisMake(doc, 'span', 'report-butterfly__mid'); middle.setAttribute('role', 'rowheader');
    middle.append(reportAnalysisMake(doc, 'strong', '', item.label));
    const extra = item.others.map(other => `${other.label} ${other.value.toLocaleString('zh-TW')}`).join('、');
    middle.append(reportAnalysisMake(doc, 'small', '', `${item.total.toLocaleString('zh-TW')}${unit}${extra ? ` · 另 ${extra}` : ''}`));
    middle.title = item.label;
    if (item.row) attach(middle, item.row);
    line.append(side(item.female, item.femaleValue, '女性', 'left'), middle, side(item.male, item.maleValue, '男性', 'right'));
    box.append(line);
  });
  const wrap = reportAnalysisMake(doc, 'div', 'report-butterfly-wrap'); wrap.append(box);
  chart.querySelector('.report-stacks').before(wrap);
  reportAnalysisHideOriginal(chart);
  chart.classList.add('report-chart--butterfly');
  return true;
}

/* 熱度矩陣：family_color（鍵是「品牌␟車型␟車色」，由後端提供，不拆顯示文字）× 年齡層 */
function renderReportHeatMatrix(chart, attach) {
  const doc = chart.ownerDocument;
  const groups = [...chart.querySelectorAll('.report-stack-row')];
  const rows = [...chart.querySelectorAll('.report-results tr[data-point-value]')];
  if (!groups.length) return false;
  const columns = [...chart.querySelectorAll('.report-series-legend > span')].map(entry => entry.textContent.trim());
  if (!columns.length) return false;
  const families = new Map();
  groups.forEach((group, index) => {
    const row = rows[index];
    const link = row?.querySelector('[data-report-drill]');
    const key = link ? new URL(link.href, location.href).searchParams.get('group') || '' : '';
    const parts = key.startsWith('v:') ? key.slice(2).split('␟') : [];
    const label = group.querySelector('.report-stack-caption strong').textContent.trim();
    const familyKey = parts.length === 3 ? `${parts[0]}␟${parts[1]}` : '未填車型';
    const familyName = label.includes(' · ') ? label.slice(0, label.lastIndexOf(' · ')) : (parts[1] || '未填車型');
    const color = label.includes(' · ') ? label.slice(label.lastIndexOf(' · ') + 3) : label;
    const cells = {};
    group.querySelectorAll('[data-stack-segment]').forEach(segment => { cells[segment.dataset.seriesLabel] = {value: Number(segment.dataset.pointValue) || 0, segment}; });
    const entry = families.get(familyKey) || {name: familyName, total: 0, items: []};
    const total = Number(row?.dataset.pointValue) || 0;
    entry.items.push({color, label, total, cells, row}); entry.total += total;
    families.set(familyKey, entry);
  });
  const all = [...families.values()];
  all.forEach(family => family.items.sort((a, b) => b.total - a.total));
  const maxCell = Math.max(REPORT_HEAT_LEVELS || 5, ...all.flatMap(family => family.items.flatMap(item => columns.map(column => item.cells[column]?.value || 0))));
  const box = reportAnalysisMake(doc, 'div', 'report-matrix');
  box.style.setProperty('--report-matrix-columns', String(columns.length));
  box.setAttribute('role', 'table');
  box.setAttribute('aria-label', `${chart.querySelector('h2').textContent}：每列一個車型顏色，每欄一個年齡層`);
  const head = reportAnalysisMake(doc, 'div', 'report-matrix__row report-matrix__head'); head.setAttribute('role', 'row');
  const first = reportAnalysisMake(doc, 'span', 'report-matrix__name', '車型 · 顏色'); first.setAttribute('role', 'columnheader');
  head.append(first);
  columns.forEach(column => { const cell = reportAnalysisMake(doc, 'span', 'report-matrix__col', column.replace('歲', '')); cell.title = column; cell.setAttribute('role', 'columnheader'); cell.setAttribute('aria-label', column); head.append(cell); });
  const totalHead = reportAnalysisMake(doc, 'span', 'report-matrix__total', '合計'); totalHead.setAttribute('role', 'columnheader'); head.append(totalHead);
  box.append(head);
  all.forEach(family => {
    const title = reportAnalysisMake(doc, 'div', 'report-matrix__group'); title.setAttribute('role', 'row');
    const titleCell = reportAnalysisMake(doc, 'span', '', family.name); titleCell.setAttribute('role', 'rowheader');
    const titleTotal = reportAnalysisMake(doc, 'span', '', `${family.total.toLocaleString('zh-TW')} 張`); titleTotal.setAttribute('role', 'cell');
    title.append(titleCell, titleTotal); box.append(title);
    family.items.forEach(item => {
      const line = reportAnalysisMake(doc, 'div', 'report-matrix__row'); line.setAttribute('role', 'row');
      const name = reportAnalysisMake(doc, 'span', 'report-matrix__name', item.color); name.title = item.label; name.setAttribute('role', 'rowheader');
      if (item.row) attach(name, item.row);
      line.append(name);
      columns.forEach(column => {
        const value = item.cells[column]?.value || 0;
        const cell = reportAnalysisMake(doc, 'span', `report-heat__cell h${reportHeatLevel(value, maxCell)}`, value ? value.toLocaleString('zh-TW') : '');
        cell.setAttribute('role', 'cell');
        if (value && item.cells[column]?.segment) attach(cell, item.cells[column].segment);
        else cell.setAttribute('aria-label', `${item.label} ${column}：0`);
        line.append(cell);
      });
      const total = reportAnalysisMake(doc, 'strong', 'report-matrix__total', item.total.toLocaleString('zh-TW')); total.setAttribute('role', 'cell');
      line.append(total); box.append(line);
    });
  });
  const foot = reportAnalysisMake(doc, 'div', 'report-matrix__row report-matrix__foot'); foot.setAttribute('role', 'row');
  const footName = reportAnalysisMake(doc, 'span', 'report-matrix__name', '各年齡層合計'); footName.setAttribute('role', 'rowheader'); foot.append(footName);
  let grand = 0;
  columns.forEach(column => {
    const value = all.reduce((sum, family) => sum + family.items.reduce((inner, item) => inner + (item.cells[column]?.value || 0), 0), 0);
    grand += value;
    const cell = reportAnalysisMake(doc, 'span', 'report-matrix__sum', value.toLocaleString('zh-TW')); cell.setAttribute('role', 'cell'); foot.append(cell);
  });
  const footTotal = reportAnalysisMake(doc, 'strong', 'report-matrix__total', (Number(chart.dataset.total) || grand).toLocaleString('zh-TW')); footTotal.setAttribute('role', 'cell'); foot.append(footTotal);
  box.append(foot);
  const scale = reportAnalysisMake(doc, 'p', 'report-heat__scale');
  scale.append('格子越深＝人數越多');
  for (let level = 0; level <= 5; level += 1) { const swatch = reportAnalysisMake(doc, 'i', `h${level}`); swatch.setAttribute('aria-hidden', 'true'); scale.append(swatch); if (level === 0) scale.append('0'); }
  scale.append(`${maxCell.toLocaleString('zh-TW')} 以上`);
  const wrap = reportAnalysisMake(doc, 'div', 'report-heat-wrap report-matrix-wrap');
  const scroll = reportAnalysisMake(doc, 'div', 'report-heat-scroll'); scroll.append(box);
  wrap.append(scroll, scale);
  chart.querySelector('.report-stacks').before(wrap);
  reportAnalysisHideOriginal(chart);
  return true;
}

/* #10：車色長條改單色＋實車顏色圓點＋占比。在 report-analysis.js 畫完之後補上。 */
function reportEnhanceColorBars(chart) {
  const rows = [...chart.querySelectorAll('.report-results tr[data-point-value]')];
  const svg = chart.querySelector('svg.report-analysis-plot');
  if (!svg || !rows.length) return;
  const ns = 'http://www.w3.org/2000/svg', total = Number(chart.dataset.total) || 0;
  if (chart.dataset.palette !== 'accessible') svg.querySelectorAll('.report-plot-segment').forEach(rect => rect.setAttribute('fill', 'var(--chart-s1)'));
  const labels = [...svg.querySelectorAll('.report-plot-label')], values = [...svg.querySelectorAll('.report-plot-value')];
  rows.forEach((row, index) => {
    const value = values[index];
    if (value && total > 0) value.textContent = `${row.dataset.pointDisplay} · ${(Number(row.dataset.pointValue) / total * 100).toFixed(0)}%`;
    const label = labels[index], paint = row.dataset.carPaint;
    if (!label || !paint) return;
    const box = label.getBBox();
    const dot = doc_create(ns, svg, 'circle', {cx: box.x - 8, cy: box.y + box.height / 2, r: 5, fill: paint, class: row.hasAttribute('data-car-paint-outline') ? 'report-paint-dot report-paint-dot--outline' : 'report-paint-dot', 'aria-hidden': 'true'});
    label.before(dot);
  });
  function doc_create(namespace, parent, tag, attrs) {
    const node = parent.ownerDocument.createElementNS(namespace, tag);
    Object.entries(attrs).forEach(([key, val]) => node.setAttribute(key, String(val)));
    return node;
  }
  chart.classList.add('report-chart--paint');
}

function renderReportAnalysisView(chart, attach) {
  if (chart.dataset.chart === 'stacked' && chart.dataset.series === 'sex') return renderReportButterfly(chart, attach);
  if (chart.dataset.chart === 'stacked' && chart.dataset.dimension === 'family_color' && chart.dataset.series === 'age_group'
      && typeof reportHeatLevel === 'function') return renderReportHeatMatrix(chart, attach);
  return false;
}
