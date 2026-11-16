const {test} = require('node:test');
const assert = require('node:assert/strict');
const {homography, warpPixels, parse, describe, fullParams} = require('../../static/js/id-crop-editor.js');

// 4×2 的原圖：左半紅、右半藍（RGBA）。
function source() {
  const pixels = new Uint8ClampedArray(4 * 2 * 4);
  for (let y = 0; y < 2; y += 1) for (let x = 0; x < 4; x += 1) {
    const o = (y * 4 + x) * 4;
    pixels.set(x < 2 ? [255, 0, 0, 255] : [0, 0, 255, 255], o);
  }
  return pixels;
}
const full = turn => ({v: 1, corners: [[0, 0], [1, 0], [1, 1], [0, 1]], turn, src_w: 4, src_h: 2, mode: 'manual', by_ocr: false});
const pixelAt = (pixels, width, x, y) => Array.from(pixels.slice((y * width + x) * 4, (y * width + x) * 4 + 3));

test('homography 把四角對到指定位置', () => {
  const h = homography([[0, 0], [10, 0], [10, 10], [0, 10]], [[5, 5], [25, 5], [25, 15], [5, 15]]);
  const map = (u, v) => { const w = h[6] * u + h[7] * v + 1; return [(h[0] * u + h[1] * v + h[2]) / w, (h[3] * u + h[4] * v + h[5]) / w]; };
  assert.deepEqual(map(10, 10).map(Math.round), [25, 15]);
  assert.deepEqual(map(5, 5).map(Math.round), [15, 10]);
  assert.equal(homography([[0, 0], [0, 0], [0, 0], [0, 0]], [[0, 0], [1, 0], [1, 1], [0, 1]]), null);
});

test('turn 決定哪一邊是上緣：0 原樣、2 上下顛倒', () => {
  const upright = warpPixels(source(), 4, 2, full(0), 8, 4);
  assert.deepEqual(pixelAt(upright, 8, 0, 0), [255, 0, 0]);
  assert.deepEqual(pixelAt(upright, 8, 7, 3), [0, 0, 255]);
  const flipped = warpPixels(source(), 4, 2, full(2), 8, 4);
  assert.deepEqual(pixelAt(flipped, 8, 0, 0), [0, 0, 255]);
  assert.deepEqual(pixelAt(flipped, 8, 7, 3), [255, 0, 0]);
});

test('turn 1：原圖右邊成為上緣（向左轉 90°）', () => {
  const turned = warpPixels(source(), 4, 2, full(1), 8, 4);
  // 上緣是原圖右邊（藍）、下緣是原圖左邊（紅）。
  assert.deepEqual(pixelAt(turned, 8, 4, 0), [0, 0, 255]);
  assert.deepEqual(pixelAt(turned, 8, 4, 3), [255, 0, 0]);
});

test('parse 只接受第 1 版、四個角的參數', () => {
  assert.equal(parse(''), null);
  assert.equal(parse('not json'), null);
  assert.equal(parse('{"v":2,"corners":[[0,0],[1,0],[1,1],[0,1]]}'), null);
  assert.equal(parse(JSON.stringify(full(0))).turn, 0);
});

test('卡片標示與整張圖片的預設方向', () => {
  assert.equal(describe({mode: 'auto', turn: 2}), '已自動轉正 180°');
  assert.equal(describe({mode: 'auto', turn: 3}), '已自動轉正 90°');
  assert.equal(describe({mode: 'auto', turn: 0}), '已自動裁切');
  assert.equal(describe({mode: 'manual', turn: 1}), '已手動調整');
  assert.equal(describe({mode: 'full', turn: 0}), '使用整張圖片');
  assert.equal(fullParams({naturalWidth: 600, naturalHeight: 900}).turn, 3);
  assert.equal(fullParams({naturalWidth: 900, naturalHeight: 600}).turn, 0);
});

// T-194：只上傳一面、或重開沒有裁切參數的草稿時，要馬上自動偵測並顯示卡片，不必等兩面都上傳。
test('卡片參數：已存的優先，沒有就用自動偵測；有照片又沒參數時要自動偵測', () => {
  const {cardState} = require('../../static/js/id-crop-editor.js');
  const saved = JSON.stringify({...full(1), mode: 'manual'});
  const auto = {...full(0), mode: 'auto'};
  assert.deepEqual(cardState({saved: '', auto: null, hasPhoto: true, pending: false}), {params: null, detect: true});
  assert.deepEqual(cardState({saved: '', auto, hasPhoto: true, pending: false}), {params: auto, detect: false});
  assert.equal(cardState({saved, auto, hasPhoto: true, pending: false}).params.mode, 'manual');
  assert.deepEqual(cardState({saved: '', auto: null, hasPhoto: false, pending: false}), {params: null, detect: false});
  assert.deepEqual(cardState({saved: '', auto: null, hasPhoto: true, pending: true}), {params: null, detect: false});
});

// T-198：車主類型在本國與居留者之間切換時，手動調整的保留；自動偵測的重算（已存的重算後存回）。
test('換證件規則時：手動保留、自動已存的重算並存回、只顯示的重算', () => {
  const {recropPlan} = require('../../static/js/id-crop-editor.js');
  assert.equal(recropPlan(JSON.stringify({...full(1), mode: 'manual'})), 'keep');
  assert.equal(recropPlan(JSON.stringify({...full(0), mode: 'auto'})), 'redetect-save');
  assert.equal(recropPlan(JSON.stringify({...full(0), mode: 'full'})), 'redetect-save');
  assert.equal(recropPlan(''), 'redetect');
});

// T-200：沒把握的卡片標「建議確認裁切」；手動調整後不再提醒。
test('建議確認裁切：needs_review 且非手動才標', () => {
  const {needsReview, describe: label} = require('../../static/js/id-crop-editor.js');
  assert.equal(needsReview({...full(0), mode: 'auto', needs_review: true}), true);
  assert.equal(label({...full(0), mode: 'auto', needs_review: true}), '建議確認裁切');
  assert.equal(needsReview({...full(0), mode: 'full', needs_review: true}), true);
  assert.equal(needsReview({...full(0), mode: 'manual', needs_review: true}), false);
  assert.equal(needsReview({...full(0), mode: 'auto', needs_review: false}), false);
  assert.equal(label({...full(2), mode: 'auto', needs_review: false}), '已自動轉正 180°');
});
