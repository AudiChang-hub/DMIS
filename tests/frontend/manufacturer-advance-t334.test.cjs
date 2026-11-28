// T-334 原廠代墊／代轉（static/js/manufacturer-advance.js）：登記原廠撥款的勾選合計／實撥／差額、
// 只選一筆時預設帶那一筆的金額、一次只能一家原廠、勾選後兩個頁籤的筆數加減、超過 7 天才提醒。
// 畫面接線（勾了就存、復原、側邊明細）由 Django 測試與瀏覽器驗收涵蓋；這裡測純計算。
const test = require('node:test');
const assert = require('node:assert/strict');
const advance = require('../../static/js/manufacturer-advance.js');

const pick = (amount, manufacturer = 'SUZUKI', gift = 0) => ({amount, manufacturer, gift});

test('勾選合計只算金額，贈品另計件數', () => {
  const summary = advance.selectionSummary([pick(1000), pick(500), pick(0, 'SUZUKI', 3)]);
  assert.equal(summary.count, 3);
  assert.equal(summary.total, 1500);
  assert.equal(summary.gifts, 3);
  assert.equal(summary.mixed, false);
});

test('勾到不同原廠時標出來，不能一起登記', () => {
  const summary = advance.selectionSummary([pick(1000, 'SUZUKI'), pick(500, 'SYM')]);
  assert.equal(summary.mixed, true);
  assert.deepEqual(summary.manufacturers, ['SUZUKI', 'SYM']);
});

test('只選一筆時，實撥金額預設帶那一筆的金額；多筆或贈品留空', () => {
  assert.equal(advance.defaultPayoutAmount([pick(1200)]), '1200');
  assert.equal(advance.defaultPayoutAmount([pick(1200), pick(300)]), '');
  assert.equal(advance.defaultPayoutAmount([pick(0, 'SUZUKI', 2)]), '');
  assert.equal(advance.defaultPayoutAmount([]), '');
});

test('差額＝實撥－勾選合計：少撥、多撥、剛好、還沒填', () => {
  const less = advance.payoutFigures(1500, '1200');
  assert.equal(less.difference, -300);
  assert.equal(less.differenceText, '−$300');
  assert.equal(less.tone, 'is-negative');
  const more = advance.payoutFigures(1500, '1700');
  assert.equal(more.differenceText, '＋$200');
  assert.equal(more.tone, 'is-positive');
  const exact = advance.payoutFigures(1500, '1500');
  assert.equal(exact.difference, 0);
  assert.equal(exact.differenceText, '沒有差額');
  const blank = advance.payoutFigures(1500, '');
  assert.equal(blank.actual, null);
  assert.equal(blank.differenceText, '—');
  assert.equal(blank.selectedText, '$1,500');
});

test('實撥金額只收整數（可以是 0），負數與小數不算', () => {
  assert.equal(advance.parseAmount('0'), 0);
  assert.equal(advance.parseAmount(' 2500 '), 2500);
  assert.equal(advance.parseAmount('-5'), null);
  assert.equal(advance.parseAmount('12.5'), null);
  assert.equal(advance.payoutFigures(800, '0').differenceText, '−$800');
});

test('勾或取消後，頁籤筆數跟著加減（三處同步時各自更新）', () => {
  const none = {reimbursed: false, handed_over: false};
  assert.deepEqual(advance.tabDeltas(none, {reimbursed: true, handed_over: false}), {reimburse: -1, handover: 0});
  assert.deepEqual(advance.tabDeltas({reimbursed: true, handed_over: false}, none), {reimburse: 1, handover: 0});
  assert.deepEqual(advance.tabDeltas(none, {reimbursed: false, handed_over: true}), {reimburse: 0, handover: -1});
  assert.deepEqual(advance.tabDeltas(none, none), {reimburse: 0, handover: 0});
});

test('超過 7 天才提醒，剛好 7 天不標', () => {
  assert.equal(advance.isOverdue(7), false);
  assert.equal(advance.isOverdue(8), true);
  assert.equal(advance.isOverdue(0), false);
});
