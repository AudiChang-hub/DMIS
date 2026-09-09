const test = require('node:test');
const assert = require('node:assert/strict');
const {reportPointText, reportFraction, reportScopeCount, reportPageRange} = require('../../static/js/report-interactions.js');
const {reportToggleSelection} = require('../../static/js/report-interactions.js');
const {reportAxisMaximum} = require('../../static/js/report-interactions.js');
const {reportDebounce} = require('../../static/js/report-interactions.js');

test('連續複選只送最後完整條件，取消待送查詢不留下舊操作', () => {
  const jobs = new Map(); let id = 0; const received = [];
  const timers = {setTimeout(fn) { jobs.set(++id, fn); return id; }, clearTimeout(key) { jobs.delete(key); }};
  const queue = reportDebounce(value => received.push(value), 300, timers);
  let selected = [];
  for (const group of ['A', 'B', 'C']) {
    selected = reportToggleSelection(selected, 0, group, '', true);
    queue.schedule(selected);
  }
  assert.equal(jobs.size, 1);
  [...jobs.values()][0]();
  assert.deepEqual(received[0][0].group, ['A', 'B', 'C']);
  queue.schedule('過時條件'); queue.cancel();
  assert.equal(jobs.size, 0);
});

test('候選圖提示明確標示占比基準，不冒充套用所有篩選', () => {
  assert.match(reportPointText({pointLabel:'車行',pointDisplay:'20',pointCount:'20',pointPercentage:25,pointScope:'候選分類範圍'},'訂單台數'), /占候選分類範圍：25.0%/);
});

test('銷售座標軸涵蓋最大值，空資料與非數值安全且台數刻度為整數', () => {
  for (const values of [[], [0], [1,7], [NaN, 25], [255], [1,9999]]) {
    const maximum=reportAxisMaximum(values);
    assert.ok(Number.isFinite(maximum) && maximum > 0);
    assert.equal(maximum % 4, 0);
    assert.ok(maximum >= Math.max(0,...values.filter(Number.isFinite)));
  }
});

test('圖表單選、重點取消、複選聯集與移除保留其他圖條件', () => {
  const other = {card:1, group:'B', grain:''};
  let chosen = reportToggleSelection([other], 0, 'A', '', false);
  assert.deepEqual(reportToggleSelection(chosen, 0, 'A', '', false), [other]);
  chosen = reportToggleSelection(chosen, 0, 'C', '', true);
  assert.deepEqual(chosen[1].group, ['A','C']);
  assert.equal(reportToggleSelection(chosen, 0, 'A', '', true)[1].group, 'C');
  assert.equal(reportToggleSelection(chosen, 0, 'D', 'year', true)[1].group, 'D');
  assert.throws(() => reportToggleSelection([{card:0,group:Array.from({length:20},(_,i)=>String(i)),grain:''}],0,'extra','',true), /20/);
});

test('彙總分頁不遺漏尾頁，切換筆數及非法頁碼有界限', () => {
  assert.deepEqual(reportPageRange(51, 25, 3), {page:3, pages:3, start:50, end:51});
  assert.deepEqual(reportPageRange(51, 100, 3), {page:1, pages:1, start:0, end:51});
  assert.deepEqual(reportPageRange(0, 0, -1), {page:1, pages:1, start:0, end:0});
});

test('圖表固定條件數量包含文字條件並排除空行及重複值', () => {
  assert.equal(reportScopeCount(2, ['EV076\r\nEV070\r\nEV076', ' \n']), 4);
  assert.equal(reportScopeCount(0, ['', 'EV060L']), 1);
});
test('提示保留分類、指標、台數與完整範圍占比', () => {
  const text = reportPointText({pointLabel:'2026/09 · 車行', pointDisplay:'60,000', pointCount:'3', pointPercentage:'25.55'}, '訂單車價合計');
  assert.match(text, /2026\/09 · 車行/); assert.match(text, /訂單車價合計：60,000/);
  assert.match(text, /訂單台數：3/); assert.match(text, /25.6%/);
});
test('平均與試算不冒充占比；標籤保持純文字', () => {
  const text = reportPointText({pointLabel:'<script>測試</script>',pointDisplay:'無法計算',pointCount:'0',pointPercentage:''},'試算');
  assert.doesNotMatch(text, /%/); assert.match(text, /<script>測試<\/script>/);
});
test('圓環 Top N 不重新正規化為百分之百', () => {
  assert.equal(reportFraction('20','100'),20);
  assert.equal(reportFraction('30','100'),30);
  assert.equal(reportFraction('20','100') + reportFraction('30','100'),50);
});
test('空值、負值及零總數不產生 NaN 幾何', () => {
  for (const [value,total] of [[0,0],['x',10],[10,'x'],[-1,10],[10,Infinity]]) assert.equal(reportFraction(value,total),0);
  assert.equal(reportFraction(200,100),100);
});
