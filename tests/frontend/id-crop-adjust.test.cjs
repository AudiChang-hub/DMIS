// T-220：證件裁切視窗的亮度、清晰度（照身分證排版工具）。前端預覽要和伺服器輸出（id_card_crop.adjust，OpenCV）一致：
// 期望值由伺服器算出，前端允許 ±2 的捨入差。
const test = require('node:test');
const assert = require('node:assert/strict');
const crop = require('../../static/js/id-crop-editor.js');

function rgba(colors) {
  const pixels = new Uint8ClampedArray(colors.length * 4);
  colors.forEach(([r, g, b], index) => pixels.set([r, g, b, 255], index * 4));
  return pixels;
}

function close(actual, expected, label) {
  actual.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) <= 2, `${label} 第 ${index} 值 ${value} ≠ ${expected[index]}`));
}

const COLORS = [[128, 128, 128], [200, 60, 40], [30, 90, 200], [245, 245, 240], [10, 10, 10], [90, 160, 70]];
const SERVER = {  // sales.services.id_card_crop.adjust(…, brightness, 0)
  50: [[170, 171, 170], [255, 111, 83], [104, 136, 253], [249, 250, 245], [33, 33, 33], [128, 200, 106]],
  '-50': [[79, 79, 79], [138, 0, 0], [0, 46, 145], [238, 239, 234], [0, 0, 0], [36, 111, 21]],
  25: [[151, 151, 151], [230, 87, 62], [74, 113, 227], [247, 248, 243], [21, 21, 21], [110, 181, 89]],
};

test('亮度查表與工具相同：黑白不動，中間調 128 在 +50→172、-50→77', () => {
  assert.deepEqual([0, 128, 255].map(i => crop.brightnessTable(50)[i]), [0, 172, 255]);
  assert.deepEqual([0, 128, 255].map(i => crop.brightnessTable(-50)[i]), [0, 77, 255]);
});

for (const brightness of Object.keys(SERVER)) {
  test(`亮度 ${brightness}：前端結果和伺服器一致（±2）`, () => {
    const pixels = crop.adjustPixels(rgba(COLORS), COLORS.length, 1, Number(brightness), 0);
    COLORS.forEach((_, index) => close([...pixels.slice(index * 4, index * 4 + 3)], SERVER[brightness][index], `顏色 ${index}`));
    assert.ok([...pixels].filter((_, i) => i % 4 === 3).every(alpha => alpha === 255), '不透明度不變');
  });
}

function step() {
  const row = [40, 40, 40, 40, 40, 200, 200, 200, 200, 200, 200, 200];
  const colors = [];
  for (let y = 0; y < 3; y += 1) row.forEach(v => colors.push([v, v, v]));
  return {pixels: rgba(colors), width: row.length, height: 3};
}

for (const [brightness, sharpness, expected] of [
  [0, 60, [40, 40, 40, 40, 25, 215, 200, 200, 200, 200, 200, 200]],
  [0, 100, [40, 40, 40, 40, 14, 226, 200, 200, 200, 200, 200, 200]],
  [30, 60, [64, 64, 64, 64, 50, 229, 215, 215, 215, 215, 215, 215]],
]) {
  test(`亮度 ${brightness}、清晰度 ${sharpness}：邊緣加強和伺服器一致（±2）`, () => {
    const {pixels, width, height} = step();
    crop.adjustPixels(pixels, width, height, brightness, sharpness);
    close(Array.from({length: width}, (_, x) => pixels[(width + x) * 4]), expected, '中間列');
  });
}

test('都是 0 時原圖不動；超出範圍會截在 -50～50、0～100', () => {
  const original = rgba(COLORS);
  assert.deepEqual([...crop.adjustPixels(rgba(COLORS), COLORS.length, 1, 0, 0)], [...original]);
  const over = crop.adjustPixels(rgba(COLORS), COLORS.length, 1, 999, 0);
  const max = crop.adjustPixels(rgba(COLORS), COLORS.length, 1, 50, 0);
  assert.deepEqual([...over], [...max]);
});
