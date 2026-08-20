(() => {
  const editor = document.querySelector("[data-brand-logo-editor]");
  if (!editor) return;
  const form = editor.closest("form");
  const input = form.querySelector("#id_logo");
  const workspace = editor.querySelector("[data-logo-workspace]");
  const emptyState = editor.querySelector("[data-logo-empty]");
  const canvas = editor.querySelector("[data-logo-canvas]");
  const previews = [...editor.querySelectorAll("[data-logo-preview]")];
  const zoom = editor.querySelector("[data-logo-zoom]");
  const reset = editor.querySelector("[data-logo-reset]");
  const remove = editor.querySelector("[data-logo-remove]");
  const status = editor.querySelector("[data-logo-status]");
  const fields = {
    x: form.querySelector("#id_logo_crop_x"), y: form.querySelector("#id_logo_crop_y"),
    width: form.querySelector("#id_logo_crop_width"), height: form.querySelector("#id_logo_crop_height"),
    changed: form.querySelector("#id_logo_crop_changed"), remove: form.querySelector("#id_remove_logo"),
  };
  const image = new Image();
  let crop = null;
  let baseCrop = null;
  let dragging = false;
  let pointer = null;
  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
  const fullImageCrop = () => ({ x: 0, y: 0, width: 1, height: 1 });
  const readStoredCrop = () => ({ x: Number(fields.x.value), y: Number(fields.y.value), width: Number(fields.width.value), height: Number(fields.height.value) });
  const writeCrop = () => Object.entries(crop).forEach(([key, value]) => { fields[key].value = value.toFixed(6); });
  const drawInto = (target) => {
    const context = target.getContext("2d");
    context.clearRect(0, 0, target.width, target.height);
    const sourceWidth = crop.width * image.naturalWidth;
    const sourceHeight = crop.height * image.naturalHeight;
    const scale = Math.min(target.width / sourceWidth, target.height / sourceHeight);
    const renderedWidth = sourceWidth * scale;
    const renderedHeight = sourceHeight * scale;
    context.drawImage(
      image,
      crop.x * image.naturalWidth,
      crop.y * image.naturalHeight,
      sourceWidth,
      sourceHeight,
      (target.width - renderedWidth) / 2,
      (target.height - renderedHeight) / 2,
      renderedWidth,
      renderedHeight,
    );
  };
  const render = () => { if (!crop || !image.naturalWidth) return; writeCrop(); drawInto(canvas); previews.forEach(drawInto); };
  const setReady = (ready) => { workspace.classList.toggle("is-empty", !ready); emptyState.hidden = ready; };
  const applyZoom = () => {
    const factor = Number(zoom.value);
    const centerX = crop.x + crop.width / 2; const centerY = crop.y + crop.height / 2;
    const width = baseCrop.width / factor; const height = baseCrop.height / factor;
    crop = { x: clamp(centerX - width / 2, 0, 1 - width), y: clamp(centerY - height / 2, 0, 1 - height), width, height };
    fields.changed.value = "1"; render();
  };
  const loadSource = (source, useStoredCrop) => {
    image.onload = () => {
      baseCrop = fullImageCrop(); crop = useStoredCrop ? readStoredCrop() : { ...baseCrop };
      if (!crop.width || !crop.height) crop = { ...baseCrop };
      zoom.value = Math.min(4, Math.max(1, baseCrop.width / crop.width, baseCrop.height / crop.height)); fields.remove.value = "";
      setReady(true); status.textContent = input.files.length ? "新圖片待儲存" : "目前已設定"; render();
    };
    image.onerror = () => {
      status.textContent = "無法預覽，請更換圖片";
      setReady(false);
    };
    image.src = source;
  };
  input.addEventListener("change", () => { if (!input.files.length) return; loadSource(URL.createObjectURL(input.files[0]), false); fields.changed.value = "1"; });
  zoom.addEventListener("input", applyZoom);
  reset.addEventListener("click", () => { crop = { ...baseCrop }; zoom.value = "1"; fields.changed.value = "1"; render(); });
  canvas.addEventListener("pointerdown", (event) => { dragging = true; pointer = { x: event.clientX, y: event.clientY, cropX: crop.x, cropY: crop.y }; canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const rect = canvas.getBoundingClientRect();
    crop.x = clamp(pointer.cropX - ((event.clientX - pointer.x) / rect.width) * crop.width, 0, 1 - crop.width);
    crop.y = clamp(pointer.cropY - ((event.clientY - pointer.y) / rect.height) * crop.height, 0, 1 - crop.height);
    fields.changed.value = "1"; render();
  });
  const stopDragging = () => { dragging = false; };
  canvas.addEventListener("pointerup", stopDragging); canvas.addEventListener("pointercancel", stopDragging);
  remove?.addEventListener("click", () => { input.value = ""; fields.remove.value = "1"; fields.changed.value = ""; status.textContent = "儲存後移除"; setReady(false); });
  if (editor.dataset.sourceUrl) { image.crossOrigin = "same-origin"; loadSource(editor.dataset.sourceUrl, editor.dataset.hasCrop === "true"); }
})();
