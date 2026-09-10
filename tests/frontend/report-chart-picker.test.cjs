const test = require('node:test');
const assert = require('node:assert/strict');
const {reportChartExamples, reportChartNextIndex, reportChartChoose} = require('../../static/js/report-chart-picker.js');

test('六種圖表皆有內建縮圖與用途說明，不載入外部資源', () => {
  assert.deepEqual(Object.keys(reportChartExamples), ['bar','line','donut','table','score','stacked']);
  for (const example of Object.values(reportChartExamples)) {
    assert.ok(example.help.length > 10);
    assert.match(example.art, /<(path|g|rect)/);
    assert.doesNotMatch(example.art, /script|https?:|href|onload/);
  }
});
test('雙欄鍵盤移動保持界限且不切換表單值', () => {
  assert.equal(reportChartNextIndex(0, 'ArrowLeft', 6), 0);
  assert.equal(reportChartNextIndex(0, 'ArrowDown', 6), 2);
  assert.equal(reportChartNextIndex(3, 'ArrowUp', 6), 1);
  assert.equal(reportChartNextIndex(5, 'ArrowRight', 6), 5);
  assert.equal(reportChartNextIndex(3, 'Home', 6), 0);
  assert.equal(reportChartNextIndex(2, 'End', 6), 5);
  assert.equal(reportChartNextIndex(2, 'Escape', 6), 2);
});
test('每次有效選取只派送一次 change，重選、非法與停用項目不更動', () => {
  const events = [];
  const select = {value:'bar', options:[{value:'bar'}, {value:'line'}, {value:'score', disabled:true}], dispatchEvent:event => events.push(event)};
  assert.equal(reportChartChoose(select, 'line'), true);
  assert.equal(select.value, 'line');
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'change');
  assert.equal(events[0].bubbles, true);
  for (const value of ['line', 'score', 'table', 'invalid', '__proto__']) assert.equal(reportChartChoose(select, value), false);
  assert.equal(events.length, 1);
  assert.equal(select.value, 'line');
});
