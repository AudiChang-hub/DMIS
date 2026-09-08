(() => {
  "use strict";
  const editor = document.querySelector("[data-report-editor]");
  if (editor) {
    const container = editor.querySelector("[data-report-cards]");
    const total = editor.querySelector('[name="cards-TOTAL_FORMS"]');
    const status = editor.querySelector("[data-save-state]");
    const message = editor.querySelector("[data-card-message]");
    let dirty = editor.dataset.unsaved === "true";
    const markDirty = () => { dirty = true; status.textContent = "有尚未儲存的變更"; };
    const cards = () => [...container.querySelectorAll("[data-report-card]")].filter(card => !card.hidden);
    const update = () => cards().forEach((card, index, all) => {
      card.querySelector("[data-card-number]").textContent = String(index + 1);
      card.querySelector('[name$="-ORDER"]').value = String(index + 1);
      card.querySelector("[data-card-up]").disabled = index === 0;
      card.querySelector("[data-card-down]").disabled = index === all.length - 1;
      card.querySelector(".report-field--formula").hidden = card.querySelector('[name$="-metric"]').value !== "formula";
      ["series", "series_limit", "series_other", "series_sort"].forEach(name => {
        const field = card.querySelector(`[name$="-${name}"]`);
        if (field) {
          field.disabled = card.querySelector('[name$="-chart"]').value !== "stacked";
          field.closest(".report-field").hidden = field.disabled;
        }
      });
    });
    editor.addEventListener("input", markDirty);
    editor.addEventListener("change", () => { markDirty(); update(); });
    editor.addEventListener("click", event => {
      const target = event.target.closest("button");
      if (!target) return;
      if (target.matches("[data-add-card]")) {
        const deleted = [...container.querySelectorAll("[data-report-card]")].find(card => card.hidden);
        if (cards().length >= 8) { message.textContent = "每份報表最多 8 張圖表。"; return; }
        const index = deleted ? Number(deleted.querySelector('[name$="-ORDER"]').name.split("-")[1]) : Number(total.value);
        const fragment = editor.querySelector("[data-card-template]").content.cloneNode(true);
        fragment.querySelectorAll("[name],[id],[for]").forEach(element => {
          ["name", "id", "for"].forEach(attr => {
            if (element.hasAttribute(attr)) element.setAttribute(attr, element.getAttribute(attr).replaceAll("__prefix__", String(index)));
          });
        });
        if (deleted) deleted.remove(); else total.value = String(index + 1);
        container.append(fragment);
        const added = cards().at(-1);
        added.querySelector('[name$="-title"]').value = "新圖表";
        added.querySelector('[name$="-limit"]').value = "20";
        update(); markDirty(); added.querySelector("input").focus();
        message.textContent = `目前 ${cards().length} 張圖表`;
      }
      const card = target.closest("[data-report-card]");
      if (!card) return;
      const visible = cards(); const index = visible.indexOf(card);
      if (target.matches("[data-card-delete]")) {
        if (visible.length === 1 && !editor.querySelector('[name="include_records"]')?.checked) { message.textContent = "至少須保留一張圖表，或啟用來源訂單明細表。"; return; }
        card.querySelector('[name$="-DELETE"]').checked = true;
        card.hidden = true;
        card.querySelectorAll("[required]").forEach(input => input.required = false);
      } else if (target.matches("[data-card-up]") && index > 0) {
        container.insertBefore(card, visible[index - 1]);
      } else if (target.matches("[data-card-down]") && index < visible.length - 1) {
        container.insertBefore(visible[index + 1], card);
      } else return;
      update(); markDirty();
    });
    editor.addEventListener("submit", () => { dirty = false; update(); });
    window.addEventListener("beforeunload", event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
    container.querySelectorAll('[name$="-DELETE"]:checked').forEach(input => {
      const removed = input.closest("[data-report-card]"); removed.hidden = true;
      removed.querySelectorAll("[required]").forEach(field => field.required = false);
    });
    update();
    if (dirty) markDirty();
  }
  document.querySelector("[data-report-print]")?.addEventListener("click", () => window.print());
  document.querySelector("[data-confirm-unpublish]")?.addEventListener("submit", event => {
    if (!window.confirm("確定取消發布？讀者將無法再查看此報表，草稿與歷史版本仍會保留。")) event.preventDefault();
  });
  document.querySelectorAll('[data-chart="line"]').forEach(chart => {
    const rows = [...chart.querySelectorAll("[data-point-value]")];
    const points = rows.map(row => row.dataset.pointValue === "" ? null : Number(row.dataset.pointValue));
    const valid = points.filter(value => value !== null && Number.isFinite(value));
    if (!valid.length) return;
    const min = Math.min(0, ...valid), max = Math.max(1, ...valid), range = max - min;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 600 190");
    const addLine = segment => {
      if (!segment.length) return;
      const path = document.createElementNS(svg.namespaceURI, "polyline");
      path.setAttribute("points", segment.join(" ")); path.setAttribute("fill", "none");
      path.setAttribute("stroke", "var(--forest)"); path.setAttribute("stroke-width", "3"); svg.append(path);
    };
    let segment = [];
    points.forEach((value, index) => {
      if (value === null || !Number.isFinite(value)) { addLine(segment); segment = []; return; }
      const x = 22 + index / Math.max(1, points.length - 1) * 550;
      const y = 155 - (value - min) / range * 130;
      segment.push(`${x},${y}`);
      const dot = document.createElementNS(svg.namespaceURI, "circle");
      dot.setAttribute("cx", String(x)); dot.setAttribute("cy", String(y)); dot.setAttribute("r", "4"); dot.setAttribute("fill", "var(--forest)");
      const title = document.createElementNS(svg.namespaceURI, "title"); title.textContent = `${rows[index].dataset.pointLabel}: ${value}`;
      dot.append(title); svg.append(dot);
    });
    addLine(segment);
    const label = document.createElementNS(svg.namespaceURI, "text"); label.setAttribute("x", "20"); label.setAttribute("y", "183"); label.setAttribute("font-size", "12"); label.setAttribute("fill", "var(--muted)");
    label.textContent = `${rows[0].dataset.pointLabel} → ${rows.at(-1).dataset.pointLabel}（逐群數值詳見下表）`; svg.append(label);
    chart.querySelector("[data-line-chart]")?.append(svg);
  });
})();
