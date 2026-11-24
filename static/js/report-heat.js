/* T-311 車行／平台銷售（#6 #8 #11 #12，dealer_overview／platform_overview）：排行＋每月熱度格。
   每列一家車行（平台）：台數橫條與占比，右邊每格是當月台數（越深越多、格內寫數字），最下面一列是每月合計。
   資料全部讀自頁面上原本的堆疊圖（同一份查詢結果），只做重排與加總，數字口徑不變。
   使用者決定（2026-11-24）：點車行名稱可下鑽（沿用原本的連結與連動），格子只顯示數字，不改 report_detail 的 group。 */
const REPORT_HEAT_LEVELS = 5;

function reportHeatLevel(value, maximum) {
  if (!(value > 0) || !(maximum > 0)) return 0;
  return Math.max(1, Math.min(REPORT_HEAT_LEVELS, Math.ceil(value / maximum * REPORT_HEAT_LEVELS)));
}
function reportHeatMonths(labels) {
  // 補齊成連續月份，沒有訂單的月份也留一格（空格）。
  const months = [...new Set(labels)].filter(label => /^\d{4}\/\d{2}$/.test(label)).sort();
  if (!months.length) return [];
  const all = [];
  let [year, month] = months[0].split('/').map(Number);
  const [endYear, endMonth] = months[months.length - 1].split('/').map(Number);
  while (year < endYear || (year === endYear && month <= endMonth)) {
    all.push(`${year}/${String(month).padStart(2, '0')}`);
    month += 1; if (month > 12) { month = 1; year += 1; }
  }
  return all;
}
/* 從原本的堆疊圖 DOM 整理成「列＝車行／平台、欄＝月份」。 */
function reportHeatData(chart) {
  const caption = group => group.querySelector('.report-stack-caption strong').textContent.trim();
  const groups = [...chart.querySelectorAll('.report-stack-row')];
  const rows = [...chart.querySelectorAll('.report-results tr[data-point-value]')];
  const isMonth = label => /^\d{4}\/\d{2}$/.test(label);
  const segments = group => [...group.querySelectorAll('[data-stack-segment]')].map(segment => ({
    label: segment.dataset.seriesLabel, value: Number(segment.dataset.pointValue) || 0}));
  const entities = []; const labels = []; let undated = 0; let other = null;
  if (chart.dataset.dimension !== 'month') {
    // 車行版：每列是車行、細分是月份。
    groups.forEach((group, index) => {
      const cells = {}; let shown = 0;
      segments(group).forEach(segment => {
        if (isMonth(segment.label)) { cells[segment.label] = (cells[segment.label] || 0) + segment.value; labels.push(segment.label); }
        else undated += segment.value;
        shown += segment.value;
      });
      const row = rows[index];
      entities.push({label: caption(group), total: Number(row?.dataset.pointValue) || shown, cells, row});
    });
  } else {
    // 平台版：每列是月份、細分是平台；原報表只列前 N 個平台，其餘算進「其他平台」。
    const byName = new Map(); const rest = {}; let restTotal = 0;
    groups.forEach((group, index) => {
      const month = caption(group), monthTotal = Number(rows[index]?.dataset.pointValue) || 0;
      let shown = 0;
      segments(group).forEach(segment => {
        shown += segment.value;
        if (!isMonth(month)) { undated += segment.value; }
        const entity = byName.get(segment.label) || {label: segment.label, total: 0, cells: {}, row: null};
        entity.total += segment.value;
        if (isMonth(month)) entity.cells[month] = (entity.cells[month] || 0) + segment.value;
        byName.set(segment.label, entity);
      });
      if (isMonth(month)) labels.push(month);
      const missing = Math.max(0, monthTotal - shown);
      if (missing) { restTotal += missing; if (isMonth(month)) rest[month] = (rest[month] || 0) + missing; else undated += missing; }
    });
    entities.push(...[...byName.values()].sort((a, b) => b.total - a.total));
    if (restTotal > 0) other = {label: '其他平台', total: restTotal, cells: rest, row: null, other: true};
  }
  return {entities, other, months: reportHeatMonths(labels), undated, total: Number(chart.dataset.total) || 0};
}

function renderReportHeat(chart, {currentMonth = ''} = {}) {
  const doc = chart.ownerDocument;
  if (chart.dataset.dimension !== 'month' && chart.dataset.series !== 'month') return false;
  const data = reportHeatData(chart);
  if (!data.entities.length) return false;
  const dealer = chart.dataset.dimension !== 'month';
  const unit = chart.dataset.metricLabel === '訂單台數' ? ' 張' : '';
  const all = data.other ? [...data.entities, data.other] : data.entities;
  const maxCell = Math.max(REPORT_HEAT_LEVELS, ...all.flatMap(entity => data.months.map(month => entity.cells[month] || 0)));
  const maxTotal = Math.max(...all.map(entity => entity.total), 1);
  const share = value => `${data.total > 0 ? (value / data.total * 100).toFixed(1) : '0.0'}%`;
  const make = (tag, className, text) => { const node = doc.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };

  const box = make('div', 'report-heat');
  box.style.setProperty('--report-heat-months', String(data.months.length));
  box.setAttribute('role', 'table');
  box.setAttribute('aria-label', `${chart.querySelector('h2').textContent}：每列一${dealer ? '家車行' : '個平台'}，每欄一個月的台數`);
  const head = make('div', 'report-heat__row report-heat__head'); head.setAttribute('role', 'row');
  const nameHead = make('span', 'report-heat__name', dealer ? '車行' : '平台'); nameHead.setAttribute('role', 'columnheader');
  const totalHead = make('span', 'report-heat__total', '台數 · 占比'); totalHead.setAttribute('role', 'columnheader');
  const monthHead = make('span', 'report-heat__months');
  let lastYear = '';
  data.months.forEach(month => {
    const [year, number] = month.split('/');
    const cell = make('span', 'report-heat__month'); cell.setAttribute('role', 'columnheader');
    const partial = month === currentMonth;
    const label = make('b', '', String(Number(number))); label.append(make('i', '', '月')); cell.append(label);
    if (partial) { cell.classList.add('is-partial'); cell.append(make('em', '', '進行中')); }
    cell.append(make('small', '', year !== lastYear ? year : ''));
    cell.setAttribute('aria-label', `${year}年${Number(number)}月${partial ? '（進行中）' : ''}`);
    lastYear = year; monthHead.append(cell);
  });
  head.append(nameHead, totalHead, monthHead); box.append(head);

  const line = entity => {
    const row = make('div', `report-heat__row${entity.other ? ' is-other' : ''}`); row.setAttribute('role', 'row');
    const link = entity.row?.querySelector('[data-report-drill]');
    const name = make(link ? 'a' : 'span', 'report-heat__name', entity.label);
    if (link) { for (const attr of link.attributes) name.setAttribute(attr.name, attr.value); name.textContent = entity.label; }
    name.title = entity.label; name.setAttribute('role', 'rowheader');
    const total = make('span', 'report-heat__total'); total.setAttribute('role', 'cell');
    const bar = make('span', 'report-heat__bar'); bar.setAttribute('aria-hidden', 'true');
    const fill = make('b'); fill.style.width = `${(entity.total / maxTotal * 100).toFixed(2)}%`; bar.append(fill);
    const number = make('strong', '', entity.total.toLocaleString('zh-TW')); number.append(make('small', '', share(entity.total)));
    total.append(bar, number);
    const months = make('span', 'report-heat__months');
    data.months.forEach(month => {
      const value = entity.cells[month] || 0;
      const cell = make('span', `report-heat__cell h${reportHeatLevel(value, maxCell)}`, value ? value.toLocaleString('zh-TW') : '');
      cell.setAttribute('role', 'cell'); cell.title = `${entity.label} · ${month}：${value.toLocaleString('zh-TW')}${unit}`;
      cell.setAttribute('aria-label', cell.title);
      if (month === currentMonth) cell.classList.add('is-partial');
      months.append(cell);
    });
    row.append(name, total, months); return row;
  };
  all.forEach(entity => box.append(line(entity)));

  const foot = make('div', 'report-heat__row report-heat__foot'); foot.setAttribute('role', 'row');
  const footName = make('span', 'report-heat__name', '每月合計'); footName.setAttribute('role', 'rowheader');
  const footTotal = make('span', 'report-heat__total'); footTotal.setAttribute('role', 'cell');
  footTotal.append(make('strong', '', data.total.toLocaleString('zh-TW')));
  const footMonths = make('span', 'report-heat__months');
  data.months.forEach(month => {
    const value = all.reduce((sum, entity) => sum + (entity.cells[month] || 0), 0);
    const cell = make('span', 'report-heat__sum', value.toLocaleString('zh-TW')); cell.setAttribute('role', 'cell'); footMonths.append(cell);
  });
  foot.append(footName, footTotal, footMonths); box.append(foot);

  const scale = make('p', 'report-heat__scale');
  scale.append('格子越深＝當月台數越多');
  for (let level = 0; level <= REPORT_HEAT_LEVELS; level += 1) {
    const swatch = make('i', `h${level}`); swatch.setAttribute('aria-hidden', 'true'); scale.append(swatch);
    if (level === 0) scale.append('0');
  }
  scale.append(`${maxCell.toLocaleString('zh-TW')} 以上`);

  const notes = [];
  const current = data.months.includes(currentMonth) ? Number(currentMonth.split('/')[1]) : 0;
  if (data.months.length) notes.push(`${data.months[0]}–${data.months[data.months.length - 1]}`);
  if (current) notes.push(`${current}月統計到今天，尚未滿月（框線格）`);
  if (data.other) notes.push(`「其他平台」是原報表只列前 ${data.entities.length} 名以外的平台，共 ${data.other.total.toLocaleString('zh-TW')}${unit}，合計本來就有算進去`);
  if (data.undated > 0) notes.push(`另有 ${data.undated.toLocaleString('zh-TW')}${unit}日期未填寫，不在每月格子裡，仍算在台數`);

  const wrap = make('div', 'report-heat-wrap');
  const scroll = make('div', 'report-heat-scroll'); scroll.append(box);
  wrap.append(scroll, scale);
  if (notes.length) wrap.append(make('p', 'report-heat__note', `${notes.join('；')}。`));
  const stacks = chart.querySelector('.report-stacks');
  stacks.before(wrap); stacks.hidden = true;
  // 原本「只顯示前 N 個系列、背景空白為未顯示部分」的說明是給堆疊圖的；熱度格已把未列出的併成「其他平台」並另寫註記。
  chart.querySelectorAll(':scope > .report-notice').forEach(note => { if (note.textContent.includes('依系列排序顯示前')) note.hidden = true; });
  chart.querySelector('.report-series-legend')?.setAttribute('hidden', '');
  const table = chart.querySelector('.report-table-wrap'); if (table) table.hidden = true;
  chart.classList.add('report-chart--heat');
  return true;
}
if (typeof module !== 'undefined' && module.exports) module.exports = {reportHeatLevel, reportHeatMonths};
