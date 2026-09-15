const test = require('node:test');
const assert = require('node:assert/strict');
const {choices} = require('../../static/js/catalog-manage.js');
const rows = [
  {brand:'SUZUKI',name:'SUI',model_number:'UQ125DA'},
  {brand:'SUZUKI',name:'SUI',model_number:'UQ125DA'},
  {brand:'SUZUKI',name:'GSX',model_number:'GSX150'},
  {brand:'OTHER',name:'SUI',model_number:'OTHER125'},
  {brand:'OTHER',name:'EMPTY',model_number:''},
];
test('車型選項依品牌去重，不混入其他品牌', () => {
  assert.deepEqual(choices(rows,'name','SUZUKI',''), ['SUI','GSX']);
});
test('型號取品牌車型交集並排除空值', () => {
  assert.deepEqual(choices(rows,'model_number','SUZUKI','SUI'), ['UQ125DA']);
  assert.deepEqual(choices(rows,'model_number','OTHER','EMPTY'), []);
  assert.deepEqual(choices(rows,'model_number','','SUI'), ['UQ125DA','OTHER125']);
});
test('空資料與不存在條件不產生錯誤選項', () => {
  assert.deepEqual(choices([],'name','',''), []);
  assert.deepEqual(choices(rows,'model_number','MISSING',''), []);
});
