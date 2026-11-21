// T-274：堆疊圖細分是車色時，總覽版型與人口分析不可把引擎依車色名稱配的顏色蓋掉；其他圖型與高辨識配色照舊。全部為合成資料。
const test = require('node:test');
const assert = require('node:assert/strict');
const analysis = require('../../static/js/report-analysis.js');
const interactions = require('../../static/js/report-interactions.js');
const {reportChartOverviewColor, reportStackPlot} = interactions;
const {renderReportAnalysis} = analysis;

// 瀏覽器裡這些是全域函式；node 測試各檔獨立行程，設定不會影響其他測試檔。
globalThis.reportAnalysisColor = analysis.reportAnalysisColor;
globalThis.reportStackPlot = reportStackPlot;
globalThis.getComputedStyle = () => ({});

const CONTRAST = ['#0072b2','#d55e00','#009e73','#cc79a7','#e69f00','#56b4e9','#333333','#806400'];
const analysisOverview = {layout: 'analysis_overview'};

test('T-274 人口分析版型：堆疊圖細分是車色時，圖例與提示用引擎配的車色（藍、白不被固定配色表蓋掉）', () => {
  const car = {chart: 'stacked', series: 'color', palette: ''};
  // 重現：修正前「藍」會變成固定配色表的 var(--chart-s5)，「白」變成 var(--chart-s4)。
  assert.equal(reportChartOverviewColor(car, '藍', '#2f6fd6', analysisOverview), '#2f6fd6');
  assert.equal(reportChartOverviewColor(car, '白', '#f4f5f7', analysisOverview), '#f4f5f7');
  // 車行總覽版型的圖例依序配色，也不可蓋掉車色。
  const legendColors = new Map([['藍', 'var(--chart-s1)']]);
  assert.equal(reportChartOverviewColor(car, '藍', '#2f6fd6', {layout: 'dealer_overview', legendColors}), '#2f6fd6');
  // 細分不是車色的堆疊圖照舊用版型固定配色。
  assert.equal(reportChartOverviewColor({chart: 'stacked', series: 'sex', palette: ''}, '男性', '#123456', analysisOverview), 'var(--chart-s1)');
});

test('T-274 長條、圓餅、折線帶 data-series="color" 時顏色不變（沿用版型固定配色）', () => {
  for (const chart of ['bar', 'pie', 'line']) {
    const withSeries = {chart, series: 'color', palette: ''};
    const without = {chart, palette: ''};
    for (const [label, options] of [
      ['藍', analysisOverview],
      ['藍', {layout: 'dealer_overview', legendColors: new Map([['藍', 'var(--chart-s2)']])}],
      ['車行', {layout: 'sales_overview'}],
    ]) {
      const expected = reportChartOverviewColor(without, label, 'var(--chart-s7)', options);
      assert.equal(reportChartOverviewColor(withSeries, label, 'var(--chart-s7)', options), expected, `${chart} ${label}`);
      assert.notEqual(expected, 'var(--chart-s7)', `${chart} ${label} 應套用版型固定配色`);
    }
  }
});

test('T-274 選「高辨識對比色」時，車色系列照舊用高辨識色', () => {
  const car = {chart: 'stacked', series: 'color', palette: 'accessible'};
  for (const label of ['藍', '金', '白', '珍珠白']) {
    const color = reportChartOverviewColor(car, label, '#2f6fd6', analysisOverview);
    assert.ok(CONTRAST.includes(color), `${label} → ${color}`);
    assert.equal(color, reportChartOverviewColor({chart: 'stacked', palette: 'accessible'}, label, '#2f6fd6', analysisOverview));
  }
  // 人口分析的 SVG 分段：高辨識時車色系列不改變結果。
  assert.equal(analysis.reportAnalysisStackColor('藍', '#0072b2', '#2f6fd6', 'accessible', true, true),
    analysis.reportAnalysisStackColor('藍', '#0072b2', '#2f6fd6', 'accessible', true, false));
});

/* 精簡假 DOM：只支援 renderReportAnalysis／reportStackPlot 用到的選擇器（標籤、.class、[屬性]、子孫）。 */
class FakeElement {
  constructor(tag, {cls = '', data = {}, text = '', style = {}} = {}, children = []) {
    this.tagName = tag; this.attrs = cls ? {class: cls} : {}; this.dataset = {...data}; this.style = {...style};
    this.ownText = text; this.children = []; this.parent = null; this.hidden = false;
    this.classList = {add: (...names) => { this.attrs.class = [...new Set([...this.classNames(), ...names])].join(' '); },
      contains: name => this.classNames().includes(name)};
    this.append(...children);
  }
  classNames() { return (this.attrs.class || '').split(/\s+/).filter(Boolean); }
  append(...items) { items.forEach(item => { if (typeof item === 'string') this.ownText += item; else { item.parent = this; this.children.push(item); } }); }
  before(node) { const siblings = this.parent.children; node.parent = this.parent; siblings.splice(siblings.indexOf(this), 0, node); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return key in this.attrs ? this.attrs[key] : null; }
  get textContent() { return this.ownText + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  descendants() { return this.children.flatMap(child => [child, ...child.descendants()]); }
  matches(compound) {
    const [, tag] = /^([a-z0-9]*)/i.exec(compound);
    const classes = [...compound.matchAll(/\.([\w-]+)/g)].map(match => match[1]);
    const attrs = [...compound.matchAll(/\[([\w-]+)\]/g)].map(match => match[1]);
    const has = name => name.startsWith('data-')
      ? name.slice(5).replace(/-(\w)/g, (_, ch) => ch.toUpperCase()) in this.dataset : name in this.attrs;
    return (!tag || this.tagName.toLowerCase() === tag.toLowerCase()) && classes.every(name => this.classNames().includes(name)) && attrs.every(has);
  }
  querySelectorAll(selector) {
    const parts = selector.trim().split(/\s+/);
    return this.descendants().filter(node => {
      if (!node.matches(parts[parts.length - 1])) return false;
      let index = parts.length - 2;
      for (let up = node.parent; up && index >= 0 && up !== this.parent; up = up.parent) if (up.matches(parts[index])) index--;
      return index < 0;
    });
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  getBoundingClientRect() { return {width: 800, left: 0, top: 0, right: 800, bottom: 400}; }
}
const fakeDocument = {createElementNS: (ns, tag) => new FakeElement(tag), createElement: tag => new FakeElement(tag)};

function carChart(data, segments) {
  const el = (tag, options, children) => new FakeElement(tag, options, children);
  const total = segments.reduce((sum, item) => sum + item.value, 0);
  const chart = el('section', {cls: 'report-chart', data: {chart: 'stacked', dimension: 'age_group', palette: '', ...data}}, [
    el('h2', {text: '年齡層 × 車色'}),
    el('div', {cls: 'report-stacks'}, [el('div', {cls: 'report-stack-row'}, [
      el('div', {cls: 'report-stack-caption'}, [el('strong', {text: '20-29歲'})]),
      ...segments.map(item => el('span', {cls: 'report-stack-segment', style: {backgroundColor: item.rgb},
        data: {stackSegment: '', ...(item.outline ? {outline: ''} : {}), pointColor: item.color, seriesLabel: item.label,
          pointLabel: `20-29歲 · ${item.label}`, pointValue: String(item.value), pointDisplay: String(item.value)}})),
    ])]),
    el('div', {cls: 'report-table-wrap'}, [el('table', {cls: 'report-results'}, [
      el('tr', {data: {pointValue: String(total), pointLabel: '20-29歲', pointDisplay: String(total)}}),
    ])]),
  ]);
  chart.ownerDocument = fakeDocument;
  return chart;
}
const SEGMENTS = [
  {label: '白', color: '#f4f5f7', rgb: 'rgb(244, 245, 247)', value: 3, outline: true},
  {label: '藍', color: '#2f6fd6', rgb: 'rgb(47, 111, 214)', value: 2},
  {label: '紅', color: '#d6312b', rgb: 'rgb(214, 49, 43)', value: 1},
];
const plotSegments = chart => {
  const svg = chart.querySelector('svg');
  assert.ok(svg, '應畫出 SVG 堆疊圖');
  return svg.querySelectorAll('.report-plot-segment');
};

test('T-274 人口分析 SVG：車色系列的白色分段加邊框，其他分段不加，顏色用引擎色碼', () => {
  const chart = carChart({series: 'color'}, SEGMENTS);
  renderReportAnalysis(chart, () => {});
  const rects = plotSegments(chart);
  assert.deepEqual(rects.map(rect => rect.getAttribute('fill')), ['#f4f5f7', '#2f6fd6', '#d6312b']);
  assert.deepEqual(rects.map(rect => rect.classList.contains('report-plot-segment--outline')), [true, false, false]);
});

test('T-274 人口分析 SVG：細分不是車色時不加邊框、照舊用固定配色', () => {
  const chart = carChart({series: 'sex'}, SEGMENTS.map(({outline, ...item}) => item));
  renderReportAnalysis(chart, () => {});
  const rects = plotSegments(chart);
  assert.deepEqual(rects.map(rect => rect.getAttribute('fill')), ['var(--chart-s4)', 'var(--chart-s5)', 'rgb(214, 49, 43)']);
  assert.ok(rects.every(rect => !rect.classList.contains('report-plot-segment--outline')));
});
