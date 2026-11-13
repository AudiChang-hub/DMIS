const test = require('node:test');
const assert = require('node:assert/strict');
const {classificationBatchText} = require('../../static/js/report-classification.js');

test('T-164 未歸類型號：顯示已選數量，未選時提示先勾選', () => {
  assert.equal(classificationBatchText(0), '勾選型號後選類別');
  assert.equal(classificationBatchText(3), '已選 3 個型號');
});
