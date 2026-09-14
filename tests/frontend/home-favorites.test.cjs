const test = require('node:test');
const assert = require('node:assert/strict');
const {moveItem, toggleItem, matches} = require('../../static/js/home-favorites.js');

test('勾選附加且不重複，取消僅移除指定項目', () => {
  assert.deepEqual(toggleItem(['orders'], 'inventory', true), ['orders', 'inventory']);
  assert.deepEqual(toggleItem(['orders'], 'orders', true), ['orders']);
  assert.deepEqual(toggleItem(['orders', 'help'], 'orders', false), ['help']);
  assert.deepEqual(toggleItem(['orders'], 'orders', false), []);
});
test('上下排序保留其他項目且不改原陣列', () => {
  const keys = ['orders', 'help', 'inventory'];
  assert.deepEqual(moveItem(keys, 'help', -1), ['help', 'orders', 'inventory']);
  assert.deepEqual(moveItem(keys, 'help', 1), ['orders', 'inventory', 'help']);
  assert.deepEqual(keys, ['orders', 'help', 'inventory']);
});
test('排序不越界、不加入未知代碼', () => {
  assert.deepEqual(moveItem(['orders'], 'orders', -1), ['orders']);
  assert.deepEqual(moveItem(['orders'], 'orders', 1), ['orders']);
  assert.deepEqual(moveItem(['orders'], 'missing', 1), ['orders']);
  assert.deepEqual(moveItem([], 'missing', 1), []);
});
test('搜尋支援中文、多關鍵字、忽略英文字母大小寫', () => {
  assert.equal(matches('舊資料 Excel 匯入', 'excel 匯入', false, false), true);
  assert.equal(matches('車輛庫存', '庫存', false, false), true);
  assert.equal(matches('車輛庫存', '訂單', false, true), false);
  assert.equal(matches('車輛庫存', '  ', false, false), true);
});
test('只看已選可與搜尋一起使用', () => {
  assert.equal(matches('全部訂單', '訂單', true, true), true);
  assert.equal(matches('全部訂單', '訂單', true, false), false);
});
