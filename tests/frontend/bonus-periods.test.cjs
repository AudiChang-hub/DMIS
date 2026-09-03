const test = require('node:test');
const assert = require('node:assert/strict');
const {periodRange} = require('../../static/js/dealer-volume-bonus.js');

test('月份包含閏年與年底邊界', () => {
  assert.deepEqual(periodRange('month', 2024, 2), ['2024-02-01', '2024-02-29']);
  assert.deepEqual(periodRange('month', 2026, 2), ['2026-02-01', '2026-02-28']);
  assert.deepEqual(periodRange('month', 2100, 2), ['2100-02-01', '2100-02-28']);
  assert.deepEqual(periodRange('month', 9999, 12), ['9999-12-01', '9999-12-31']);
});
test('四季涵蓋完整國曆季度', () => {
  for (const [q, start, end] of [[1,'01-01','03-31'],[2,'04-01','06-30'],[3,'07-01','09-30'],[4,'10-01','12-31']]) {
    assert.deepEqual(periodRange('quarter', '2026', String(q)), [`2026-${start}`, `2026-${end}`]);
  }
});
test('無效年份與月份不產生猜測日期', () => {
  for (const args of [['quarter',2026,5],['month',2026,0],['month','',1],['month',2026.5,1],['month',10000,1],['custom',2026,1]]) {
    assert.equal(periodRange(...args), null);
  }
});
