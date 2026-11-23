// 統一撥款對帳（T-96）：輸入實際金額時即時試算差額（只預覽、不標紅，按入帳後才算）；
// 合併撥款勾選多張單（平台與分期公司都可以，T-283），各自的實際金額加總後一起入帳；
// 分期列的實際金額照樣逐張自己填，不帶入預計金額，有沒填或填 0 的就全部擋下並指出是哪幾張。
(() => {
  const shell = document.querySelector("[data-reconciliation]");
  if (!shell) return;
  const money = new Intl.NumberFormat("zh-TW");
  const amount = input => Math.max(Number.parseInt(input?.value || "0", 10) || 0, 0);
  const signed = value => `${value > 0 ? "+" : value < 0 ? "−" : ""}$${money.format(Math.abs(value))}`;
  const rowOf = element => element.closest("[data-reconciliation-row]");

  const preview = row => {
    const actual = row.querySelector("[data-actual-input]");
    const output = row.querySelector("[data-difference-preview]");
    if (!actual || !output || actual.dataset.expected === undefined) return;
    const adjusted = row.querySelector("[data-expected-input]");
    const expected = adjusted ? amount(adjusted) : Number(actual.dataset.expected) || 0;
    const typed = actual.value.trim() !== "" && amount(actual) > 0;
    output.hidden = !typed;
    output.textContent = typed ? `試算 ${signed(amount(actual) - expected)}` : "";
  };

  const clearMissing = input => {
    if (!input) return;
    input.setCustomValidity("");
    input.removeAttribute("aria-invalid");
  };

  const batch = document.querySelector("[data-reconciliation-batch]");
  const picks = () => [...shell.querySelectorAll("[data-batch-pick]")];
  const batchLabel = chosen => {
    const channels = new Set(chosen.map(box => box.dataset.batchChannel));
    if (channels.size === 1 && channels.has("platform")) return "平台合併撥款";
    if (channels.size === 1 && channels.has("installment")) return "分期公司合併撥款";
    return "合併入帳";
  };
  const refreshBatch = () => {
    if (!batch) return;
    const chosen = picks().filter(box => box.checked);
    picks().forEach(box => rowOf(box)?.classList.toggle("is-picked", box.checked));
    const total = chosen.reduce((sum, box) => sum + amount(rowOf(box)?.querySelector("[data-actual-input]")), 0);
    batch.hidden = chosen.length === 0;
    const label = batch.querySelector("[data-batch-label]");
    if (label) label.textContent = batchLabel(chosen);
    batch.querySelector("[data-batch-count]").textContent = String(chosen.length);
    batch.querySelector("[data-batch-total]").textContent = `$${money.format(total)}`;
    batch.querySelector("[data-batch-submit]").textContent = chosen.length > 1 ? `${chosen.length} 張一起入帳` : "入帳";
  };

  shell.addEventListener("input", event => {
    const row = rowOf(event.target);
    if (!row) return;
    if (event.target.matches("[data-actual-input]")) clearMissing(event.target);
    preview(row);
    refreshBatch();
  });
  shell.addEventListener("change", event => {
    if (!event.target.matches("[data-batch-pick]")) return;
    if (!event.target.checked) clearMissing(rowOf(event.target)?.querySelector("[data-actual-input]"));
    refreshBatch();
  });
  shell.querySelectorAll("[data-reconciliation-row]").forEach(preview);

  if (!batch) return;
  batch.querySelector("[data-batch-clear]").addEventListener("click", () => {
    picks().forEach(box => { box.checked = false; });
    refreshBatch();
  });
  batch.addEventListener("submit", event => {
    batch.querySelectorAll("[data-batch-amount]").forEach(input => input.remove());
    const chosen = picks().filter(item => item.checked);
    chosen.forEach(box => clearMissing(rowOf(box)?.querySelector("[data-actual-input]")));
    const missing = chosen.filter(box => !amount(rowOf(box)?.querySelector("[data-actual-input]")));
    if (missing.length) {
      // 一張沒填就一筆都不送；每張沒填的都標出來，訊息列出全部單號。
      event.preventDefault();
      event.stopImmediatePropagation();
      const numbers = missing.map(box => box.dataset.orderNumber || box.value).join("、");
      missing.forEach((box, index) => {
        const actual = rowOf(box)?.querySelector("[data-actual-input]");
        if (!actual) return;
        actual.setAttribute("aria-invalid", "true");
        actual.setCustomValidity(missing.length > 1
          ? `這 ${missing.length} 張還沒填實際撥款金額（不能空白或 0）：${numbers}`
          : "請填這張單的實際撥款金額。");
        if (index === 0) actual.reportValidity();
      });
      return;
    }
    const append = (name, value) => {
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = name;
      hidden.value = value;
      hidden.dataset.batchAmount = "";
      batch.append(hidden);
    };
    for (const box of chosen) {
      const row = rowOf(box);
      append(`amount_${box.value}`, String(amount(row?.querySelector("[data-actual-input]"))));
      // 分期列展開「本單特殊撥款」改過的預計金額一併送出，和單列入帳一致。
      const adjusted = row?.querySelector("[data-expected-input]");
      if (adjusted && adjusted.value.trim() !== "") append(`expected_${box.value}`, String(amount(adjusted)));
    }
  }, true);
  refreshBatch();
})();
