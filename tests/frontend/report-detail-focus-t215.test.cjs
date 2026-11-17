// T-215：報表中心「查看來源訂單」明細面板關閉後，鍵盤焦點回到原本按的連結。
const test = require('node:test');
const assert = require('node:assert/strict');
const {reportDetailTrigger, reportDetailReturnTarget} = require('../../static/js/report-interactions.js');

function node({card = null, attrs = [], connected = true, matchesSelf = []} = {}) {
  const el = {isConnected: connected, attrs: new Set(attrs), matchesSelf,
    matches(selector) { return selector.split(',').some(part => this.matchesSelf.includes(part.trim())); },
    closest(selector) { return selector === '[data-chart-index]' && card !== null ? {dataset: {chartIndex: String(card)}} : null; }};
  return el;
}
function root(found = {}) {
  return {queried: [], querySelector(selector) { this.queried.push(selector); return found[selector] || null; }};
}
const panel = (inside = []) => ({contains: el => inside.includes(el)});

test('從面板外打開：記下觸發元素與所在卡片', () => {
  const link = node({card: 2, matchesSelf: ['a[data-report-open-detail]']});
  const trigger = reportDetailTrigger(link, panel(), null);
  assert.equal(trigger.element, link);
  assert.equal(trigger.card, '2');
  assert.equal(trigger.selector, 'a[data-report-open-detail]');
});

test('面板內換頁、跳頁不覆蓋原本的觸發元素', () => {
  const link = node({card: 0, matchesSelf: ['a[data-report-open-detail]']});
  const first = reportDetailTrigger(link, panel(), null);
  const pager = node();
  assert.equal(reportDetailTrigger(pager, panel([pager]), first), first);
  assert.equal(reportDetailTrigger(null, panel(), first), first);
});

test('關閉時觸發元素還在：焦點回到它', () => {
  const link = node({card: 1, matchesSelf: ['a[data-report-open-detail]']});
  const doc = root();
  assert.equal(reportDetailReturnTarget(reportDetailTrigger(link, panel(), null), doc), link);
  assert.deepEqual(doc.queried, []);
});

test('觸發元素被報表重新整理換掉：回到同一張卡片的同一個連結', () => {
  const link = node({card: 3, matchesSelf: ['a[data-report-open-detail]']});
  const trigger = reportDetailTrigger(link, panel(), null);
  link.isConnected = false;
  const replacement = node();
  assert.equal(reportDetailReturnTarget(trigger, root({'[data-chart-index="3"] a[data-report-open-detail]': replacement})), replacement);
});

test('找不到觸發元素：退回圖表上被選的那一列，再退回面板所在區塊', () => {
  const drill = node({card: 0, matchesSelf: ['a[data-report-drill]'], connected: false});
  const trigger = reportDetailTrigger(drill, panel(), null);
  assert.equal(trigger.selector, null, '圖表分類連結不用卡片內第一個連結冒充');
  const row = node();
  assert.equal(reportDetailReturnTarget(trigger, root({'.report-row-selected a': row})), row);
  const exploration = node();
  assert.equal(reportDetailReturnTarget(trigger, root({'[data-report-exploration]': exploration})), exploration);
  assert.equal(reportDetailReturnTarget(null, root({'[data-report-exploration]': exploration})), exploration);
});
