const test = require('node:test');
const assert = require('node:assert/strict');
const {designerScale} = require('../../static/js/report-designer.js');
test('畫布縮放不改變目標內容寬度', () => {
  assert.equal(designerScale('fit', 1440, 2000, 720, 600), .5);
  assert.equal(designerScale('page', 1440, 2000, 720, 600), .3);
  assert.equal(designerScale('1', 1440, 2000, 720, 600), 1);
  assert.equal(designerScale('fit', 390, 2000, 900, 600), 1);
});
test('縮放防呆及極窄容器', () => {
  assert.equal(designerScale('fit', 1440, 2000, 0, 600), .1);
  assert.equal(designerScale('page', 1440, 2000, 0, 0), .05);
  assert.equal(designerScale('bad', 1440, 2000, 500, 600), 1);
});
