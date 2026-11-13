const test = require('node:test');
const assert = require('node:assert/strict');
const {catalogPayload, catalogKeyboardTarget} = require('../../static/js/report-catalog.js');

test('T-164 目錄排序送出全部報表，依畫面分組與先後，版本號轉為數字', () => {
  assert.deepEqual(catalogPayload([
    {group: 'sales', rows: [{pk: '3', version: '2'}, {pk: '1', version: '5'}]},
    {group: 'analysis', rows: []},
    {group: 'custom', rows: [{pk: '7', version: '1'}]},
  ]), {pages: [{pk: 3, group: 'sales', version: 2}, {pk: 1, group: 'sales', version: 5}, {pk: 7, group: 'custom', version: 1}]});
});

test('T-164 鍵盤上下移動：組內移一格，到邊界就移到相鄰分組，最外側不動', () => {
  const lists = [{group: 'sales', size: 3}, {group: 'analysis', size: 0}, {group: 'custom', size: 2}];
  assert.deepEqual(catalogKeyboardTarget(lists, 'sales', 1, -1), {group: 'sales', index: 0});
  assert.deepEqual(catalogKeyboardTarget(lists, 'sales', 2, 1), {group: 'analysis', index: 0});
  assert.deepEqual(catalogKeyboardTarget(lists, 'custom', 0, -1), {group: 'analysis', index: 0});
  assert.deepEqual(catalogKeyboardTarget([{group: 'sales', size: 2}, {group: 'custom', size: 2}], 'custom', 0, -1), {group: 'sales', index: 2});
  assert.equal(catalogKeyboardTarget(lists, 'sales', 0, -1), null);
  assert.equal(catalogKeyboardTarget(lists, 'custom', 1, 1), null);
  assert.equal(catalogKeyboardTarget(lists, 'finance', 0, 1), null);
});
