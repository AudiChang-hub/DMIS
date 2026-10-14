/* 套表列印：表格勾選 ↔ 列印清單。勾選存在 sessionStorage，換頁、重新搜尋都保留；關閉分頁即清除。 */
(function () {
  const root = document.querySelector("[data-form-print]");
  if (!root) return;
  const KEY = "dmis-form-print-v1";
  const FORMS = ["envelope", "tax_declaration", "receipt"];
  const trayForm = root.querySelector("[data-tray-form]");
  const list = root.querySelector("[data-list]");
  const template = document.querySelector("[data-item-template]");
  const dock = document.querySelector("[data-dock]");

  // state：{ 訂單 pk: { number, name, vehicle, forms: { key: 顯示名稱 }, note, address, seq } }
  let state = {};
  try { state = JSON.parse(sessionStorage.getItem(KEY) || "{}") || {}; } catch (error) { state = {}; }
  let seq = Object.values(state).reduce((max, item) => Math.max(max, item.seq || 0), 0);

  const save = () => {
    try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (error) { /* 無痕模式等情況只保留在畫面上 */ }
  };

  const rowOf = (element) => element.closest("tr[data-order]");

  const entryFor = (row) => {
    const pk = row.dataset.order;
    if (!state[pk]) {
      state[pk] = {
        number: row.dataset.number, name: row.dataset.name, vehicle: row.dataset.vehicle,
        forms: {}, note: row.dataset.note || "", address: row.dataset.address || "", seq: ++seq,
      };
    }
    return state[pk];
  };

  const setForm = (row, input, checked) => {
    const entry = entryFor(row);
    if (checked) entry.forms[input.dataset.form] = input.dataset.label;
    else delete entry.forms[input.dataset.form];
    if (!Object.keys(entry.forms).length) delete state[row.dataset.order];
  };

  const syncRow = (row) => {
    const entry = state[row.dataset.order];
    const inputs = row.querySelectorAll("input[data-form]");
    inputs.forEach((input) => { input.checked = Boolean(entry && entry.forms[input.dataset.form]); });
    const picked = [...inputs].filter((input) => input.checked).length;
    const master = row.querySelector("[data-row-pick]");
    master.checked = picked > 0;
    master.indeterminate = picked > 0 && picked < inputs.length;
    row.classList.toggle("is-picked", picked > 0);
  };

  const render = () => {
    const entries = Object.entries(state).sort((a, b) => a[1].seq - b[1].seq);
    const counts = Object.fromEntries(FORMS.map((key) => [key, 0]));
    list.replaceChildren();
    trayForm.querySelectorAll("input[name='job']").forEach((input) => input.remove());
    entries.forEach(([pk, entry]) => {
      const node = template.content.firstElementChild.cloneNode(true);
      node.dataset.order = pk;
      node.querySelector("[data-item-name]").textContent = entry.name || "（未填車主）";
      node.querySelector("[data-item-meta]").textContent = [entry.number, entry.vehicle].filter(Boolean).join("・");
      const chips = node.querySelector("[data-item-chips]");
      FORMS.filter((key) => entry.forms[key]).forEach((key) => {
        counts[key] += 1;
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "form-print__chip";
        chip.dataset.removeForm = key;
        chip.setAttribute("aria-label", `不印 ${entry.forms[key]}`);
        chip.innerHTML = `<span></span><i aria-hidden="true">×</i>`;
        chip.querySelector("span").textContent = entry.forms[key];
        chips.append(chip);
        const job = document.createElement("input");
        job.type = "hidden";
        job.name = "job";
        job.value = `${pk}:${key}`;
        trayForm.append(job);
      });
      const receipt = node.querySelector("[data-item-receipt]");
      const note = node.querySelector("[data-item-note]");
      const address = node.querySelector("[data-item-address]");
      receipt.hidden = !entry.forms.receipt;
      note.name = `note_${pk}`;
      address.name = `address_${pk}`;
      note.value = entry.note || "";
      address.value = entry.address || "";
      list.append(node);
    });
    const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
    root.querySelector("[data-total]").textContent = total;
    FORMS.forEach((key) => {
      const paper = root.querySelector(`[data-paper="${key}"]`);
      paper.querySelector("[data-paper-count]").textContent = counts[key];
      paper.classList.toggle("is-active", counts[key] > 0);
    });
    root.querySelector("[data-empty]").hidden = total > 0;
    trayForm.querySelector("[data-submit]").disabled = total === 0;
    trayForm.querySelector("[data-submit]").textContent = total ? `產生 PDF（${total} 頁）` : "產生 PDF";
    trayForm.querySelector("[data-clear]").disabled = total === 0;
    if (dock) {
      dock.hidden = total === 0;
      dock.querySelector("[data-dock-count]").textContent = total;
    }
    root.querySelectorAll("tr[data-order]").forEach(syncRow);
    save();
  };

  root.addEventListener("change", (event) => {
    const input = event.target;
    const row = rowOf(input);
    if (!row) return;
    if (input.matches("[data-row-pick]")) {
      const inputs = [...row.querySelectorAll("input[data-form]")];
      const anyPicked = inputs.some((item) => item.checked);
      inputs.forEach((item) => setForm(row, item, !anyPicked && item.hasAttribute("data-suggested")));
    } else if (input.matches("input[data-form]")) {
      setForm(row, input, input.checked);
    } else {
      return;
    }
    render();
  });

  root.addEventListener("click", (event) => {
    const column = event.target.closest("[data-column]");
    if (column) {
      const key = column.dataset.column;
      const inputs = [...root.querySelectorAll(`tbody input[data-form="${key}"]`)];
      const allPicked = inputs.length && inputs.every((input) => input.checked);
      inputs.forEach((input) => setForm(rowOf(input), input, !allPicked));
      render();
      return;
    }
    const chip = event.target.closest("[data-remove-form]");
    const item = event.target.closest(".form-print__item");
    if (chip && item) {
      const entry = state[item.dataset.order];
      delete entry.forms[chip.dataset.removeForm];
      if (!Object.keys(entry.forms).length) delete state[item.dataset.order];
      render();
      return;
    }
    if (event.target.closest("[data-remove]") && item) {
      delete state[item.dataset.order];
      render();
      return;
    }
    if (event.target.closest("[data-clear]")) {
      state = {};
      render();
    }
  });

  list.addEventListener("input", (event) => {
    const item = event.target.closest(".form-print__item");
    if (!item || !state[item.dataset.order]) return;
    if (event.target.matches("[data-item-note]")) state[item.dataset.order].note = event.target.value;
    if (event.target.matches("[data-item-address]")) state[item.dataset.order].address = event.target.value;
    save();
  });

  render();
})();
