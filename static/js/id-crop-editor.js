// 證件裁切／旋轉（T-190 方案 A）：卡片預覽與調整視窗。
// 偵測在伺服器（services/id_card_crop.py）；這裡只依參數把原圖透視校正成卡片、讓使用者拖四角與換上緣。
// 參數格式與伺服器相同：{v, corners[[x,y]×4]（0–1）, turn, src_w, src_h, mode, by_ocr}。
(() => {
  "use strict";
  const CARD_RATIO = 85.6 / 54;
  const SOURCE_MAX = 2000;  // 預覽用的原圖最長邊，足夠清楚又不卡
  const CORNER_LABELS = ["左上角", "右上角", "右下角", "左下角"];
  const sourceCache = new WeakMap();

  // ---------- 透視轉換 ----------
  // 解 8 元一次方程：把卡片座標 (u,v) 對應到原圖座標 (x,y)。
  function homography(from, to) {
    const a = [];
    const b = [];
    for (let i = 0; i < 4; i += 1) {
      const [u, v] = from[i];
      const [x, y] = to[i];
      a.push([u, v, 1, 0, 0, 0, -u * x, -v * x]); b.push(x);
      a.push([0, 0, 0, u, v, 1, -u * y, -v * y]); b.push(y);
    }
    for (let col = 0; col < 8; col += 1) {
      let pivot = col;
      for (let row = col + 1; row < 8; row += 1) if (Math.abs(a[row][col]) > Math.abs(a[pivot][col])) pivot = row;
      if (Math.abs(a[pivot][col]) < 1e-12) return null;
      [a[col], a[pivot]] = [a[pivot], a[col]];
      [b[col], b[pivot]] = [b[pivot], b[col]];
      for (let row = 0; row < 8; row += 1) {
        if (row === col) continue;
        const factor = a[row][col] / a[col][col];
        if (!factor) continue;
        for (let k = col; k < 8; k += 1) a[row][k] -= factor * a[col][k];
        b[row] -= factor * b[col];
      }
    }
    return b.map((value, index) => value / a[index][index]);
  }

  // ---------- EXIF 方向（T-253，使用者 2026-11-20「圖片會異常扭曲，造成辨識出問題」） ----------
  // iPhone 相機當場拍的照片是橫的像素＋EXIF 方向 6／8。若瀏覽器回報的 naturalWidth/Height 已轉正，
  // 畫到 canvas 時卻用沒轉的像素，原圖會被擠進轉正後的框裡，卡片就拉伸變形。
  // 用一張 2×1（左黑右白）、方向 6 的小圖實測這個瀏覽器：只有「尺寸已轉正、canvas 沒轉」時才自己依 EXIF 轉，
  // 其他情況（目前 Chromium 系列實測 canvas 已轉正）照舊交給瀏覽器，行為不變。
  const ORIENTATION_PROBE = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/4QAiRXhpZgAATU0AKgAAAAgAAQESAAMAAAABAAYAAAAAAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAALCAABAAIBAREA/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEBAAA/AP6+f+CTv/KLL/gmn/2YB+xv/wCs6/Dmv//Z";
  let canvasMode = typeof Image === "undefined" || typeof window === "undefined" ? "auto" : "unknown";
  const orientationWaiters = new Set();

  // JPEG 檔頭的 EXIF 方向（1–8）；不是 JPEG、沒有 EXIF 或讀不到都回 1。
  function exifOrientation(buffer) {
    const view = buffer instanceof DataView ? buffer : new DataView(buffer.buffer ? buffer.buffer : buffer, buffer.byteOffset || 0, buffer.byteLength);
    if (view.byteLength < 4 || view.getUint16(0) !== 0xFFD8) return 1;
    let offset = 2;
    while (offset + 4 <= view.byteLength) {
      const marker = view.getUint16(offset);
      if ((marker & 0xFF00) !== 0xFF00 || marker === 0xFFDA) return 1;
      const length = view.getUint16(offset + 2);
      if (marker === 0xFFE1 && offset + 10 <= view.byteLength && view.getUint32(offset + 4) === 0x45786966 && view.getUint16(offset + 8) === 0) {
        const tiff = offset + 10;
        if (tiff + 8 > view.byteLength) return 1;
        const little = view.getUint16(tiff) === 0x4949;
        const ifd = tiff + view.getUint32(tiff + 4, little);
        if (ifd + 2 > view.byteLength) return 1;
        const count = view.getUint16(ifd, little);
        for (let i = 0; i < count; i += 1) {
          const entry = ifd + 2 + i * 12;
          if (entry + 12 > view.byteLength) return 1;
          if (view.getUint16(entry, little) === 0x0112) {
            const value = view.getUint16(entry + 8, little);
            return value >= 1 && value <= 8 ? value : 1;
          }
        }
        return 1;
      }
      offset += 2 + length;
    }
    return 1;
  }

  // 實測小圖的結果：naturalWidth/Height 是 1×2 表示 <img> 已轉正；上下兩點明顯不同表示 canvas 也轉了。
  function classifyProbe(naturalWidth, naturalHeight, top, bottom) {
    if (naturalWidth !== 1 || naturalHeight !== 2) return "legacy";  // 連 <img> 都沒轉：尺寸會和伺服器不符，卡片本來就不顯示
    return Math.abs(top - bottom) > 64 ? "auto" : "manual";
  }

  // 把原始（未轉正）像素畫進轉正後 width×height 的 canvas 要用的轉換矩陣。
  function orientationMatrix(orientation, width, height) {
    switch (orientation) {
      case 2: return [-1, 0, 0, 1, width, 0];
      case 3: return [-1, 0, 0, -1, width, height];
      case 4: return [1, 0, 0, -1, 0, height];
      case 5: return [0, 1, 1, 0, 0, 0];
      case 6: return [0, 1, -1, 0, width, 0];
      case 7: return [0, -1, -1, 0, width, height];
      case 8: return [0, -1, 1, 0, 0, height];
      default: return [1, 0, 0, 1, 0, 0];
    }
  }

  function wakeOrientationWaiters() {
    orientationWaiters.forEach(image => image.dispatchEvent(new Event("dmis-orientation")));
    orientationWaiters.clear();
  }

  function probeCanvasOrientation() {
    if (canvasMode !== "unknown") return;
    const probe = new Image();
    probe.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = probe.naturalWidth;
        canvas.height = probe.naturalHeight;
        const context = canvas.getContext("2d", {willReadFrequently: true});
        context.drawImage(probe, 0, 0, canvas.width, canvas.height);
        const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
        canvasMode = classifyProbe(probe.naturalWidth, probe.naturalHeight, data[0], data[data.length - 4]);
      } catch (_) {
        canvasMode = "auto";
      }
      wakeOrientationWaiters();
    };
    probe.onerror = () => { canvasMode = "auto"; wakeOrientationWaiters(); };
    probe.src = ORIENTATION_PROBE;
  }
  if (canvasMode === "unknown") probeCanvasOrientation();

  // 這張圖要不要自己轉、轉幾度；還在確認時回傳 null，確認後對圖片發 dmis-orientation 事件，呼叫端再畫一次。
  function orientationFor(image) {
    if (canvasMode === "unknown") { orientationWaiters.add(image); return null; }
    if (canvasMode !== "manual") return 1;
    if (image.dataset.exifSrc === image.currentSrc) return Number(image.dataset.exifOrientation) || 1;
    if (!orientationWaiters.has(image)) {
      orientationWaiters.add(image);
      const src = image.currentSrc;
      fetch(src).then(response => response.arrayBuffer()).then(buffer => exifOrientation(buffer)).catch(() => 1).then(value => {
        if (image.currentSrc === src) {
          image.dataset.exifSrc = src;
          image.dataset.exifOrientation = String(value);
        }
        orientationWaiters.delete(image);
        image.dispatchEvent(new Event("dmis-orientation"));
      });
    }
    return null;
  }

  // 原圖快照（縮到 SOURCE_MAX）。圖片還沒下載完（例如草稿自動儲存後預覽改載伺服器網址，
  // 尺寸已知但 complete 為 false）時 drawImage 畫不出東西，不拍快照也不快取，回傳 null（T-207）。
  function sourceOf(image) {
    if (!image?.complete || !image.naturalWidth) return null;
    const orientation = orientationFor(image);
    if (orientation === null) return null;
    const key = `${image.currentSrc}#${orientation}`;
    const cached = sourceCache.get(image);
    if (cached && cached.src === key) return cached;
    const scale = Math.min(1, SOURCE_MAX / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = canvas.getContext("2d", {willReadFrequently: true});
    if (orientation > 1) {
      // 這個瀏覽器的 canvas 用的是沒轉正的像素：轉換後再畫，寬高 5–8 要對調。
      context.setTransform(...orientationMatrix(orientation, canvas.width, canvas.height));
      const swap = orientation >= 5;
      context.drawImage(image, 0, 0, swap ? canvas.height : canvas.width, swap ? canvas.width : canvas.height);
      context.setTransform(1, 0, 0, 1, 0, 0);
    } else {
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
    }
    const entry = {src: key, canvas, data: context.getImageData(0, 0, canvas.width, canvas.height)};
    sourceCache.set(image, entry);
    return entry;
  }

  // 依參數把原圖像素（RGBA，sw×sh）透視校正成 width×height 的卡片像素（雙線性取樣）。
  function warpPixels(pixels, sw, sh, params, width, height) {
    const corners = params.corners.map(([x, y]) => [x * sw, y * sh]);
    const quad = [0, 1, 2, 3].map(index => corners[(index + params.turn) % 4]);
    const h = homography([[0, 0], [width, 0], [width, height], [0, height]], quad);
    if (!h) return null;
    const out = new Uint8ClampedArray(width * height * 4);
    for (let v = 0; v < height; v += 1) {
      for (let u = 0; u < width; u += 1) {
        const w = h[6] * (u + 0.5) + h[7] * (v + 0.5) + 1;
        let x = (h[0] * (u + 0.5) + h[1] * (v + 0.5) + h[2]) / w - 0.5;
        let y = (h[3] * (u + 0.5) + h[4] * (v + 0.5) + h[5]) / w - 0.5;
        x = Math.min(Math.max(x, 0), Math.max(sw - 1.001, 0));
        y = Math.min(Math.max(y, 0), Math.max(sh - 1.001, 0));
        const x0 = Math.floor(x);
        const y0 = Math.floor(y);
        const x1 = Math.min(x0 + 1, sw - 1);
        const y1 = Math.min(y0 + 1, sh - 1);
        const fx = x - x0;
        const fy = y - y0;
        const i00 = (y0 * sw + x0) * 4;
        const i10 = (y0 * sw + x1) * 4;
        const i01 = (y1 * sw + x0) * 4;
        const i11 = (y1 * sw + x1) * 4;
        const o = (v * width + u) * 4;
        for (let c = 0; c < 3; c += 1) {
          const top = pixels[i00 + c] + (pixels[i10 + c] - pixels[i00 + c]) * fx;
          const bottom = pixels[i01 + c] + (pixels[i11 + c] - pixels[i01 + c]) * fx;
          out[o + c] = top + (bottom - top) * fy;
        }
        out[o + 3] = 255;
      }
    }
    return out;
  }

  // ---------- 亮度／清晰度（T-220，與伺服器 id_card_crop.adjust 同算法，照身分證排版工具） ----------
  const MIN_BRIGHTNESS = -50;
  const MAX_BRIGHTNESS = 50;
  const MAX_SHARPNESS = 100;
  const CROP_WIDTH = 1012;
  const clampInt = (value, low, high) => Math.min(Math.max(Math.round(Number(value) || 0), low), high);

  // L 通道的 gamma 查表：+50 → 中間調 128 變 172；-50 → 77。黑白兩端不動。
  function brightnessTable(brightness) {
    const gamma = 2 ** (-brightness / 50 * 0.8);
    return Array.from({length: 256}, (_, i) => Math.min(Math.max(Math.round(255 * (i / 255) ** gamma), 0), 255));
  }

  // sRGB ↔ CIE Lab（D65，常數同 OpenCV 8 位元轉換），只改 L，色相不變。
  const LINEAR = Array.from({length: 256}, (_, i) => { const c = i / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
  const XN = 0.950456;
  const ZN = 1.088754;
  const labF = t => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const labFInverse = f => (f > 0.206893 ? f * f * f : (f - 16 / 116) / 7.787);
  const toSrgb = v => 255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * Math.max(v, 0) ** (1 / 2.4) - 0.055);

  function brighten(pixels, brightness) {
    const table = brightnessTable(brightness);
    for (let i = 0; i < pixels.length; i += 4) {
      const r = LINEAR[pixels[i]];
      const g = LINEAR[pixels[i + 1]];
      const b = LINEAR[pixels[i + 2]];
      const fx = labF((0.412453 * r + 0.357580 * g + 0.180423 * b) / XN);
      const y = 0.212671 * r + 0.715160 * g + 0.072169 * b;
      const fy = labF(y);
      const fz = labF((0.019334 * r + 0.119193 * g + 0.950227 * b) / ZN);
      const lightness = y > 0.008856 ? 116 * fy - 16 : 903.3 * y;
      const shifted = table[Math.min(Math.max(Math.round(lightness * 255 / 100), 0), 255)] * 100 / 255;
      const ny = shifted > 7.9996 ? ((shifted + 16) / 116) ** 3 : shifted / 903.3;
      const nfy = shifted > 7.9996 ? (shifted + 16) / 116 : 7.787 * ny + 16 / 116;
      const x = labFInverse(nfy + (fx - fy)) * XN;
      const z = labFInverse(nfy - (fy - fz)) * ZN;
      pixels[i] = toSrgb(3.240479 * x - 1.53715 * ny - 0.498535 * z);
      pixels[i + 1] = toSrgb(-0.969256 * x + 1.875991 * ny + 0.041556 * z);
      pixels[i + 2] = toSrgb(0.055648 * x - 0.204043 * ny + 1.057311 * z);
    }
  }

  // unsharp mask：src + amount × (src − GaussianBlur(src))；半徑依圖寬換算，預覽和 1012 px 輸出看起來一致。
  function sharpen(pixels, width, height, sharpness) {
    const sigma = Math.max(0.5, 1.4 * width / CROP_WIDTH);
    const amount = sharpness / 100 * 1.5;
    const radius = (Math.round(sigma * 3 * 2 + 1) | 1) >> 1;
    const kernel = Array.from({length: radius * 2 + 1}, (_, k) => Math.exp(-((k - radius) ** 2) / (2 * sigma * sigma)));
    const total = kernel.reduce((sum, value) => sum + value, 0);
    for (let k = 0; k < kernel.length; k += 1) kernel[k] /= total;
    const reflect = (index, size) => {  // OpenCV 預設邊界 BORDER_REFLECT_101
      if (size === 1) return 0;
      let i = index;
      while (i < 0 || i >= size) i = i < 0 ? -i : 2 * size - 2 - i;
      return i;
    };
    const pass = (input, horizontal) => {
      const output = new Float32Array(input.length);
      for (let y = 0; y < height; y += 1) {
        for (let x = 0; x < width; x += 1) {
          for (let c = 0; c < 3; c += 1) {
            let sum = 0;
            for (let k = -radius; k <= radius; k += 1) {
              const sx = horizontal ? reflect(x + k, width) : x;
              const sy = horizontal ? y : reflect(y + k, height);
              sum += input[(sy * width + sx) * 4 + c] * kernel[k + radius];
            }
            output[(y * width + x) * 4 + c] = sum;
          }
        }
      }
      return output;
    };
    const blur = pass(pass(pixels, true), false);
    for (let i = 0; i < pixels.length; i += 4) {
      for (let c = 0; c < 3; c += 1) pixels[i + c] = pixels[i + c] * (1 + amount) - Math.round(blur[i + c]) * amount;
    }
  }

  // RGBA 像素（Uint8ClampedArray）原地套用亮度與清晰度；兩者都是 0 時不動。
  function adjustPixels(pixels, width, height, brightness = 0, sharpness = 0) {
    const b = clampInt(brightness, MIN_BRIGHTNESS, MAX_BRIGHTNESS);
    const s = clampInt(sharpness, 0, MAX_SHARPNESS);
    if (b) brighten(pixels, b);
    if (s) sharpen(pixels, width, height, s);
    return pixels;
  }

  // 依參數把原圖（<img>，需已載入）畫成卡片到 canvas；canvas 大小由呼叫端決定。
  function renderCard(image, params, canvas) {
    const entry = params ? sourceOf(image) : null;
    if (!entry) return false;
    const {data, canvas: source} = entry;
    const pixels = warpPixels(data.data, source.width, source.height, params, canvas.width, canvas.height);
    if (!pixels) return false;
    adjustPixels(pixels, canvas.width, canvas.height, params.brightness, params.sharpness);
    const context = canvas.getContext("2d");
    const output = context.createImageData(canvas.width, canvas.height);
    output.data.set(pixels);
    context.putImageData(output, 0, 0);
    return true;
  }

  function parse(value) {
    if (!value) return null;
    try {
      const params = typeof value === "string" ? JSON.parse(value) : value;
      return params && params.v === 1 && Array.isArray(params.corners) && params.corners.length === 4 ? params : null;
    } catch (_) {
      return null;
    }
  }

  function fullParams(image, mode = "full") {
    const width = image.naturalWidth;
    const height = image.naturalHeight;
    return {v: 1, corners: [[0, 0], [1, 0], [1, 1], [0, 1]], turn: height > width ? 3 : 0,
            src_w: width, src_h: height, mode, by_ocr: false};
  }

  // 卡片用哪份參數（T-194）：已存的（使用者調整或辨識帶回）優先，沒有就用自動偵測的結果；
  // 有照片又兩者都沒有、也沒在偵測中，就要馬上自動偵測，不必等正反面都上傳。
  function cardState({saved, auto, hasPhoto, pending}) {
    const params = parse(saved) || parse(auto);
    return {params, detect: !params && Boolean(hasPhoto) && !pending};
  }

  // 車主類型換了證件規則（本國↔居留者，T-198）時這一面怎麼處理：使用者手動調整的保留；
  // 已存的自動偵測參數重算後存回；只顯示、還沒存的自動偵測結果重算。
  function recropPlan(saved) {
    const params = parse(saved);
    if (params?.mode === "manual") return "keep";
    return params ? "redetect-save" : "redetect";
  }

  // 卡片上的標示：自動轉正幾度、手動調整、整張。
  // 自動偵測沒把握（T-200）：伺服器判斷並存在參數裡；手動調整或按過「套用」就不再提醒。
  function needsReview(params) {
    return Boolean(params?.needs_review) && params.mode !== "manual";
  }

  // 訂單頁證件卡片預覽怎麼畫（T-262）：只有自動偵測失敗、自動改用整張照片（mode=full 且還沒確認）時，
  // 照原照片的比例、不轉向；使用者在調整視窗選「使用整張圖片」並套用的（needs_review 已清除），
  // 照使用者選的轉向畫成卡片比例，和調整視窗、列印一致。
  function previewShape(params) {
    if (params?.mode === "full" && needsReview(params)) return {whole: true, params: {...params, turn: 0}};
    return {whole: false, params};
  }

  function describe(params) {
    if (!params) return "";
    if (needsReview(params)) return "建議確認裁切";
    if (params.mode === "manual") return "已手動調整";
    if (params.mode === "full") return "使用整張圖片";
    if (params.turn === 2) return "已自動轉正 180°";
    if (params.turn === 1 || params.turn === 3) return "已自動轉正 90°";
    return "已自動裁切";
  }

  // ---------- 調整視窗 ----------
  let dialog = null;
  let state = null;

  function buildDialog() {
    dialog = document.createElement("dialog");
    dialog.className = "theme-dialog id-crop-dialog";
    dialog.setAttribute("aria-labelledby", "id-crop-title");
    dialog.innerHTML = `
      <div class="id-crop-dialog__frame">
        <header class="theme-dialog__header">
          <div>
            <h2 id="id-crop-title" data-crop-title>調整證件照片</h2>
            <p>拖曳四個角對齊卡片邊緣；標「上緣」的那一邊會成為卡片上方。</p>
          </div>
          <button type="button" class="theme-dialog__close" data-crop-cancel aria-label="關閉，不套用">×</button>
        </header>
        <div class="id-crop-dialog__body">
          <div class="id-crop-stage" data-crop-stage>
            <div class="id-crop-stage__photo" data-crop-photo>
              <canvas data-crop-canvas aria-hidden="true"></canvas>
              <svg class="id-crop-stage__overlay" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">
                <polygon data-crop-shade fill-rule="evenodd"></polygon>
                <polygon data-crop-quad></polygon>
                <line data-crop-top></line>
              </svg>
              <span class="id-crop-stage__top" data-crop-top-label>上緣</span>
              ${CORNER_LABELS.map((label, index) => `<button type="button" class="id-crop-handle" data-crop-handle="${index}" aria-label="${label}，可拖曳或用方向鍵微調"></button>`).join("")}
            </div>
            <span class="id-crop-stage__tag">原始照片</span>
            <canvas class="id-crop-loupe" data-crop-loupe width="240" height="240" hidden aria-hidden="true"></canvas>
          </div>
          <div class="id-crop-side">
            <section class="id-crop-group">
              <h3>裁切後預覽</h3>
              <canvas class="id-crop-preview" data-crop-preview aria-label="裁切後預覽" role="img"></canvas>
              <small>輸出為身分證實際比例 85.6 × 54 mm</small>
            </section>
            <section class="id-crop-group">
              <h3>裁切範圍</h3>
              <div class="id-crop-buttons">
                <button type="button" class="button ghost" data-crop-detect>自動偵測</button>
                <button type="button" class="button ghost" data-crop-full>使用整張圖片</button>
              </div>
            </section>
            <section class="id-crop-group">
              <h3>方向</h3>
              <div class="id-crop-buttons">
                <button type="button" class="button ghost id-crop-buttons__wide" data-crop-turn="2"><span aria-hidden="true">⇅</span> 轉 180°（上下顛倒時）</button>
                <button type="button" class="button ghost" data-crop-turn="1"><span aria-hidden="true">↺</span> 向左轉 90°</button>
                <button type="button" class="button ghost" data-crop-turn="3"><span aria-hidden="true">↻</span> 向右轉 90°</button>
              </div>
            </section>
            <section class="id-crop-group">
              <h3>影像</h3>
              <div class="id-crop-slider">
                <label for="id-crop-brightness">亮度</label>
                <input type="range" id="id-crop-brightness" min="${MIN_BRIGHTNESS}" max="${MAX_BRIGHTNESS}" step="1" value="0" data-crop-adjust="brightness">
                <output for="id-crop-brightness" data-crop-adjust-value="brightness">0</output>
              </div>
              <div class="id-crop-slider">
                <label for="id-crop-sharpness">清晰度</label>
                <input type="range" id="id-crop-sharpness" min="0" max="${MAX_SHARPNESS}" step="1" value="0" data-crop-adjust="sharpness">
                <output for="id-crop-sharpness" data-crop-adjust-value="sharpness">0</output>
              </div>
              <div class="id-crop-buttons">
                <button type="button" class="button ghost id-crop-buttons__wide" data-crop-adjust-reset>亮度與清晰度恢復原樣</button>
              </div>
            </section>
            <p class="id-crop-status" data-crop-status role="status" aria-live="polite"></p>
            <p class="id-crop-keys">點選一個角後可用方向鍵微調，Shift＋方向鍵一次移動較多。</p>
          </div>
        </div>
        <footer class="theme-dialog__footer">
          <small>只改照片的顯示範圍，原始照片會保留</small>
          <div class="id-crop-dialog__actions">
            <button type="button" class="button ghost" data-crop-cancel>取消</button>
            <button type="button" class="button secondary" data-crop-apply>套用</button>
            <button type="button" class="button primary" data-crop-apply-ocr>套用並重新辨識</button>
          </div>
        </footer>
      </div>`;
    document.body.append(dialog);
    dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
    dialog.addEventListener("click", event => {
      if (event.target === dialog) close();
      if (event.target.closest("[data-crop-cancel]")) close();
      if (event.target.closest("[data-crop-apply]")) apply(false);
      if (event.target.closest("[data-crop-apply-ocr]")) apply(true);
      if (event.target.closest("[data-crop-full]")) {
        update(keepAdjust({...fullParams(state.image), corners: [[0, 0], [1, 0], [1, 1], [0, 1]]}));
        status("已改用整張圖片。");
      }
      const turnButton = event.target.closest("[data-crop-turn]");
      if (turnButton) {
        update({...state.params, turn: (state.params.turn + Number(turnButton.dataset.cropTurn)) % 4, mode: "manual", by_ocr: false});
        status({1: "已向左轉 90°。", 2: "已轉 180°。", 3: "已向右轉 90°。"}[turnButton.dataset.cropTurn]);
      }
      if (event.target.closest("[data-crop-detect]")) detect();
      if (event.target.closest("[data-crop-adjust-reset]")) {
        update({...state.params, brightness: 0, sharpness: 0});
        syncSliders();
        status("亮度與清晰度已恢復原樣。");
      }
    });
    // 拖滑桿即時更新預覽；亮度與清晰度不改裁切範圍，所以不把參數改成「手動調整」。
    dialog.addEventListener("input", event => {
      const slider = event.target.closest("[data-crop-adjust]");
      if (!slider) return;
      update({...state.params, [slider.dataset.cropAdjust]: Number(slider.value)});
      syncSliders();
    });
    dialog.querySelectorAll("[data-crop-handle]").forEach(handle => {
      handle.addEventListener("pointerdown", startDrag);
      handle.addEventListener("keydown", nudge);
    });
    new ResizeObserver(() => { if (dialog.open) layout(); }).observe(dialog.querySelector("[data-crop-stage]"));
  }

  function status(message, isError = false) {
    const node = dialog.querySelector("[data-crop-status]");
    node.textContent = message;
    node.classList.toggle("is-error", isError);
  }

  function layout() {
    const stage = dialog.querySelector("[data-crop-stage]");
    const photo = dialog.querySelector("[data-crop-photo]");
    const canvas = dialog.querySelector("[data-crop-canvas]");
    const image = state.image;
    const source = sourceOf(image);
    if (!source) return;  // 圖片下載完會再觸發 load（見 open），屆時重排
    const pad = 24;  // 留給把手超出照片邊緣的空間
    // 照片區高度跟著照片比例，橫拍照片不留一大片空白；上限約半個畫面高。
    const width = stage.getBoundingClientRect().width;
    const ideal = (width - pad * 2) * image.naturalHeight / image.naturalWidth + pad * 2;
    const limit = Math.min(window.innerHeight * 0.58, 560);
    stage.style.height = `${Math.round(Math.max(240, Math.min(limit, ideal)))}px`;
    const box = stage.getBoundingClientRect();
    const scale = Math.min((box.width - pad * 2) / image.naturalWidth, (box.height - pad * 2) / image.naturalHeight);
    const photoWidth = Math.max(1, Math.floor(image.naturalWidth * scale));
    const photoHeight = Math.max(1, Math.floor(image.naturalHeight * scale));
    photo.style.width = `${photoWidth}px`;
    photo.style.height = `${photoHeight}px`;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(photoWidth * ratio);
    canvas.height = Math.round(photoHeight * ratio);
    canvas.getContext("2d").drawImage(source.canvas, 0, 0, canvas.width, canvas.height);
    const preview = dialog.querySelector("[data-crop-preview]");
    const previewWidth = Math.max(1, Math.round(preview.getBoundingClientRect().width * ratio));
    preview.width = previewWidth;
    preview.height = Math.round(previewWidth / CARD_RATIO);
    draw();
  }

  let previewFrame = 0;
  function draw() {
    const {corners, turn} = state.params;
    const points = corners.map(([x, y]) => `${x * 1000},${y * 1000}`).join(" ");
    dialog.querySelector("[data-crop-quad]").setAttribute("points", points);
    dialog.querySelector("[data-crop-shade]").setAttribute("points", `0,0 1000,0 1000,1000 0,1000 0,0 ${points} ${corners[0][0] * 1000},${corners[0][1] * 1000}`);
    const [a, b] = [corners[turn], corners[(turn + 1) % 4]];
    const top = dialog.querySelector("[data-crop-top]");
    top.setAttribute("x1", a[0] * 1000); top.setAttribute("y1", a[1] * 1000);
    top.setAttribute("x2", b[0] * 1000); top.setAttribute("y2", b[1] * 1000);
    const label = dialog.querySelector("[data-crop-top-label]");
    label.style.left = `${(a[0] + b[0]) * 50}%`;
    label.style.top = `${(a[1] + b[1]) * 50}%`;
    dialog.querySelectorAll("[data-crop-handle]").forEach(handle => {
      const [x, y] = corners[Number(handle.dataset.cropHandle)];
      handle.style.left = `${x * 100}%`;
      handle.style.top = `${y * 100}%`;
    });
    // 拖曳時預覽每個畫格最多算一次。
    cancelAnimationFrame(previewFrame);
    previewFrame = requestAnimationFrame(() => {
      renderCard(state.image, state.params, dialog.querySelector("[data-crop-preview]"));
    });
  }

  function update(params) {
    state.params = params;
    draw();
  }

  // 換裁切範圍（自動偵測、整張圖片）時保留目前的亮度與清晰度。
  function keepAdjust(params) {
    return {...params, brightness: state.params.brightness || 0, sharpness: state.params.sharpness || 0};
  }

  function syncSliders() {
    for (const key of ["brightness", "sharpness"]) {
      const value = Number(state.params[key]) || 0;
      dialog.querySelector(`[data-crop-adjust="${key}"]`).value = String(value);
      dialog.querySelector(`[data-crop-adjust-value="${key}"]`).textContent = key === "brightness" && value > 0 ? `+${value}` : String(value);
    }
  }

  // 存回的參數：0 不存（與伺服器 clean_params 相同），舊參數不多出欄位。
  function withAdjust(params) {
    const result = {...params};
    for (const [key, low, high] of [["brightness", MIN_BRIGHTNESS, MAX_BRIGHTNESS], ["sharpness", 0, MAX_SHARPNESS]]) {
      const value = clampInt(result[key], low, high);
      if (value) result[key] = value; else delete result[key];
    }
    return result;
  }

  function convex(corners) {
    let sign = 0;
    for (let i = 0; i < 4; i += 1) {
      const [ax, ay] = corners[i];
      const [bx, by] = corners[(i + 1) % 4];
      const [cx, cy] = corners[(i + 2) % 4];
      const cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx);
      if (Math.abs(cross) < 1e-9) return false;
      if (sign && Math.sign(cross) !== sign) return false;
      sign = Math.sign(cross);
    }
    return true;
  }

  function moveCorner(index, x, y) {
    const corners = state.params.corners.map(point => [...point]);
    corners[index] = [Math.min(Math.max(x, 0), 1), Math.min(Math.max(y, 0), 1)];
    if (!convex(corners)) return;  // 四角交叉時不移動，維持上一個合理的位置
    update({...state.params, corners, mode: "manual", by_ocr: false});
  }

  function startDrag(event) {
    const handle = event.currentTarget;
    const index = Number(handle.dataset.cropHandle);
    const photo = dialog.querySelector("[data-crop-photo]");
    handle.setPointerCapture(event.pointerId);
    handle.focus({preventScroll: true});
    event.preventDefault();
    const move = moveEvent => {
      const box = photo.getBoundingClientRect();
      moveCorner(index, (moveEvent.clientX - box.left) / box.width, (moveEvent.clientY - box.top) / box.height);
      loupe(index);
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      dialog.querySelector("[data-crop-loupe]").hidden = true;
      handle.classList.remove("is-dragging");
    };
    handle.classList.add("is-dragging");
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    handle.addEventListener("lostpointercapture", end, {once: true});
    loupe(index);
  }

  // 放大鏡：拖曳時在照片角落放大顯示游標附近，手指不會擋住要對齊的邊。
  function loupe(index) {
    const node = dialog.querySelector("[data-crop-loupe]");
    const entry = sourceOf(state.image);
    if (!entry) return;
    const {canvas: source} = entry;
    const [x, y] = state.params.corners[index];
    const zoom = 3;
    const size = node.width;
    const context = node.getContext("2d");
    const span = size / zoom;
    context.fillStyle = getComputedStyle(node).backgroundColor || "#000";
    context.fillRect(0, 0, size, size);
    context.drawImage(source, x * source.width - span / 2, y * source.height - span / 2, span, span, 0, 0, size, size);
    context.strokeStyle = getComputedStyle(node).color || "#fff";
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(size / 2, size / 2 - 18); context.lineTo(size / 2, size / 2 + 18);
    context.moveTo(size / 2 - 18, size / 2); context.lineTo(size / 2 + 18, size / 2);
    context.stroke();
    node.classList.toggle("is-right", x < 0.5);
    node.hidden = false;
  }

  function nudge(event) {
    const steps = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[event.key];
    if (!steps) return;
    event.preventDefault();
    const index = Number(event.currentTarget.dataset.cropHandle);
    const box = dialog.querySelector("[data-crop-photo]").getBoundingClientRect();
    const distance = event.shiftKey ? 10 : 1;
    const [x, y] = state.params.corners[index];
    moveCorner(index, x + steps[0] * distance / box.width, y + steps[1] * distance / box.height);
  }

  async function detect() {
    const button = dialog.querySelector("[data-crop-detect]");
    if (state.autoParams) {
      update(keepAdjust({...state.autoParams}));
      status("已套用自動偵測的範圍。");
      return;
    }
    if (!state.detect) return;
    button.disabled = true;
    status("自動偵測中…");
    try {
      const params = await state.detect();
      state.autoParams = params;
      update(keepAdjust({...params}));
      status(params.mode === "full" ? "找不到卡片邊緣，先使用整張圖片；可手動拖曳四角。" : "已套用自動偵測的範圍。");
    } catch (error) {
      status(error.message || "自動偵測失敗，請手動拖曳四角。", true);
    } finally {
      button.disabled = false;
    }
  }

  function apply(rerun) {
    // 按「套用」就是使用者確認過這個範圍：改為手動（選了整張圖片的保留 full），提醒消失（T-200）。
    const params = withAdjust({
      ...state.params, src_w: state.image.naturalWidth, src_h: state.image.naturalHeight,
      mode: state.params.mode === "full" ? "full" : "manual", needs_review: false, by_ocr: false,
    });
    const callback = state.onApply;
    close();
    callback(params, {rerun});
  }

  function close() {
    if (!dialog?.open) return;
    dialog.close();
    state?.image?.removeEventListener?.("load", state.onImageLoad);
    state?.image?.removeEventListener?.("dmis-orientation", state.onImageLoad);
    document.documentElement.classList.remove("has-id-crop-dialog");
    state?.returnFocus?.focus?.({preventScroll: true});
    state = null;
  }

  // options：{image: 已載入的原圖 <img>, params, title, autoParams, detect(): Promise<params>, onApply(params, {rerun}), canRerun, returnFocus}
  function open(options) {
    if (!dialog) buildDialog();
    const image = options.image;
    const params = parse(options.params);
    const valid = params && params.src_w === image.naturalWidth && params.src_h === image.naturalHeight;
    state = {
      ...options,
      params: valid ? params : (parse(options.autoParams) || fullParams(image, "full")),
      autoParams: parse(options.autoParams),
      // 視窗開著時預覽圖可能換網址重新下載（草稿自動儲存）；下載完重畫原圖與預覽。
      onImageLoad: () => { if (dialog.open) layout(); },
    };
    image.addEventListener("load", state.onImageLoad);
    image.addEventListener("dmis-orientation", state.onImageLoad);
    dialog.querySelector("[data-crop-title]").textContent = options.title || "調整證件照片";
    dialog.querySelector("[data-crop-apply-ocr]").hidden = options.canRerun === false;
    status("");
    syncSliders();
    dialog.showModal();
    document.documentElement.classList.add("has-id-crop-dialog");
    layout();
    dialog.querySelector(`[data-crop-handle="${state.params.turn}"]`).focus({preventScroll: true});
  }

  const api = {open, renderCard, parse, describe, fullParams, homography, warpPixels, adjustPixels, brightnessTable, cardState, recropPlan, needsReview, previewShape,
               exifOrientation, classifyProbe, orientationMatrix, canvasOrientationMode: () => canvasMode,
               orientationPending: image => orientationWaiters.has(image)};
  if (typeof window !== "undefined") window.dmisIdCrop = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
