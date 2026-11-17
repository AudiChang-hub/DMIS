// T-212：領牌年月樹狀（年 → 月）的勾選狀態、點年份的結果、搜尋時的年份顯示。
const test = require('node:test');
const assert = require('node:assert/strict');
const {reportMonthYearState, reportMonthYearTarget, reportMonthYearCount, reportMonthYearVisibility} = require('../../static/js/report-month-tree.js');

test('年份狀態：全勾 true、部分勾半選 mixed、全不勾 false', () => {
  assert.equal(reportMonthYearState(12, 12), 'true');
  assert.equal(reportMonthYearState(3, 12), 'mixed');
  assert.equal(reportMonthYearState(0, 12), 'false');
  assert.equal(reportMonthYearState(0, 0), 'false');
});

test('點年份：未選或半選→全選該年各月；已全選→全部取消', () => {
  assert.equal(reportMonthYearTarget('false'), true);
  assert.equal(reportMonthYearTarget('mixed'), true);
  assert.equal(reportMonthYearTarget('true'), false);
});

test('勾年份後各月與年份狀態一致（全選、部分、取消）', () => {
  const months = Array.from({length: 12}, () => ({checked: false}));
  const state = () => reportMonthYearState(months.filter(month => month.checked).length, months.length);
  const clickYear = () => { const target = reportMonthYearTarget(state()); months.forEach(month => { month.checked = target; }); };
  clickYear();
  assert.equal(state(), 'true');
  months[4].checked = false;
  assert.equal(state(), 'mixed');
  clickYear();
  assert.equal(state(), 'true', '半選時點年份補滿整年');
  clickYear();
  assert.equal(state(), 'false', '全選時點年份全部取消');
});

test('年份旁的數量', () => {
  assert.equal(reportMonthYearCount(3, 12), '3／12');
  assert.equal(reportMonthYearCount(12, 12), '12／12');
});

test('搜尋：有符合月份的年份展開，沒有的藏起來；清空搜尋恢復原狀', () => {
  assert.deepEqual(reportMonthYearVisibility('05', 1), {hidden: false, expand: true});
  assert.deepEqual(reportMonthYearVisibility('2025', 0), {hidden: true, expand: false});
  assert.deepEqual(reportMonthYearVisibility('', 0), {hidden: false, expand: false});
});
