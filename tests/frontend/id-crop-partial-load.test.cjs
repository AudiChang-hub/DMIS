// T-207：照片還沒下載完時（例如草稿自動儲存後預覽改載伺服器網址），裁切預覽不可留下全黑的快照。
const {test} = require('node:test');
const assert = require('node:assert/strict');

// 模擬瀏覽器畫布：drawImage 遇到還沒下載完的圖片什麼都不畫（規格行為），讀回來就是全 0。
function fakeCanvas() {
  const canvas = {width: 0, height: 0, pixels: null};
  canvas.getContext = () => ({
    drawImage(image) {
      canvas.pixels = new Uint8ClampedArray(canvas.width * canvas.height * 4);
      if (!image.complete) return;
      for (let i = 0; i < canvas.pixels.length; i += 4) canvas.pixels.set([200, 180, 160, 255], i);
    },
    getImageData(x, y, width, height) {
      return {data: canvas.pixels || new Uint8ClampedArray(width * height * 4)};
    },
    createImageData(width, height) {
      return {data: new Uint8ClampedArray(width * height * 4)};
    },
    putImageData(output) { canvas.output = output.data; },
  });
  return canvas;
}

global.document = {createElement: () => fakeCanvas()};
const {renderCard} = require('../../static/js/id-crop-editor.js');

const params = {v: 1, corners: [[0.1, 0.5], [0.9, 0.5], [0.9, 0.9], [0.1, 0.9]], turn: 3, src_w: 30, src_h: 40, mode: 'auto'};
const blackPixels = data => {
  let black = 0;
  for (let i = 0; i < data.length; i += 4) if (data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 0) black += 1;
  return black;
};

test('圖片尺寸已知但還沒下載完：不畫預覽，也不把空白快照留到下載完成後', () => {
  const image = {naturalWidth: 30, naturalHeight: 40, complete: false, currentSrc: 'https://example.test/files/draft/1/id_back'};
  const canvas = fakeCanvas();
  canvas.width = 16;
  canvas.height = 10;
  assert.equal(renderCard(image, params, canvas), false);
  assert.equal(canvas.output, undefined);

  image.complete = true;
  assert.equal(renderCard(image, params, canvas), true);
  assert.equal(blackPixels(canvas.output), 0);
});
