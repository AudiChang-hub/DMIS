const test = require('node:test');
const assert = require('node:assert/strict');
const {reportPointText, reportFraction} = require('../../static/js/report-interactions.js');
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
