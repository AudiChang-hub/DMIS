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

  function sourceOf(image) {
    const cached = sourceCache.get(image);
    if (cached && cached.src === image.currentSrc) return cached;
    const scale = Math.min(1, SOURCE_MAX / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = canvas.getContext("2d", {willReadFrequently: true});
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const entry = {src: image.currentSrc, canvas, data: context.getImageData(0, 0, canvas.width, canvas.height)};
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

  // 依參數把原圖（<img>，需已載入）畫成卡片到 canvas；canvas 大小由呼叫端決定。
  function renderCard(image, params, canvas) {
    if (!image?.naturalWidth || !params) return false;
    const {data, canvas: source} = sourceOf(image);
    const pixels = warpPixels(data.data, source.width, source.height, params, canvas.width, canvas.height);
    if (!pixels) return false;
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

  // 卡片上的標示：自動轉正幾度、手動調整、整張。
  function describe(params) {
    if (!params) return "";
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
                <button type="button" class="button ghost" data-crop-turn="1"><span aria-hidden="true">↺</span> 向左轉 90°</button>
                <button type="button" class="button ghost" data-crop-turn="3"><span aria-hidden="true">↻</span> 向右轉 90°</button>
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
        update({...fullParams(state.image), corners: [[0, 0], [1, 0], [1, 1], [0, 1]]});
        status("已改用整張圖片。");
      }
      const turnButton = event.target.closest("[data-crop-turn]");
      if (turnButton) {
        update({...state.params, turn: (state.params.turn + Number(turnButton.dataset.cropTurn)) % 4, mode: "manual", by_ocr: false});
        status(turnButton.dataset.cropTurn === "1" ? "已向左轉 90°。" : "已向右轉 90°。");
      }
      if (event.target.closest("[data-crop-detect]")) detect();
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
    canvas.getContext("2d").drawImage(sourceOf(image).canvas, 0, 0, canvas.width, canvas.height);
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
    const {canvas: source} = sourceOf(state.image);
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
      update({...state.autoParams});
      status("已套用自動偵測的範圍。");
      return;
    }
    if (!state.detect) return;
    button.disabled = true;
    status("自動偵測中…");
    try {
      const params = await state.detect();
      state.autoParams = params;
      update({...params});
      status(params.mode === "full" ? "找不到卡片邊緣，先使用整張圖片；可手動拖曳四角。" : "已套用自動偵測的範圍。");
    } catch (error) {
      status(error.message || "自動偵測失敗，請手動拖曳四角。", true);
    } finally {
      button.disabled = false;
    }
  }

  function apply(rerun) {
    const params = {...state.params, src_w: state.image.naturalWidth, src_h: state.image.naturalHeight};
    const callback = state.onApply;
    close();
    callback(params, {rerun});
  }

  function close() {
    if (!dialog?.open) return;
    dialog.close();
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
    };
    dialog.querySelector("[data-crop-title]").textContent = options.title || "調整證件照片";
    dialog.querySelector("[data-crop-apply-ocr]").hidden = options.canRerun === false;
    status("");
    dialog.showModal();
    document.documentElement.classList.add("has-id-crop-dialog");
    layout();
    dialog.querySelector(`[data-crop-handle="${state.params.turn}"]`).focus({preventScroll: true});
  }

  const api = {open, renderCard, parse, describe, fullParams, homography, warpPixels, cardState};
  if (typeof window !== "undefined") window.dmisIdCrop = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
