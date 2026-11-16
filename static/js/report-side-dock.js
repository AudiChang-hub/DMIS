// 報表中心報表頁左側收合（T-181）：「報表頁面」「車型篩選」兩條窄標籤固定在最左側，可各自展開或收合。
// 桌面：展開時把報表往右推（不蓋住圖表），開合狀態記在 localStorage，換報表頁時維持；預設兩個都收合。
// 手機（800px 以下）：從左側滑出蓋在畫面上，一次只開一個，點外面或按 Esc 收回；不記狀態，換頁不會一進來就蓋住報表。
const REPORT_SIDE_DOCK_KEY = 'dmis.reportSideDock';
// 無痕模式或封鎖儲存時讀寫會丟例外，一律當作兩個都收合、不影響操作。
function reportSideDockRead(storage) {
  try {
    const saved = JSON.parse(storage?.getItem(REPORT_SIDE_DOCK_KEY) || '{}');
    return {pages: saved?.pages === true, tree: saved?.tree === true};
  } catch { return {pages: false, tree: false}; }
}
function reportSideDockWrite(storage, state) {
  try { storage?.setItem(REPORT_SIDE_DOCK_KEY, JSON.stringify({pages: !!state.pages, tree: !!state.tree})); return true; } catch { return false; }
}
if (typeof module !== 'undefined' && module.exports) module.exports = {reportSideDockRead, reportSideDockWrite, REPORT_SIDE_DOCK_KEY};
(() => {
  if (typeof document === 'undefined') return;
  const dock = document.currentScript?.closest('[data-report-side-dock]') || document.querySelector('[data-report-side-dock]');
  if (!dock || dock.dataset.dockReady) return;
  dock.dataset.dockReady = 'true';
  const rails = [...dock.querySelectorAll('[data-side-rail]')];
  const names = rails.map(rail => rail.dataset.sideRail);
  const railOf = name => dock.querySelector(`[data-side-rail="${name}"]`);
  const panelOf = name => dock.querySelector(`[data-side-panel="${name}"]`);
  const closerOf = name => dock.querySelector(`[data-side-close="${name}"]`);
  const backdrop = dock.querySelector('[data-side-backdrop]');
  const overlay = matchMedia('(max-width: 800px)');
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const storage = () => { try { return window.localStorage; } catch { return null; } };
  const state = {};
  // 圖表依新欄寬重算：沿用各圖既有的 resize 處理（與 T-152 相同）。
  const relayout = () => window.dispatchEvent(new Event('resize'));
  let relayoutTimer = 0;
  function relayoutAfterMotion() {
    clearTimeout(relayoutTimer);
    if (overlay.matches) return;
    relayoutTimer = setTimeout(relayout, reduceMotion.matches || dock.classList.contains('is-instant') ? 0 : 380);
  }

  function render() {
    names.forEach(name => {
      const open = !!state[name], rail = railOf(name), label = rail.dataset.sideLabel;
      panelOf(name).classList.toggle('is-open', open);
      rail.setAttribute('aria-expanded', String(open));
      rail.setAttribute('title', `${open ? '收合' : '展開'}${label}`);
      closerOf(name)?.setAttribute('aria-expanded', String(open));
    });
    const overlayOpen = overlay.matches && names.some(name => state[name]);
    dock.classList.toggle('is-overlay-open', overlayOpen);
    if (backdrop) backdrop.hidden = !overlayOpen;
    document.documentElement.classList.toggle('report-side-locked', overlayOpen);
  }
  function setOpen(name, open, {focus = null} = {}) {
    if (overlay.matches && open) names.forEach(other => { state[other] = false; });
    state[name] = open;
    if (!overlay.matches) reportSideDockWrite(storage(), state);
    render();
    relayoutAfterMotion();
    if (focus === 'panel') requestAnimationFrame(() => closerOf(name)?.focus({preventScroll: true}));
    if (focus === 'rail') railOf(name).focus({preventScroll: true});
  }
  function closeOverlay() {
    const open = names.find(name => state[name]);
    if (open) setOpen(open, false, {focus: 'rail'});
  }

  rails.forEach(rail => rail.addEventListener('click', () => {
    const name = rail.dataset.sideRail;
    setOpen(name, !state[name], {focus: overlay.matches && !state[name] ? 'panel' : null});
  }));
  names.forEach(name => closerOf(name)?.addEventListener('click', () => setOpen(name, false, {focus: 'rail'})));
  backdrop?.addEventListener('click', closeOverlay);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !dock.classList.contains('is-overlay-open')) return;
    event.preventDefault();
    closeOverlay();
  });
  // 手機與桌面切換（例如平板轉向）：進手機一律收起；回桌面恢復記住的狀態。
  overlay.addEventListener('change', () => {
    const saved = overlay.matches ? {} : reportSideDockRead(storage());
    names.forEach(name => { state[name] = !!saved[name]; });
    dock.classList.add('is-instant');
    render();
    relayoutAfterMotion();
    requestAnimationFrame(() => requestAnimationFrame(() => dock.classList.remove('is-instant')));
  });

  // 載入時直接套用記住的狀態，不播動畫。
  const saved = overlay.matches ? {} : reportSideDockRead(storage());
  names.forEach(name => { state[name] = !!saved[name]; });
  dock.classList.add('is-instant');
  render();
  if (names.some(name => state[name])) window.addEventListener('load', relayout, {once: true});
  requestAnimationFrame(() => requestAnimationFrame(() => dock.classList.remove('is-instant')));
})();
