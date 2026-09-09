(() => {
  "use strict";
  const editor = document.querySelector("[data-report-editor]");
  if (!editor) return;
  const workbench = editor.querySelector("[data-workbench]");
  const canvas = editor.querySelector("[data-design-canvas]");
  const forms = editor.querySelector("[data-report-cards]");
  const status = editor.querySelector("[data-canvas-status]");
  const panels = () => [...forms.querySelectorAll("[data-report-card]")].filter(el => !el.hidden);
  const field = (panel, name) => panel.querySelector(`[name$="-${name}"]`);
  const tiles = new Map();
  let selected, controller, requestId = 0, generation = 0;
  workbench.hidden = false;
  editor.querySelector('[name="action"][value="publish"]').textContent = "儲存並發布";
  // Keep the existing validated inputs and names; only change their presentation.
  const settings = document.createElement("details");
  settings.className = "report-panel report-page-settings";
  const summary = document.createElement("summary"); summary.textContent = "整份報表設定、固定範圍與附表";
  settings.append(summary);
  [...editor.children].filter(el => el.matches("section.report-panel, details.report-panel")).forEach(el => settings.append(el));
  editor.insertBefore(settings, workbench);
  if (settings.querySelector(".errorlist")) settings.open = true;
  function select(panel) {
    selected = panel;
    panels().forEach(item => {
      item.dataset.selected = String(item === panel);
      tiles.get(item)?.classList.toggle("is-selected", item === panel);
      tiles.get(item)?.querySelector("[data-select-chart]")?.setAttribute("aria-pressed", String(item === panel));
    });
  }
  function changed() {
    generation++;
    editor.dispatchEvent(new Event("report-layout-change"));
    status.textContent = "設定已變更；請更新實際圖表確認。尚未儲存發布。";
    sync();
  }
  function sync() {
    const visible = panels();
    for (const [panel, tile] of tiles) if (!visible.includes(panel)) { tile.remove(); tiles.delete(panel); }
    visible.forEach((panel, index) => {
      let tile = tiles.get(panel);
      if (!tile) {
        tile = document.createElement("section"); tile.className = "report-design-tile";
        const heading = document.createElement("div"); heading.className = "report-tile-heading";
        const handle = document.createElement("button"); handle.type = "button"; handle.textContent = "⠿";
        handle.className = "report-drag-handle"; handle.setAttribute("aria-label", "拖曳圖表排序；也可使用右側上移下移按鈕");
        const choose = document.createElement("button"); choose.type = "button"; choose.dataset.selectChart = "";
        choose.addEventListener("click", () => { select(panel); if (window.innerWidth <= 800) forms.closest("aside").scrollIntoView({block: "start", behavior: "smooth"}); });
        heading.append(handle, choose);
        const frame = document.createElement("iframe"); frame.title = "圖表實際資料預覽";
        frame.setAttribute("sandbox", "allow-scripts");
        const resize = document.createElement("button"); resize.type = "button"; resize.className = "report-resize-handle";
        resize.textContent = "↘"; resize.setAttribute("aria-label", "調整圖表大小；方向鍵調整寬高");
        resize.addEventListener("keydown", event => {
          if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
          event.preventDefault(); select(panel);
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") field(panel, "width").value = event.key === "ArrowLeft" ? "6" : "12";
          else field(panel, "height").value = String(Math.max(320, Math.min(1200, Number(field(panel, "height").value || 520) + (event.key === "ArrowDown" ? 40 : -40))));
          changed();
        });
        function pointerStart(event, resizing) {
          if (event.button !== 0) return;
          event.preventDefault(); select(panel);
          const target = canvas, x = event.clientX, y = event.clientY;
          const startHeight = tile.getBoundingClientRect().height;
          target.setPointerCapture(event.pointerId); canvas.classList.add("is-dragging");
          let moved = false;
          const move = e => {
            moved = moved || Math.abs(e.clientX - x) + Math.abs(e.clientY - y) > 5;
            if (resizing) {
              field(panel, "height").value = String(Math.max(320, Math.min(1200, Math.round(startHeight + e.clientY - y))));
              field(panel, "width").value = e.clientX - tile.getBoundingClientRect().left > canvas.clientWidth * 0.7 ? "12" : "6";
              sync();
            } else {
              for (const [other, element] of tiles) {
                if (other === panel) continue;
                const rect = element.getBoundingClientRect();
                if (e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom) {
                  const before = panels().indexOf(panel) > panels().indexOf(other);
                  forms.insertBefore(panel, before ? other : other.nextSibling); sync(); break;
                }
              }
              if (e.clientY > window.innerHeight - 80) window.scrollBy(0, 18);
              if (e.clientY < 80) window.scrollBy(0, -18);
            }
          };
          const end = () => {
            target.removeEventListener("pointermove", move); target.removeEventListener("pointerup", end); target.removeEventListener("pointercancel", end);
            canvas.classList.remove("is-dragging"); if (moved) changed();
          };
          target.addEventListener("pointermove", move); target.addEventListener("pointerup", end); target.addEventListener("pointercancel", end);
        }
        handle.addEventListener("pointerdown", event => pointerStart(event, false));
        resize.addEventListener("pointerdown", event => pointerStart(event, true));
        tile.append(heading, frame, resize); tiles.set(panel, tile);
      }
      tile.querySelector("[data-select-chart]").textContent = `${index + 1}. ${field(panel, "title").value || "新圖表"}`;
      tile.style.gridColumn = field(panel, "width").value === "12" ? "1 / -1" : "span 1";
      tile.style.height = `${Math.max(320, Math.min(1200, Number(field(panel, "height").value || 520)))}px`;
      // Avoid moving existing iframes unnecessarily: moving them reloads their document.
      if (canvas.children[index] !== tile) canvas.insertBefore(tile, canvas.children[index] || null);
    });
    select(visible.includes(selected) ? selected : visible[0]);
  }
  async function refresh() {
    controller?.abort(); controller = new AbortController();
    const current = ++requestId, currentGeneration = generation;
    const activeController = controller;
    const timeout = setTimeout(() => activeController.abort(), 30000);
    status.textContent = "正在依目前設定查詢實際資料…";
    const body = new FormData(editor); body.set("action", "canvas");
    try {
      const response = await fetch(editor.getAttribute("action") || location.href, {method: "POST", body, signal: controller.signal, credentials: "same-origin"});
      if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("登入可能已逾時或伺服器暫時無法回應，請另開分頁確認登入後重試。");
      const payload = await response.json();
      if (current !== requestId || currentGeneration !== generation) return;
      if (!response.ok) {
        const messages = [];
        const collect = value => {
          if (typeof value === "string") messages.push(value);
          else if (Array.isArray(value)) value.forEach(collect);
          else if (value && typeof value === "object") {
            if (value.message) messages.push(value.message); else Object.values(value).forEach(collect);
          }
        };
        collect(payload.errors);
        throw new Error(messages.slice(0, 6).join("；") || "請檢查必填欄位。");
      }
      sync();
      panels().forEach((panel, index) => { tiles.get(panel).querySelector("iframe").srcdoc = payload.cards[index]; });
      status.textContent = `已更新 ${payload.cards.length} 張實際圖表。此為尚未發布的設計預覽。`;
    } catch (error) {
      if (current === requestId) status.textContent = error.name === "AbortError" ? "查詢逾時或已取消，可再按更新實際圖表；輸入仍保留。" : `無法更新預覽：${error.message}`;
    } finally { clearTimeout(timeout); }
  }
  editor.addEventListener("input", () => { generation++; sync(); status.textContent = "設定已變更，請更新實際圖表。"; });
  editor.addEventListener("change", () => { generation++; sync(); });
  editor.addEventListener("click", event => {
    if (event.target.closest("[data-add-card],[data-card-up],[data-card-down],[data-card-delete]")) {
      generation++; sync();
      if (event.target.closest("[data-add-card]")) select(panels().at(-1));
    }
  });
  editor.addEventListener("invalid", event => {
    const panel = event.target.closest("[data-report-card]");
    if (panel) select(panel); else settings.open = true;
  }, true);
  editor.querySelector("[data-refresh-canvas]").addEventListener("click", refresh);
  window.addEventListener("pagehide", () => controller?.abort());
  sync(); refresh();
})();
