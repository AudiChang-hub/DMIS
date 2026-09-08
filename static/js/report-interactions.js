/* 圖表互動只讀取伺服器已授權資料；不修改報表或訂單。 */
function reportPointText(data, metric) {
  let text = `${data.pointLabel}\n${metric}：${data.pointDisplay}`;
  if (metric !== "訂單台數") text += `\n訂單台數：${data.pointCount}`;
  if (data.pointPercentage !== "" && Number.isFinite(Number(data.pointPercentage))) text += `\n占完整篩選範圍：${Number(data.pointPercentage).toFixed(1)}%`;
  return text;
}
function reportFraction(value, total) {
  if (!Number.isFinite(Number(value)) || !Number.isFinite(Number(total)) || Number(total) <= 0) return 0;
  return Math.max(0, Math.min(100, Number(value) / Number(total) * 100));
}
if (typeof module !== "undefined" && module.exports) module.exports = {reportPointText, reportFraction};
(() => {
  "use strict";
  if (typeof document === "undefined") return;
  const initMulti = root => root.querySelectorAll("[data-report-multi]").forEach(control => {
    if (control.dataset.multiReady) return;
    control.dataset.multiReady = "true";
    const inputs = [...control.querySelectorAll('input[type="checkbox"]')];
    const update = () => {
      const selected = inputs.filter(input => input.checked);
      control.querySelector("[data-multi-summary]").textContent = selected.length ? `已選 ${selected.length} 項` : "不限（可複選）";
      const scope = control.closest(".report-card-scope");
      if (scope) {
        const count = scope.querySelectorAll('input[type="checkbox"]:checked').length;
        scope.querySelector("[data-scope-count]").textContent = count ? `已選 ${count} 項` : "沿用報表範圍";
      }
    };
    control.addEventListener("change", update);
    control.querySelector("[data-multi-search]").addEventListener("input", event => {
      const query = event.target.value.trim().toLocaleLowerCase();
      control.querySelectorAll("[data-multi-option]").forEach(option => { option.hidden = !option.textContent.toLocaleLowerCase().includes(query); });
    });
    control.querySelector("[data-multi-all]").addEventListener("click", () => {
      inputs.filter(input => !input.closest("label").hidden).forEach(input => { input.checked = true; });
      control.dispatchEvent(new Event("change", {bubbles:true}));
    });
    control.querySelector("[data-multi-clear]").addEventListener("click", () => { inputs.forEach(input => { input.checked = false; }); control.dispatchEvent(new Event("change", {bubbles:true})); });
    control.addEventListener("toggle", () => {
      if (control.open) document.querySelectorAll("[data-report-multi]").forEach(other => { if (other !== control) other.open = false; });
    });
    control.addEventListener("keydown", event => { if (event.key === "Escape") { control.open = false; control.querySelector("summary").focus(); } });
    document.addEventListener("click", event => { if (!control.contains(event.target)) control.open = false; });
    update();
  });
  initMulti(document);
  const editorCards = document.querySelector("[data-report-cards]");
  if (editorCards) new MutationObserver(() => initMulti(editorCards)).observe(editorCards, {childList:true});

  const palette = ["#4257a5", "#278168", "#b65b33", "#9269af", "#28789d", "#a86e11", "#b3446c", "#5c6b78"];
  document.querySelectorAll(".report-chart").forEach((chart, chartIndex) => {
    const rows = [...chart.querySelectorAll("[data-point-value]")];
    const tip = document.createElement("div");
    tip.className = "report-point-tooltip"; tip.id = `report-tooltip-${chartIndex}`; tip.setAttribute("role", "tooltip"); tip.hidden = true; chart.append(tip);
    const describe = row => reportPointText(row.dataset, chart.dataset.metricLabel);
    const attach = (target, row) => {
      const link = row.querySelector("[data-report-drill]");
      target.setAttribute("tabindex", "0"); target.setAttribute("role", link ? "button" : "img");
      target.setAttribute("aria-label", describe(row)); target.setAttribute("aria-describedby", tip.id);
      const show = event => {
        tip.textContent = describe(row); tip.hidden = false;
        const box = target.getBoundingClientRect();
        const x = event?.clientX || box.left + box.width / 2;
        const y = event?.clientY || box.top;
        tip.style.left = `${Math.max(8, Math.min(x + 12, window.innerWidth - tip.offsetWidth - 8))}px`;
        tip.style.top = `${Math.max(8, Math.min(y + 14, window.innerHeight - tip.offsetHeight - 8))}px`;
      };
      target.addEventListener("pointerenter", show); target.addEventListener("pointermove", show);
      target.addEventListener("focus", show); target.addEventListener("pointerleave", () => { tip.hidden = true; });
      target.addEventListener("blur", () => { tip.hidden = true; });
      target.addEventListener("click", event => {
        if (link && link.contains(event.target)) { tip.hidden = true; return; }
        if (event.pointerType === "touch") { show(event); return; }
        tip.hidden = true; link?.click();
      });
      target.addEventListener("keydown", event => {
        if (event.key === "Escape") tip.hidden = true;
        if (link && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); tip.hidden = true; link.click(); }
      });
    };
    rows.forEach(row => {
      const bar = row.querySelector(".report-bar-track");
      if (bar) attach(bar, row);
      if (row.hasAttribute("data-stack-segment")) {
        attach(row, row);
        const link = row.querySelector("[data-report-drill]");
        if (link) link.tabIndex = -1;
      }
    });
    if (chart.dataset.chart === "line") {
      const validRows = rows.filter(row => row.dataset.pointValue !== "" && Number.isFinite(Number(row.dataset.pointValue)));
      chart.querySelectorAll("svg circle").forEach((dot, index) => { dot.setAttribute("r", "7"); attach(dot, validRows[index]); });
      chart.querySelectorAll("svg polyline").forEach(line => { line.style.pointerEvents = "none"; });
    }
    if (chart.dataset.chart === "donut") {
      const total = Number(chart.dataset.total);
      const host = chart.querySelector("[data-line-chart]");
      if (total > 0 && rows.length) {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", "0 0 300 300"); svg.classList.add("report-donut");
        const ring = (color, fraction, offset) => {
          const circle = document.createElementNS(ns, "circle");
          for (const [key, value] of Object.entries({cx:150,cy:150,r:100,fill:"none",stroke:color,"stroke-width":46,pathLength:100,"stroke-dasharray":`${fraction} ${100-fraction}`,"stroke-dashoffset":-offset,transform:"rotate(-90 150 150)"})) circle.setAttribute(key, String(value));
          svg.append(circle); return circle;
        };
        ring("var(--line)", 100, 0); let offset = 0;
        rows.forEach((row, index) => {
          const fraction = reportFraction(row.dataset.pointValue, total);
          if (!fraction) return;
          const color = palette[index % palette.length];
          attach(ring(color, fraction, offset), row); offset += fraction;
          const swatch = document.createElement("span"); swatch.className = "report-legend-dot"; swatch.style.background = color;
          row.querySelector("th").prepend(swatch);
        });
        const text = document.createElementNS(ns, "text"); text.setAttribute("x", "150"); text.setAttribute("y", "154"); text.setAttribute("text-anchor", "middle"); text.setAttribute("fill", "currentColor"); text.textContent = chart.querySelector(".report-score strong").textContent; svg.append(text);
        host.append(svg);
        if (offset < 99.99) { const note = document.createElement("p"); note.className = "report-muted"; note.textContent = "灰色區域為未顯示群組；占比以完整篩選範圍計算。"; host.append(note); }
      } else host.textContent = "目前沒有可呈現的正值資料。";
    }
    chart.querySelector("[data-chart-fullscreen]")?.addEventListener("click", () => {
      // 使用頁內放大，不倚賴瀏覽器全螢幕授權；Escape 或原按鈕即可返回。
      const expanded = chart.classList.toggle("report-chart-expanded");
      chart.querySelector("[data-chart-fullscreen]").textContent = expanded ? "返回原大小" : "放大圖表";
      if (expanded) chart.scrollIntoView({block:"start", behavior:"smooth"});
    });
    chart.addEventListener("keydown", event => { if (event.key === "Escape") { chart.classList.remove("report-chart-expanded"); const button = chart.querySelector("[data-chart-fullscreen]"); if (button) button.textContent = "放大圖表"; } });
  });

  const panel = document.querySelector("[data-inline-detail]");
  if (!panel) return;
  let controller, sequence = 0, currentUrl = null;
  const body = panel.querySelector("[data-detail-body]");
  const status = panel.querySelector("[data-detail-status]");
  const selection = panel.querySelector("[data-detail-selection]");
  async function loadDetail(url, label) {
    controller?.abort(); controller = new AbortController(); const ownController = controller; const ticket = ++sequence;
    panel.hidden = false; panel.setAttribute("aria-busy", "true"); status.textContent = "正在讀取明細…";
    body.replaceChildren(); selection.textContent = label;
    document.querySelector("[data-report-exploration]").classList.add("has-detail");
    const target = new URL(url, location.href); target.searchParams.set("inline", "1"); currentUrl = target;
    const timeout = setTimeout(() => ownController.abort(), 15000);
    try {
      const response = await fetch(target, {signal:ownController.signal, credentials:"same-origin", headers:{"X-Requested-With":"XMLHttpRequest"}});
      if (!response.ok || response.redirected) throw new Error(response.status === 409 ? "報表已更新，請重新整理報表後再選取。" : "無法讀取明細，請確認登入與查看權限，或稍後再試。");
      const documentFragment = new DOMParser().parseFromString(await response.text(), "text/html");
      const content = documentFragment.querySelector("[data-detail-content]");
      if (!content) throw new Error("回應不是有效明細，請重新登入或稍後再試。");
      if (ticket !== sequence) return;
      body.replaceChildren(document.importNode(content, true)); status.textContent = "明細已更新，圖表與篩選條件保留。";
      selection.focus({preventScroll:true});
      if (window.innerWidth <= 1100) panel.scrollIntoView({block:"start", behavior:"smooth"});
    } catch (error) {
      if (ticket !== sequence) return;
      status.textContent = error.name === "AbortError" ? "讀取逾時，請重新點選分類再試。" : error.message;
    } finally { clearTimeout(timeout); if (ticket === sequence) panel.removeAttribute("aria-busy"); }
  }
  document.addEventListener("click", event => {
    const link = event.target.closest("a[data-report-drill],a[data-detail-page]");
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button) return;
    event.preventDefault();
    if (link.matches("[data-report-drill]")) {
      document.querySelectorAll(".report-row-selected").forEach(row => row.classList.remove("report-row-selected"));
      const row = link.closest("[data-point-label]") || link.closest(".report-stack-row");
      row?.classList.add("report-row-selected");
      loadDetail(link.href, `已選取：${row?.dataset.pointLabel || link.getAttribute("aria-label") || link.textContent.trim()}`);
    } else loadDetail(new URL(link.getAttribute("href"), currentUrl).href, selection.textContent);
  });
  panel.querySelector("[data-detail-clear]").addEventListener("click", () => {
    ++sequence; controller?.abort(); panel.hidden = true; body.replaceChildren();
    document.querySelector("[data-report-exploration]").classList.remove("has-detail");
    const selected = document.querySelector(".report-row-selected"); selected?.querySelector("a")?.focus(); selected?.classList.remove("report-row-selected");
  });
})();
