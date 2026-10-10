// 平板手寫簽名：指標事件繪製，送出前轉成 PNG 放入隱藏欄位。
(() => {
  const pad = document.querySelector("[data-signature-pad]");
  const form = document.querySelector("[data-signing-form]");
  if (!pad || !form) return;
  const canvas = pad.querySelector("canvas");
  const hint = pad.querySelector("[data-signature-hint]");
  const value = form.querySelector("[data-signature-value]");
  const context = canvas.getContext("2d");
  let drawing = false;
  let inked = false;
  let last = null;

  const resize = () => {
    const ratio = Math.max(window.devicePixelRatio || 1, 1);
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = getComputedStyle(pad).color;
    context.lineWidth = 2.6;
    inked = false;
    hint.hidden = false;
  };

  const point = (event) => {
    const rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  canvas.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    canvas.setPointerCapture(event.pointerId);
    drawing = true;
    last = point(event);
    context.beginPath();
    context.arc(last.x, last.y, context.lineWidth / 2, 0, Math.PI * 2);
    context.fillStyle = context.strokeStyle;
    context.fill();
    inked = true;
    hint.hidden = true;
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!drawing) return;
    event.preventDefault();
    const events = event.getCoalescedEvents ? event.getCoalescedEvents() : [event];
    for (const item of events) {
      const next = point(item);
      context.beginPath();
      context.moveTo(last.x, last.y);
      context.lineTo(next.x, next.y);
      context.stroke();
      last = next;
    }
  });
  const stop = () => { drawing = false; last = null; };
  canvas.addEventListener("pointerup", stop);
  canvas.addEventListener("pointercancel", stop);

  form.querySelector("[data-signature-clear]").addEventListener("click", () => {
    context.clearRect(0, 0, canvas.width, canvas.height);
    inked = false;
    hint.hidden = false;
  });

  form.addEventListener("submit", (event) => {
    // 「返回修改」等不需要簽名的按鈕直接送出。
    if (event.submitter && event.submitter.hasAttribute("data-signature-skip")) return;
    if (!inked) {
      event.preventDefault();
      hint.textContent = "請先在此簽名";
      pad.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    value.value = canvas.toDataURL("image/png");
    form.querySelector("[data-signature-submit]").disabled = true;
  });

  // 旋轉或縮放會清空畫布，避免簽名被拉伸變形。
  let width = canvas.getBoundingClientRect().width;
  window.addEventListener("resize", () => {
    const next = canvas.getBoundingClientRect().width;
    if (Math.abs(next - width) > 1) { width = next; resize(); }
  });
  resize();
})();
