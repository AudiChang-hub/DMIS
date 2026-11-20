// T-262 驗收（2.32.5）：訂單頁證件卡片預覽的轉向。只有「自動偵測失敗、自動改用整張照片」（mode=full 且還沒確認）
// 才不轉向、照原照片比例；使用者在調整視窗選「使用整張圖片」並套用的，保留使用者的轉向，和調整視窗、列印一致。
const test = require('node:test');
const assert = require('node:assert/strict');
const crop = require('../../static/js/id-crop-editor.js');

const PORTRAIT = {naturalWidth: 1200, naturalHeight: 1600};

test('自動改用整張照片（還沒確認）：照原照片比例、不轉向', () => {
  const auto = {v: 1, corners: [[0, 0], [1, 0], [1, 1], [0, 1]], turn: 0, src_w: 1200, src_h: 1600, mode: 'full', needs_review: true};
  const shape = crop.previewShape(auto);
  assert.equal(shape.whole, true);
  assert.equal(shape.params.turn, 0);
  // 舊參數（伺服器改版前）帶了轉向，預覽也不轉。
  assert.equal(crop.previewShape({...auto, turn: 3}).params.turn, 0);
});

test('手動「使用整張圖片」並套用：保留使用者的轉向，畫成卡片比例', () => {
  // 調整視窗的「使用整張圖片」：直式照片給 turn 3；按「套用」後 mode 仍是 full、提醒清除（apply）。
  const chosen = {...crop.fullParams(PORTRAIT), corners: [[0, 0], [1, 0], [1, 1], [0, 1]]};
  assert.equal(chosen.turn, 3);
  const applied = {...chosen, mode: 'full', needs_review: false, by_ocr: false};
  const shape = crop.previewShape(applied);
  assert.equal(shape.whole, false);
  assert.equal(shape.params.turn, 3);
  assert.equal(shape.params, applied);
});

test('自動偵測到卡片或手動調整：照參數畫', () => {
  for (const params of [
    {mode: 'auto', turn: 1, needs_review: true},
    {mode: 'auto', turn: 2, needs_review: false},
    {mode: 'manual', turn: 3, needs_review: true},
  ]) {
    const shape = crop.previewShape(params);
    assert.equal(shape.whole, false);
    assert.equal(shape.params.turn, params.turn);
  }
});
