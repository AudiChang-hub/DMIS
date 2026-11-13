// T-151：大數據分析樹狀篩選的勾選狀態與送出資料。
const test = require('node:test');
const assert = require('node:assert/strict');
const {reportTreeCheckedState, reportTreeStatus, reportTreeFormData} = require('../../static/js/report-tree-filter.js');
const {reportFilterDelay} = require('../../static/js/report-interactions.js');

test('父層狀態：全勾 true、部分 mixed（半選）、全不勾 false', () => {
  assert.equal(reportTreeCheckedState(3, 3), 'true');
  assert.equal(reportTreeCheckedState(1, 3), 'mixed');
  assert.equal(reportTreeCheckedState(0, 3), 'false');
  assert.equal(reportTreeCheckedState(0, 0), 'false');
});

test('狀態列文字', () => {
  assert.equal(reportTreeStatus(13, 13), '全部 13 個車型');
  assert.equal(reportTreeStatus(12, 13), '已選 12／13 個車型');
  assert.equal(reportTreeStatus(0, 13), '未選取（不顯示資料）');
});

test('送出：全選不帶車型、部分照送、全不勾改送 empty_model', () => {
  const build = entries => { const data = new FormData(); entries.forEach(([k, v]) => data.append(k, v)); return data; };
  const all = reportTreeFormData(build([['model', '1'], ['model', '2'], ['empty_model', 'False'], ['months', '2026-10']]), 2, 2);
  assert.deepEqual([...all], [['months', '2026-10']]);
  const some = reportTreeFormData(build([['model', '1'], ['empty_model', 'True']]), 1, 2);
  assert.deepEqual([...some], [['model', '1']]);
  const none = reportTreeFormData(build([['empty_model', '']]), 0, 2);
  assert.deepEqual([...none], [['empty_model', '1']]);
});

test('樹狀勾選經由表單內的代理欄位走既有的 300ms 防抖；其他隱藏欄位照舊不觸發', () => {
  assert.equal(reportFilterDelay({dataset: {reportTreeProxy: ''}, type: 'hidden', name: ''}), 300);
  assert.equal(reportFilterDelay({dataset: {}, type: 'hidden', name: 'revision'}), null);
  assert.equal(reportFilterDelay({dataset: {reportMulti: ''}}), 300);
});

// T-152：寬螢幕向右收合，狀態記在 localStorage；讀寫失敗不影響操作。
const {reportTreeRailCount, reportTreeReadCollapsed, reportTreeWriteCollapsed, REPORT_TREE_COLLAPSED_KEY} = require('../../static/js/report-tree-filter.js');

test('收合後窄邊顯示目前勾選數量', () => {
  assert.equal(reportTreeRailCount(39, 39), '已選 39／39');
  assert.equal(reportTreeRailCount(3, 39), '已選 3／39');
});

test('收合狀態寫入與讀回；沒有儲存或被封鎖時當作展開', () => {
  const data = new Map();
  const storage = {getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value)};
  assert.equal(reportTreeReadCollapsed(storage), false);
  assert.equal(reportTreeWriteCollapsed(storage, true), true);
  assert.equal(data.get(REPORT_TREE_COLLAPSED_KEY), '1');
  assert.equal(reportTreeReadCollapsed(storage), true);
  reportTreeWriteCollapsed(storage, false);
  assert.equal(reportTreeReadCollapsed(storage), false);
  const blocked = {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }};
  assert.equal(reportTreeReadCollapsed(blocked), false);
  assert.equal(reportTreeWriteCollapsed(blocked, true), false);
  assert.equal(reportTreeReadCollapsed(null), false);
});
