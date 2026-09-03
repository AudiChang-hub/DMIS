const test = require('node:test');
const assert = require('node:assert/strict');
const {placement} = require('../../static/js/floating-list.js');
const viewport = {left: 0, top: 0, width: 1280, height: 900};

test('桌機在欄位下方顯示，寬度對齊', () => {
  const p = placement({left: 100, top: 100, bottom: 148, width: 480}, viewport, 150);
  assert.equal(p.left, 100); assert.equal(p.width, 480); assert.equal(p.top, 153);
  assert.equal(p.openAbove, false); assert.equal(p.maxHeight, 330);
});
test('底部不足時向上展開，短清單緊貼欄位', () => {
  const p = placement({left: 100, top: 750, bottom: 798, width: 480}, viewport, 100);
  assert.equal(p.openAbove, true); assert.equal(p.top, 645);
});
test('手機過寬欄位不溢出左右邊界', () => {
  const p = placement({left: 240, top: 200, bottom: 248, width: 500}, {left: 0, top: 0, width: 390, height: 844});
  assert.equal(p.width, 366); assert.equal(p.left, 12);
});
test('極窄視窗不強迫維持 220px', () => {
  const p = placement({left: 0, top: 30, bottom: 70, width: 200}, {left: 0, top: 0, width: 180, height: 300});
  assert.equal(p.width, 156); assert.equal(p.left, 12);
});
test('軟鍵盤縮小視窗時選項高度不超過可見空間', () => {
  const p = placement({left: 15, top: 150, bottom: 198, width: 330}, {left: 0, top: 80, width: 390, height: 200});
  assert.equal(p.openAbove, false); assert.equal(p.maxHeight, 65);
  assert.ok(p.top + p.maxHeight <= 268);
});
test('縮放平移後使用 visualViewport 的位移', () => {
  const p = placement({left: 20, top: 280, bottom: 328, width: 300}, {left: 50, top: 180, width: 300, height: 220}, 80);
  assert.equal(p.left, 62); assert.equal(p.openAbove, true); assert.equal(p.top, 195);
});
test('各螢幕尺寸及欄位位置皆留在可見範圍', () => {
  for (const width of [180, 320, 390, 760, 1440]) {
    for (const height of [200, 400, 844, 1050]) {
      for (const top of [20, height / 2 - 24, height - 70]) {
        const p = placement({left: width - 40, top, bottom: top + 48, width: 350}, {left: 0, top: 0, width, height}, 330);
        assert.ok(p.left >= 12 && p.left + p.width <= width - 12);
        assert.ok(p.top >= 12 && p.top + p.maxHeight <= height - 12);
      }
    }
  }
});
