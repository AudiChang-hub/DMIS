// 建單精靈的附件卡（使用者 2026-11-07 T-128）：像訂單頁附件一樣，虛線區點選或拖曳選檔，選好就隨草稿上傳；
// 每個已存檔案一張卡，可「刪除」（先確認）或「替換」。檔案仍走原本的欄位與草稿儲存（_order_form_scripts.html），
// 這裡只負責畫面：草稿存好後依伺服器回傳的清單重畫卡片，刪除用原本的 _remove_intake_attachments。
(() => {
  const ROOT = "[data-intake-upload]";

  function kindsOf(root) {
    return new Set([root.dataset.kind, ...(root.dataset.alsoKinds || "").split(/\s+/).filter(Boolean)]);
  }

  function card({id, name, url, label, primary}) {
    const item = document.createElement("div");
    item.className = "intake-upload__item";
    item.dataset.intakeAttachment = id;
    const link = document.createElement("a");
    link.href = url;
    link.dataset.previewName = name;
    link.dataset.previewLabel = primary ? name : `${label}：${name}`;
    link.textContent = name;
    const actions = document.createElement("div");
    actions.className = "intake-upload__actions";
    if (primary) actions.append(button("替換", "button ghost compact", "intakeReplace"));
    actions.append(button("刪除", "button danger-outline compact", "intakeDelete"));
    item.append(link, actions);
    return item;
  }

  function button(text, className, flag) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = className;
    node.dataset[flag] = "";
    node.textContent = text;
    return node;
  }

  function pendingCard(file) {
    const item = document.createElement("div");
    item.className = "intake-upload__item is-pending";
    const name = document.createElement("span");
    name.className = "intake-upload__name";
    name.textContent = file.name;
    const state = document.createElement("small");
    state.className = "intake-upload__state";
    state.textContent = "上傳中…";
    item.append(name, state);
    return item;
  }

  function showPending(root) {
    const list = root.querySelector("[data-intake-upload-list]");
    const input = root.querySelector("[data-intake-upload-input]");
    list.querySelectorAll(".is-pending").forEach((node) => node.remove());
    Array.from(input.files || []).forEach((file) => list.append(pendingCard(file)));
  }

  function setFiles(input, files) {
    const transfer = new DataTransfer();
    Array.from(files).forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", {bubbles: true}));
  }

  function markRemoved(root, id) {
    const form = root.querySelector("[data-intake-upload-input]").form;
    if (!form || form.querySelector(`input[name="_remove_intake_attachments"][value="${id}"]`)) return;
    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = "_remove_intake_attachments";
    hidden.value = id;
    hidden.dataset.intakeRemoval = "";
    form.append(hidden);
  }

  document.addEventListener("change", (event) => {
    const input = event.target;
    if (!input.matches?.("[data-intake-upload-input]")) return;
    showPending(input.closest(ROOT));
  });

  document.addEventListener("click", (event) => {
    const root = event.target.closest?.(ROOT);
    const item = event.target.closest?.("[data-intake-attachment]");
    if (!root || !item) return;
    const name = item.querySelector("a")?.dataset.previewName || "這個檔案";
    if (event.target.closest("[data-intake-delete]")) {
      if (!window.confirm(`確定刪除「${name}」嗎？草稿存好後就無法復原。`)) return;
      markRemoved(root, item.dataset.intakeAttachment);
      item.classList.add("is-removing");
      item.querySelector(".intake-upload__actions").replaceChildren(Object.assign(document.createElement("small"), {className: "intake-upload__state", textContent: "刪除中…"}));
      // 觸發草稿儲存（訂單表單的 change 會排入自動暫存）。
      root.querySelector("[data-intake-upload-input]").form?.dispatchEvent(new Event("change", {bubbles: true}));
    } else if (event.target.closest("[data-intake-replace]")) {
      const picker = document.createElement("input");
      picker.type = "file";
      picker.accept = root.querySelector("[data-intake-upload-input]").accept;
      picker.addEventListener("change", () => {
        if (!picker.files.length) return;
        markRemoved(root, item.dataset.intakeAttachment);
        item.classList.add("is-removing");
        setFiles(root.querySelector("[data-intake-upload-input]"), picker.files);
      }, {once: true});
      picker.click();
    }
  });

  // 拖曳到虛線區：檔案放進原本的欄位，照一般選檔流程上傳。
  document.addEventListener("dragover", (event) => {
    const zone = event.target.closest?.(`${ROOT} [data-upload-dropzone]`);
    if (!zone || !Array.from(event.dataTransfer?.types || []).includes("Files")) return;
    event.preventDefault();
    zone.classList.add("is-dragover");
  });
  document.addEventListener("dragleave", (event) => {
    event.target.closest?.(`${ROOT} [data-upload-dropzone]`)?.classList.remove("is-dragover");
  });
  document.addEventListener("drop", (event) => {
    const zone = event.target.closest?.(`${ROOT} [data-upload-dropzone]`);
    if (!zone) return;
    event.preventDefault();
    zone.classList.remove("is-dragover");
    const input = zone.querySelector("[data-intake-upload-input]");
    const files = Array.from(event.dataTransfer?.files || []);
    if (files.length) setFiles(input, input.multiple ? files : files.slice(0, 1));
  });

  // 草稿存好：依伺服器清單重畫已存檔案；已傳上去的檔案清出欄位，避免下次重送。
  document.addEventListener("draft-saved", (event) => {
    const saved = event.detail?.attachments;
    if (!Array.isArray(saved)) return;
    document.querySelectorAll(ROOT).forEach((root) => {
      const kinds = kindsOf(root);
      const list = root.querySelector("[data-intake-upload-list]");
      const input = root.querySelector("[data-intake-upload-input]");
      const mine = saved.filter((item) => kinds.has(item.kind));
      const names = new Set(mine.map((item) => item.name));
      if (Array.from(input.files || []).every((file) => names.has(file.name))) input.value = "";
      list.replaceChildren(...mine.map((item) => card({...item, primary: item.kind === root.dataset.kind})));
      if (input.files?.length) showPending(root);
    });
    const ids = new Set(saved.map((item) => String(item.id)));
    document.querySelectorAll("input[data-intake-removal]").forEach((hidden) => {
      if (!ids.has(hidden.value)) hidden.remove();
    });
  });

  const init = () => document.querySelectorAll(ROOT).forEach((root) => root.classList.add("is-enhanced"));
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true});
  else init();
})();
