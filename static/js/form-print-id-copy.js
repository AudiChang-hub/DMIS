// 套表列印預覽（T-190 2.13.0）：身分證影本頁點證件 → 開同一個調整視窗 → 存回訂單 → 只重畫這一頁。
// 與 form-print.js 分開，只靠預覽內容的 data 屬性運作，不改列印清單與預覽本身的行為。
(() => {
  "use strict";
  const tray = document.querySelector("form[data-preview-url]");
  if (!tray) return;
  const csrf = () => document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  const summary = () => document.querySelector("[data-preview-summary]");

  const loadImage = src => new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("讀不到原始照片，請重新整理後再試。"));
    image.src = src;
  });

  async function postJson(url, fields) {
    const payload = new FormData();
    Object.entries(fields).forEach(([name, value]) => payload.append(name, value));
    const response = await fetch(url, {
      method: "POST", body: payload, credentials: "same-origin",
      headers: {"X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest"},
    });
    const data = await response.json().catch(() => ({ok: false}));
    if (!response.ok || !data.ok) throw new Error(data.error || "儲存失敗，請再試一次。");
    return data;
  }

  // 只重新產生這一頁身分證影本（同一頁的各組與備註照舊，T-208），換掉畫面上那一頁與左側縮圖，捲動位置不變。
  async function refreshPage(button) {
    const page = button.closest("[data-page]");
    const payload = new FormData();
    payload.append("csrfmiddlewaretoken", csrf());
    let jobs = [];
    try { jobs = JSON.parse(page?.dataset.idJobs || "[]"); } catch (_) { jobs = []; }
    if (!jobs.length) jobs = [{order: button.dataset.order, note: null}];
    jobs.forEach(job => {
      payload.append("job", `${job.order}:id_copy`);
      if (job.note !== null && job.note !== undefined) payload.append(`idnote_${job.order}`, job.note);
    });
    const response = await fetch(tray.dataset.previewUrl, {
      method: "POST", body: payload, credentials: "same-origin", headers: {"X-Requested-With": "XMLHttpRequest"},
    });
    if (!response.ok) throw new Error("預覽更新失敗，請重新開啟預覽。");
    const fresh = new DOMParser().parseFromString(await response.text(), "text/html").querySelector("[data-page] .print-preview__sheet");
    if (!fresh || !page) throw new Error("預覽更新失敗，請重新開啟預覽。");
    const pages = [...document.querySelectorAll("[data-preview-content] [data-page]")];
    page.querySelector(".print-preview__sheet").replaceWith(document.importNode(fresh, true));
    const thumb = document.querySelectorAll("[data-preview-rail] img")[pages.indexOf(page)];
    if (thumb) thumb.src = fresh.querySelector("img").src;
    page.querySelector(`[data-id-copy-card][data-side="${button.dataset.side}"]`)?.focus({preventScroll: true});
  }

  async function open(button) {
    if (!window.dmisIdCrop || button.classList.contains("is-busy")) return;
    const label = button.querySelector("span");
    const original = label.textContent;
    button.classList.add("is-busy");
    label.textContent = "載入原始照片…";
    let image;
    try {
      image = await loadImage(button.dataset.src);
    } catch (error) {
      if (summary()) summary().textContent = error.message;
      return;
    } finally {
      button.classList.remove("is-busy");
      label.textContent = original;
    }
    const saved = button.dataset.saved === "1";
    window.dmisIdCrop.open({
      image,
      params: button.dataset.crop,
      autoParams: saved ? null : button.dataset.crop,
      title: `調整${button.dataset.label}`,
      canRerun: false,
      returnFocus: button,
      detect: async () => (await postJson(tray.dataset.idCropDetectUrl, {
        side: button.dataset.side, source: `order:${button.dataset.order}`, document_type: button.dataset.documentType,
      })).crop,
      onApply: async params => {
        button.classList.add("is-busy");
        label.textContent = "儲存並更新預覽…";
        try {
          await postJson(button.dataset.saveUrl || tray.dataset.idCropSaveUrl.replace("/0/", `/${button.dataset.order}/`), {
            side: button.dataset.side, crop: JSON.stringify(params),
          });
          await refreshPage(button);
          if (summary()) summary().textContent = `已更新${button.dataset.label}，訂單裡的照片裁切也一起更新。`;
        } catch (error) {
          button.classList.remove("is-busy");
          label.textContent = original;
          if (summary()) summary().textContent = error.message;
        }
      },
    });
  }

  document.addEventListener("click", event => {
    const button = event.target.closest("[data-id-copy-card]");
    if (button) open(button);
  });
})();
