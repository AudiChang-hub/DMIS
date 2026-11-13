/* T-164 報表目錄：拖拉或鍵盤調整分組與順序，放開即送出整份排序；伺服器以版本號防止覆蓋。 */
function catalogPayload(lists) {
  return {pages: lists.flatMap(list => list.rows.map(row => ({pk: Number(row.pk), group: list.group, version: Number(row.version)})))};
}
/* 鍵盤移動：在「分組內順序」攤平的序列上移一格；到分組頂端再往上就移到上一組最後。 */
function catalogKeyboardTarget(lists, group, index, delta) {
  const at = lists.findIndex(list => list.group === group);
  if (at < 0) return null;
  const size = lists[at].size;
  const next = index + delta;
  if (next >= 0 && next < size) return {group, index: next};
  const neighbour = lists[at + (delta < 0 ? -1 : 1)];
  if (!neighbour) return null;
  return {group: neighbour.group, index: delta < 0 ? neighbour.size : 0};
}
if (typeof module !== 'undefined') module.exports = {catalogPayload, catalogKeyboardTarget};
if (typeof document !== 'undefined') (() => {
  'use strict';
  const root = document.querySelector('[data-report-catalog]');
  const startDialog = document.querySelector('[data-start-dialog]');
  document.querySelector('[data-open-start]')?.addEventListener('click', () => startDialog?.showModal());
  startDialog?.addEventListener('click', event => { if (event.target === startDialog || event.target.closest('[data-close-start]')) startDialog.close(); });
  if (!root) return;
  const status = document.querySelector('[data-catalog-status]');
  const lists = () => [...root.querySelectorAll('[data-group-list]')];
  const rows = list => [...list.querySelectorAll(':scope > [data-report-row]')];
  const describe = () => lists().map(list => ({group: list.dataset.group, rows: rows(list).map(row => ({pk: row.dataset.pk, version: row.dataset.version}))}));
  const orderKey = () => JSON.stringify(describe().map(list => [list.group, list.rows.map(row => row.pk)]));
  let saved = orderKey(), savedLayout = describe(), timer, controller;

  function say(text, state = '') { status.textContent = text; status.dataset.state = state; }
  function refreshGroups() {
    lists().forEach(list => {
      const section = list.closest('.catalog-group'), count = rows(list).length;
      section.querySelector('[data-group-count]').textContent = `${count} 份`;
      section.querySelector('[data-group-empty]').hidden = count > 0;
    });
  }
  function restore(layout) {
    const all = new Map([...root.querySelectorAll('[data-report-row]')].map(row => [row.dataset.pk, row]));
    layout.forEach(item => { const list = root.querySelector(`[data-group-list][data-group="${item.group}"]`); item.rows.forEach(row => list.append(all.get(row.pk))); });
    refreshGroups();
  }
  async function save() {
    clearTimeout(timer);
    if (orderKey() === saved) return;
    controller?.abort(); controller = new AbortController();
    const token = root.querySelector('[name="csrfmiddlewaretoken"]').value;
    say('正在儲存順序…', 'busy');
    try {
      const response = await fetch(root.dataset.reorderUrl, {method: 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': token}, body: JSON.stringify(catalogPayload(describe()))});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw Object.assign(new Error(payload.error || '儲存失敗，請重新整理後再試。'), {status: response.status});
      Object.entries(payload.versions || {}).forEach(([pk, version]) => {
        root.querySelector(`[data-report-row][data-pk="${pk}"]`)?.setAttribute('data-version', String(version));
        document.querySelectorAll(`[data-version-for="${pk}"]`).forEach(input => { input.value = String(version); });
      });
      saved = orderKey(); savedLayout = describe();
      say(payload.changed?.length ? '已儲存，報表中心的分組與順序已更新。' : '順序沒有變更。', 'ready');
    } catch (error) {
      if (error.name === 'AbortError') return;
      restore(savedLayout); saved = orderKey();
      say(`沒有儲存：${error.message}`, 'error');
      if (error.status === 409) {
        const reload = document.createElement('button'); reload.type = 'button'; reload.className = 'button ghost'; reload.textContent = '重新整理';
        reload.addEventListener('click', () => location.reload()); status.append(' ', reload);
      }
    }
  }
  const schedule = delay => { clearTimeout(timer); timer = setTimeout(save, delay); };

  /* 滑鼠／觸控拖拉：只從把手開始。拖拉中原列留在原位淡出、影子跟著游標、插入線標示落點；放開才移動並儲存，版面不會跳動。 */
  root.addEventListener('pointerdown', event => {
    const handle = event.target.closest('[data-drag-handle]');
    if (!handle || event.button !== 0) return;
    event.preventDefault(); handle.focus({preventScroll: true});
    const row = handle.closest('[data-report-row]'), origin = row.getBoundingClientRect();
    const startX = event.clientX, startY = event.clientY;
    handle.setPointerCapture(event.pointerId);
    const line = document.createElement('li'); line.className = 'catalog-drop-line'; line.setAttribute('aria-hidden', 'true');
    let ghost = null, raf = 0, dragging = false;
    const clearTargets = () => root.querySelectorAll('.catalog-group.is-target').forEach(group => group.classList.remove('is-target'));
    const place = point => {
      const under = document.elementFromPoint(point.clientX, point.clientY);
      const target = under?.closest('[data-report-row]');
      const section = (target || under)?.closest('.catalog-group');
      clearTargets();
      if (!section) { line.remove(); return; }
      section.classList.add('is-target');
      const list = section.querySelector('[data-group-list]');
      if (target && target !== row) {
        const rect = target.getBoundingClientRect();
        list.insertBefore(line, point.clientY < rect.top + rect.height / 2 ? target : target.nextSibling);
      } else if (!target) {
        const others = rows(list).filter(item => item !== row);
        const after = others.find(item => point.clientY < item.getBoundingClientRect().top + item.getBoundingClientRect().height / 2);
        list.insertBefore(line, after || null);
      } else line.remove();
    };
    const move = point => {
      if (!dragging && Math.abs(point.clientX - startX) + Math.abs(point.clientY - startY) < 4) return;
      if (!dragging) {
        dragging = true;
        ghost = row.cloneNode(true); ghost.classList.add('catalog-ghost'); ghost.removeAttribute('data-report-row');
        ghost.querySelectorAll('[id],[name]').forEach(item => { item.removeAttribute('id'); item.removeAttribute('name'); });
        Object.assign(ghost.style, {width: `${origin.width}px`, left: `${origin.left}px`, top: `${origin.top}px`});
        document.body.append(ghost); row.classList.add('is-dragging'); root.classList.add('is-sorting');
      }
      ghost.style.transform = `translate(${point.clientX - startX}px,${point.clientY - startY}px)`;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const edge = 72;
        if (point.clientY < edge) window.scrollBy(0, -14); else if (point.clientY > innerHeight - edge) window.scrollBy(0, 14);
        place(point);
      });
    };
    const stop = end => {
      cancelAnimationFrame(raf);
      handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', stop); handle.removeEventListener('pointercancel', stop);
      if (dragging && end.type === 'pointerup') {
        place(end);
        if (line.parentElement) line.parentElement.insertBefore(row, line);
      }
      line.remove(); ghost?.remove(); clearTargets();
      row.classList.remove('is-dragging'); root.classList.remove('is-sorting');
      refreshGroups();
      if (dragging) {
        const list = row.parentElement;
        say(`「${row.dataset.title}」放到「${list.dataset.groupLabel}」第 ${rows(list).indexOf(row) + 1} 位。`, 'busy');
        schedule(0);
      }
    };
    handle.addEventListener('pointermove', move); handle.addEventListener('pointerup', stop); handle.addEventListener('pointercancel', stop);
  });

  root.addEventListener('keydown', event => {
    const handle = event.target.closest('[data-drag-handle]');
    if (!handle || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const row = handle.closest('[data-report-row]'), list = row.parentElement;
    const summary = lists().map(item => ({group: item.dataset.group, size: rows(item).filter(other => other !== row).length}));
    const target = catalogKeyboardTarget(summary.map(item => item.group === list.dataset.group ? {...item, size: item.size + 1} : item), list.dataset.group, rows(list).indexOf(row), event.key === 'ArrowUp' ? -1 : 1);
    if (!target) return;
    const destination = root.querySelector(`[data-group-list][data-group="${target.group}"]`);
    const others = rows(destination).filter(other => other !== row);
    destination.insertBefore(row, others[target.index] || null);
    refreshGroups(); handle.focus();
    say(`「${row.dataset.title}」移到「${destination.dataset.groupLabel}」第 ${rows(destination).indexOf(row) + 1} 位，稍後自動儲存。`, 'busy');
    schedule(700);
  });
  root.addEventListener('focusout', event => { if (event.target.closest('[data-drag-handle]')) schedule(150); });
})();
