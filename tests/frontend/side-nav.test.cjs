const test = require('node:test');
const assert = require('node:assert/strict');
const {pickCurrent} = require('../../static/js/side-nav.js');

// 營運總表捲到頁底：即時工作量佔上半，庫存概況頂端停在視窗約三成處，捲不到判定線。
const viewport = 900;
const line = 96 + 160;

test('一般捲動標示頂端已越過判定線的最後一個段落', () => {
  assert.equal(pickCurrent([-1200, -400, 120, 700], {line, viewport, atBottom: false}), 2);
  assert.equal(pickCurrent([-1200, -400, 300, 900], {line, viewport, atBottom: false}), 1);
});

test('捲到頁底時標示最後一個看得到的段落，頁尾短段落也點得到', () => {
  const bottom = [-2600, -1500, -300, 330];
  assert.equal(pickCurrent(bottom, {line, viewport, atBottom: false}), 2, '未到頁底時判定線以上是即時工作量');
  assert.equal(pickCurrent(bottom, {line, viewport, atBottom: true}), 3, '到頁底改標庫存概況');
});

test('還在頁首、所有段落都在判定線下方時標示第一段', () => {
  assert.equal(pickCurrent([400, 1200, 2000], {line, viewport, atBottom: false}), 0);
});

test('隱藏的段落不參與標示', () => {
  assert.equal(pickCurrent([-800, 100, null], {line, viewport, atBottom: true}), 1);
  assert.equal(pickCurrent([null, 500, 1200], {line, viewport, atBottom: false}), 1);
});
