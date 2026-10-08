(() => {
  // 「要匯入的頁籤」只適用營運 Excel；選通路名冊時隱藏，避免誤以為有作用。
  const form = document.querySelector(".import-upload-form");
  const type = form?.querySelector('[name="import_type"]');
  const sheets = form?.querySelector("[data-import-sheets]");
  if (!type || !sheets) return;
  const sync = () => { sheets.hidden = type.value !== "operations"; };
  type.addEventListener("change", sync);
  sync();
})();
