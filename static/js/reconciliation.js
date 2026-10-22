// 統一撥款對帳（T-96）：輸入實際金額時即時試算差額（只預覽、不標紅，按入帳後才算）；
// 平台合併撥款勾選多張單，各自的實際金額加總後一起入帳。
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

  const batch = document.querySelector("[data-reconciliation-batch]");
  const picks = () => [...shell.querySelectorAll("[data-batch-pick]")];
  const refreshBatch = () => {
    if (!batch) return;
    const chosen = picks().filter(box => box.checked);
    picks().forEach(box => rowOf(box)?.classList.toggle("is-picked", box.checked));
    const total = chosen.reduce((sum, box) => sum + amount(rowOf(box)?.querySelector("[data-actual-input]")), 0);
    batch.hidden = chosen.length === 0;
    batch.querySelector("[data-batch-count]").textContent = String(chosen.length);
    batch.querySelector("[data-batch-total]").textContent = `$${money.format(total)}`;
    batch.querySelector("[data-batch-submit]").textContent = chosen.length > 1 ? `${chosen.length} 張一起入帳` : "入帳";
  };

  shell.addEventListener("input", event => {
    const row = rowOf(event.target);
    if (!row) return;
    if (event.target.matches("[data-actual-input]")) event.target.setCustomValidity("");
    preview(row);
    refreshBatch();
  });
  shell.addEventListener("change", event => {
    if (event.target.matches("[data-batch-pick]")) refreshBatch();
  });
  shell.querySelectorAll("[data-reconciliation-row]").forEach(preview);

  if (!batch) return;
  batch.querySelector("[data-batch-clear]").addEventListener("click", () => {
    picks().forEach(box => { box.checked = false; });
    refreshBatch();
  });
  batch.addEventListener("submit", event => {
    batch.querySelectorAll("[data-batch-amount]").forEach(input => input.remove());
    for (const box of picks().filter(item => item.checked)) {
      const actual = rowOf(box)?.querySelector("[data-actual-input]");
      if (!amount(actual)) {
        event.preventDefault();
        event.stopImmediatePropagation();
        actual.setCustomValidity("請填這張單的實際撥款金額。");
        actual.reportValidity();
        return;
      }
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = `amount_${box.value}`;
      hidden.value = String(amount(actual));
      hidden.dataset.batchAmount = "";
      batch.append(hidden);
    }
  }, true);
  refreshBatch();
})();
