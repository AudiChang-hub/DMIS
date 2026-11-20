// T-253（使用者 2026-11-20「上傳證件的部分，他的圖片會異常扭曲，造成辨識出問題」）：
// iPhone 相機當場拍的照片是橫的像素＋EXIF 方向 6／8。瀏覽器若回報轉正後的尺寸、canvas 卻畫沒轉的像素，
// 卡片預覽會被拉伸變形。這裡用模擬的瀏覽器重現那種行為，確認快照會先依 EXIF 轉正；其他瀏覽器行為不變。
// 全部是程式產生的位元組與假畫布，不含任何照片。
const {test} = require('node:test');
const assert = require('node:assert/strict');

// 最小 JPEG：SOI＋APP1(Exif，只有方向一個欄位)＋EOI。
function jpegWithOrientation(orientation, little = false) {
  const tiff = Buffer.alloc(26);
  if (little) {
    tiff.write('II', 0, 'latin1'); tiff.writeUInt16LE(42, 2); tiff.writeUInt32LE(8, 4); tiff.writeUInt16LE(1, 8);
    tiff.writeUInt16LE(0x0112, 10); tiff.writeUInt16LE(3, 12); tiff.writeUInt32LE(1, 14); tiff.writeUInt16LE(orientation, 18);
  } else {
    tiff.write('MM', 0, 'latin1'); tiff.writeUInt16BE(42, 2); tiff.writeUInt32BE(8, 4); tiff.writeUInt16BE(1, 8);
    tiff.writeUInt16BE(0x0112, 10); tiff.writeUInt16BE(3, 12); tiff.writeUInt32BE(1, 14); tiff.writeUInt16BE(orientation, 18);
  }
  const payload = Buffer.concat([Buffer.from('Exif\0\0', 'latin1'), tiff]);
  const app1 = Buffer.alloc(4); app1.writeUInt16BE(0xFFE1, 0); app1.writeUInt16BE(payload.length + 2, 2);
  return Buffer.concat([Buffer.from([0xFF, 0xD8]), app1, payload, Buffer.from([0xFF, 0xD9])]);
}
const view = bytes => new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

// 模擬「尺寸已轉正、canvas 沒轉」的瀏覽器：實測小圖 1×2，但畫出來上下兩點一樣（左右像素被擠在一起）。
const calls = [];
function fakeCanvas() {
  const canvas = {width: 0, height: 0};
  canvas.getContext = () => ({
    setTransform(...args) { calls.push(['setTransform', ...args]); },
    drawImage(image, ...args) { calls.push(['drawImage', image.kind, ...args]); },
    getImageData(x, y, width, height) {
      const data = new Uint8ClampedArray(width * height * 4).fill(128);
      return {data};
    },
    createImageData(width, height) { return {data: new Uint8ClampedArray(width * height * 4)}; },
    putImageData() {},
  });
  return canvas;
}
class FakeEvent { constructor(type) { this.type = type; } }
class FakeImage {
  constructor() { this.kind = 'probe'; this.naturalWidth = 1; this.naturalHeight = 2; }
  set src(value) { this._src = value; queueMicrotask(() => this.onload && this.onload()); }
}
global.window = {};
global.Event = FakeEvent;
global.Image = FakeImage;
global.document = {createElement: () => fakeCanvas()};
global.fetch = async () => ({arrayBuffer: async () => { const b = jpegWithOrientation(6); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); }});
const crop = require('../../static/js/id-crop-editor.js');

test('讀得到 JPEG 的 EXIF 方向（大端、小端）；沒有 EXIF 或不是 JPEG 都當 1', () => {
  assert.equal(crop.exifOrientation(view(jpegWithOrientation(6))), 6);
  assert.equal(crop.exifOrientation(view(jpegWithOrientation(8, true))), 8);
  assert.equal(crop.exifOrientation(view(Buffer.from([0xFF, 0xD8, 0xFF, 0xD9]))), 1);
  assert.equal(crop.exifOrientation(view(Buffer.from('not a jpeg'))), 1);
  // 內建的實測小圖本身就是方向 6。
  const source = require('node:fs').readFileSync(require.resolve('../../static/js/id-crop-editor.js'), 'utf8');
  const base64 = source.match(/ORIENTATION_PROBE = "data:image\/jpeg;base64,([^"]+)"/)[1];
  assert.equal(crop.exifOrientation(view(Buffer.from(base64, 'base64'))), 6);
});

test('實測小圖分三種瀏覽器：都轉、只有 <img> 轉、都沒轉', () => {
  assert.equal(crop.classifyProbe(1, 2, 0, 255), 'auto');
  assert.equal(crop.classifyProbe(1, 2, 128, 128), 'manual');
  assert.equal(crop.classifyProbe(2, 1, 0, 255), 'legacy');
});

test('轉換矩陣把原始像素的四角放到轉正後的正確位置', () => {
  const apply = ([a, b, c, d, e, f], [x, y]) => [a * x + c * y + e, b * x + d * y + f];
  const W = 300, H = 400;  // 轉正後（直式）
  // 方向 6：原圖（400×300 橫）順時針轉 90°：原圖左上→右上、原圖右上→右下。
  assert.deepEqual(apply(crop.orientationMatrix(6, W, H), [0, 0]), [W, 0]);
  assert.deepEqual(apply(crop.orientationMatrix(6, W, H), [H, 0]), [W, H]);
  // 方向 8：逆時針 90°：原圖左上→左下、原圖右上→左上。
  assert.deepEqual(apply(crop.orientationMatrix(8, W, H), [0, 0]), [0, H]);
  assert.deepEqual(apply(crop.orientationMatrix(8, W, H), [H, 0]), [0, 0]);
  // 方向 3：180°。
  assert.deepEqual(apply(crop.orientationMatrix(3, W, H), [0, 0]), [W, H]);
  assert.deepEqual(crop.orientationMatrix(1, W, H), [1, 0, 0, 1, 0, 0]);
});

test('canvas 沒轉的瀏覽器：快照先依 EXIF 轉正再畫，不把橫的像素硬塞進直的框', async () => {
  await new Promise(resolve => setTimeout(resolve, 0));  // 等實測小圖跑完
  assert.equal(crop.canvasOrientationMode(), 'manual');
  const listeners = {};
  const photo = {
    kind: 'photo', complete: true, naturalWidth: 300, naturalHeight: 400, currentSrc: 'blob:photo', dataset: {},
    addEventListener(type, fn) { listeners[type] = fn; }, dispatchEvent(event) { listeners[event.type]?.(); },
  };
  const params = {v: 1, corners: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]], turn: 3, src_w: 300, src_h: 400, mode: 'auto'};
  const canvas = fakeCanvas(); canvas.width = 64; canvas.height = 40;
  // 第一次：還在讀這張照片的 EXIF，不畫半成品。
  assert.equal(crop.renderCard(photo, params, canvas), false);
  assert.equal(crop.orientationPending(photo), true);
  await new Promise(resolve => { photo.addEventListener('dmis-orientation', resolve); });
  calls.length = 0;
  assert.equal(crop.renderCard(photo, params, canvas), true);
  assert.deepEqual(calls[0], ['setTransform', 0, 1, -1, 0, 300, 0]);
  // 轉正後 300×400 的框，原始像素以 400×300（寬高對調）畫進去。
  assert.deepEqual(calls[1], ['drawImage', 'photo', 0, 0, 400, 300]);
  assert.deepEqual(calls[2], ['setTransform', 1, 0, 0, 1, 0, 0]);
});
