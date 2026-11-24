/* T-311 閱讀版型的圓餅（只用在 reader_layout 不是 standard 的報表；一般自訂報表的圓環照舊）。
   使用者決定：原本是圓餅的地方維持圓餅，只改三件事——
   1. 圖例每項一列：色塊 · 名稱 · 數值 · 占比；名稱不換行，放不下才用「…」，滑過顯示全名（修 #5 圖例一個字一行）。
   2. 扇區標整數百分比：≥ 7% 標在環上（白字或深字取對比高者），< 7% 標在環外加短引線；小數一位的占比寫在圖例。
   3. 超過 6 項時只畫前 5 名，其餘合併成灰色「其他」，圖例列出它包含哪些項目；原報表有上限而沒列出的部分也算進「其他」，
      各扇區加起來＝圖卡合計。資料本身就有「其他」分類時，合併項改叫「其餘 N 項」。
   只做顯示用的加總與占比，數字口徑不變；點扇區連動、中間總數照舊。 */
const REPORT_PIE_MAX = 6;
const REPORT_PIE_INSIDE = 7; // 扇區百分比 ≥ 7% 才標在環上
const REPORT_PIE_INK = [17, 21, 26];

function reportPieRank(items, total, {max = REPORT_PIE_MAX, fixed = []} = {}) {
  // 名次相同時依原報表順序（穩定排序）；fixed（例如女、男）固定排最前面，不隨台數換位。
  const rank = item => { const index = fixed.indexOf(item.label); return index < 0 ? fixed.length : index; };
  const ordered = items.map((item, position) => ({...item, position}))
    .sort((a, b) => rank(a) - rank(b) || b.value - a.value || a.position - b.position);
  let shown = ordered, merged = [];
  if (ordered.length > max) { shown = ordered.slice(0, max - 1); merged = ordered.slice(max - 1); }
  const listed = ordered.reduce((sum, item) => sum + item.value, 0);
  const hidden = Math.max(0, total - listed); // 原報表設了上限而沒列出、但算在合計的部分
  const otherValue = merged.reduce((sum, item) => sum + item.value, 0) + hidden;
  let other = null;
  if (otherValue > 0 && (merged.length || hidden > 0)) {
    const clash = ordered.some(item => item.label === '其他');
    const label = clash ? (merged.length ? `其餘 ${merged.length} 項` : '其餘未列出') : '其他';
    other = {label, value: otherValue, merged, hidden, other: true};
  }
  return {shown, other};
}

function reportPieColorKey(doc, color) {
  const probe = doc.createElement('span'); probe.style.color = color; probe.hidden = true;
  doc.body.append(probe); const value = getComputedStyle(probe).color; probe.remove();
  return value;
}
function reportPieLuminance(rgb) {
  const channel = value => { value /= 255; return value <= .03928 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4; };
  return .2126 * channel(rgb[0]) + .7152 * channel(rgb[1]) + .0722 * channel(rgb[2]);
}
function reportPieInk(doc, color) {
  const rgb = (reportPieColorKey(doc, color).match(/[\d.]+/g) || []).slice(0, 3).map(Number);
  if (rgb.length < 3) return 'var(--ink)';
  const contrast = (a, b) => (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
  const light = reportPieLuminance(rgb);
  return contrast(light, 1) >= contrast(light, reportPieLuminance(REPORT_PIE_INK)) ? '#fff' : '#11151a';
}
/* 同一張圓餅裡顏色不重複：調色盤只有 8 色，第 9 個分類起會撞色，撞到的改用還沒用過的 --chart-sN。 */
function reportPieDistinct(doc, items) {
  const used = new Set();
  const spare = Array.from({length: 8}, (_, index) => `var(--chart-s${index + 1})`);
  return items.map(item => {
    const key = reportPieColorKey(doc, item.color);
    if (!used.has(key)) { used.add(key); return item; }
    const free = spare.find(color => !used.has(reportPieColorKey(doc, color)));
    if (!free) return item;
    used.add(reportPieColorKey(doc, free));
    return {...item, color: free};
  });
}
function reportPiePercent(value, total) {
  const share = total > 0 ? value / total * 100 : 0;
  return share > 0 && share < .5 ? '<1%' : `${Math.round(share)}%`;
}

function renderReportPie(chart, rows, attach) {
  const doc = chart.ownerDocument, ns = 'http://www.w3.org/2000/svg';
  const host = chart.querySelector('[data-line-chart]');
  const total = Number(chart.dataset.total);
  const items = rows.map(row => ({row, label: row.dataset.pointLabel, value: Math.max(0, Number(row.dataset.pointValue) || 0),
    display: row.dataset.pointDisplay, color: row.dataset.pointColor || 'var(--chart-s1)'})).filter(item => item.value > 0);
  if (!(total > 0) || !items.length) { host.replaceChildren(reportEmptyState(chart)); return; }
  // T-311：性別圓餅（#9 #15）女左男右、順序固定（女在前），配色同蝴蝶圖。
  const ranked = reportPieRank(items, total, {fixed: chart.dataset.dimension === 'sex' ? ['女性', '男性'] : []});
  const slices = [...reportPieDistinct(doc, ranked.shown)];
  if (ranked.other) slices.push({...ranked.other, color: 'var(--chart-other)'});
  const svg = doc.createElementNS(ns, 'svg'); svg.classList.add('report-donut', 'report-pie__plot');
  svg.setAttribute('role', 'group'); svg.setAttribute('aria-label', `${chart.querySelector('h2').textContent} 圓餅圖`);
  const add = (tag, attrs, text) => {
    const node = doc.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== undefined) node.textContent = text;
    svg.append(node); return node;
  };
  const centre = 150, radius = 104, band = 44, outer = radius + band / 2;
  const point = (distance, angle) => [centre + distance * Math.cos(angle), centre + distance * Math.sin(angle)];
  add('circle', {cx: centre, cy: centre, r: radius, fill: 'none', stroke: 'var(--line-soft)', 'stroke-width': band});
  const labels = [];
  let offset = 0, outside = false;
  slices.forEach(slice => {
    const fraction = reportFraction(slice.value, total);
    if (!fraction) return;
    const gap = slices.length > 1 ? .5 : 0;
    const ring = add('circle', {cx: centre, cy: centre, r: radius, fill: 'none', stroke: slice.color, 'stroke-width': band, pathLength: 100,
      'stroke-dasharray': `${Math.max(.01, fraction - gap)} ${100 - fraction + gap}`, 'stroke-dashoffset': -offset, transform: `rotate(-90 ${centre} ${centre})`});
    if (slice.other) {
      ring.classList.add('report-pie__other');
      ring.setAttribute('role', 'img');
      ring.setAttribute('aria-label', `${slice.label}：${Number(slice.value).toLocaleString('zh-TW')}，占 ${(fraction).toFixed(1)}%`);
      const title = doc.createElementNS(ns, 'title'); title.textContent = ring.getAttribute('aria-label'); ring.append(title);
    } else attach(ring, slice.row);
    const angle = -Math.PI / 2 + (offset + fraction / 2) / 100 * 2 * Math.PI;
    if (fraction >= REPORT_PIE_INSIDE) {
      const [x, y] = point(radius, angle);
      labels.push(['text', {x: x.toFixed(1), y: (y + 5).toFixed(1), 'text-anchor': 'middle', class: 'report-pie__share', fill: reportPieInk(doc, slice.color), 'aria-hidden': 'true'}, reportPiePercent(slice.value, total)]);
    } else {
      outside = true;
      const [x0, y0] = point(outer + 3, angle), [x1, y1] = point(outer + 14, angle), right = Math.cos(angle) >= 0;
      labels.push(['path', {d: `M${x0.toFixed(1)} ${y0.toFixed(1)}L${x1.toFixed(1)} ${y1.toFixed(1)}`, class: 'report-pie__leader', 'aria-hidden': 'true'}]);
      labels.push(['text', {x: (x1 + (right ? 3 : -3)).toFixed(1), y: (y1 + 4).toFixed(1), 'text-anchor': right ? 'start' : 'end', class: 'report-pie__share report-pie__share--outside', 'aria-hidden': 'true'}, reportPiePercent(slice.value, total)]);
    }
    offset += fraction;
  });
  labels.forEach(([tag, attrs, text]) => { const node = add(tag, attrs, text); node.style.pointerEvents = 'none'; });
  add('text', {x: centre, y: centre + 10, 'text-anchor': 'middle', class: 'report-donut-total'}, chart.querySelector('.report-score strong')?.textContent.trim() || '');
  add('text', {x: centre, y: centre + 38, 'text-anchor': 'middle', class: 'report-donut-caption'}, chart.dataset.metricLabel === '訂單台數' ? '張訂單' : chart.dataset.metricLabel || '');
  svg.setAttribute('viewBox', outside ? '-38 -26 376 352' : '0 0 300 300');

  // 圖例：每項一列；連結沿用原本的下鑽連結，點選連動與選取樣式照舊。
  const legend = doc.createElement('div'); legend.className = 'report-overview-legend report-pie-legend';
  const entry = (tag, slice) => {
    const node = doc.createElement(tag), dot = doc.createElement('i'), name = doc.createElement('span');
    const value = doc.createElement('span'), share = doc.createElement('span');
    dot.style.background = slice.color; dot.setAttribute('aria-hidden', 'true');
    name.className = 'report-overview-legend__name'; name.textContent = slice.label; name.title = slice.label;
    value.className = 'report-overview-legend__value'; value.textContent = slice.display ?? Number(slice.value).toLocaleString('zh-TW');
    share.className = 'report-overview-legend__share'; share.textContent = `${reportFraction(slice.value, total).toFixed(1)}%`;
    node.append(dot, name, value, share); return node;
  };
  slices.forEach(slice => {
    if (slice.other) {
      const item = entry('div', slice); item.classList.add('report-pie-legend__other');
      const detail = doc.createElement('p'); detail.className = 'report-pie-legend__members';
      if (slice.merged.length) {
        detail.append('含 ');
        slice.merged.forEach((member, index) => {
          if (index) detail.append('、');
          const link = member.row.querySelector('[data-report-drill]');
          const text = `${member.label} ${member.display}`;
          if (link) { const copy = link.cloneNode(false); copy.textContent = text; detail.append(copy); } else detail.append(text);
        });
      }
      const unit = chart.dataset.metricLabel === '訂單台數' ? ' 張' : '';
      if (slice.hidden > 0) detail.append(`${slice.merged.length ? '；' : ''}原報表未列出的 ${Number(slice.hidden).toLocaleString('zh-TW')}${unit}`);
      item.append(detail); legend.append(item); return;
    }
    const link = slice.row.querySelector('[data-report-drill]');
    const item = entry(link ? 'a' : 'div', slice);
    if (link) { for (const attr of link.attributes) item.setAttribute(attr.name, attr.value); }
    item.title = `${slice.label}：${slice.display} · ${reportFraction(slice.value, total).toFixed(1)}%`;
    legend.append(item);
  });
  const inner = doc.createElement('div'); inner.className = 'report-pie__inner'; inner.append(svg, legend);
  host.classList.add('report-pie'); host.replaceChildren(inner);
}
if (typeof module !== 'undefined' && module.exports) module.exports = {reportPieRank, reportPiePercent};
