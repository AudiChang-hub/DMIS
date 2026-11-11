// T-140 第 4～9 點（使用者 2026-11-11）：圖表操作選單匯出改為按下後才選格式。
const test = require('node:test');
const assert = require('node:assert/strict');
const {reportExportUrl, REPORT_EXPORT_FORMATS} = require('../../static/js/report-overview.js');

test('匯出：按下去才選格式，網址帶上格式與是否保留值格式、原本的篩選照留', () => {
  assert.deepEqual(REPORT_EXPORT_FORMATS.map(([value]) => value), ['csv', 'excel']);
  const url = new URL(reportExportUrl('http://x/reports/2/export/0/?revision=a&legacy_source=%E8%BB%8A%E8%A1%8C', 'excel', true));
  assert.equal(url.searchParams.get('format'), 'excel');
  assert.equal(url.searchParams.get('formatted'), '1');
  assert.equal(url.searchParams.get('legacy_source'), '車行');
  assert.equal(new URL(reportExportUrl('http://x/e/?a=1', 'csv', false)).searchParams.get('formatted'), '0');
});
