const test = require('node:test');
const assert = require('node:assert/strict');
const {canonical, decision} = require('../../static/js/order-workspace.js');
test('金額正規化避免 0、空白與小數位造成假衝突', () => {
  assert.equal(canonical({type:'number'}, '0.0000'), canonical({type:'number'}, ''));
  assert.equal(canonical({type:'number'}, '800.00'), 800);
});
test('布林欄位與空值正規化', () => {
  assert.equal(canonical({type:'checkbox'}, true), true);
  assert.equal(canonical({type:'checkbox'}, false), false);
  assert.equal(canonical({type:'text'}, null), '');
});
test('跨頁籤三方合併：乾淨欄位更新、未儲存輸入保留、重疊衝突不覆寫', () => {
  assert.equal(decision(100, 100, 200), 'update');
  assert.equal(decision(100, 150, 100), 'keep');
  assert.equal(decision(100, 150, 150), 'keep');
  assert.equal(decision(100, 150, 200), 'conflict');
});
test('同名勾選組合併比對：部分勾選不會永遠判定未儲存，改勾才算修改', () => {
  const {snapshot} = require('../../static/js/order-workspace.js');
  const box = (checked) => ({name: 'subsidy_programs', type: 'checkbox', checked});
  const before = snapshot([box(true), box(false)]);
  assert.equal(before.get('subsidy_programs'), snapshot([box(true), box(false)]).get('subsidy_programs'));
  assert.notEqual(before.get('subsidy_programs'), snapshot([box(false), box(false)]).get('subsidy_programs'));
});
test('radio 只看選中的選項', () => {
  const {snapshot} = require('../../static/js/order-workspace.js');
  const radio = (value, checked) => ({name: 'plate', type: 'radio', value, checked});
  assert.equal(snapshot([radio('a', true), radio('b', false)]).get('plate'), snapshot([radio('a', true), radio('b', false)]).get('plate'));
  assert.notEqual(snapshot([radio('a', true), radio('b', false)]).get('plate'), snapshot([radio('a', false), radio('b', true)]).get('plate'));
});
