// 套表列印頁「列印清單」左側收合（T-193）：操作方式同報表中心左側窄條（T-181），只用在套表列印頁。
// 桌面：展開時把訂單表格往右推，收合後表格吃滿寬度；開合狀態記在 localStorage。沒記過時，寬螢幕（1100px 以上）預設展開，較窄時預設收合。
// 手機（800px 以下）：從左側滑出蓋在表格上，點外面或按 Esc 收回；不記狀態，一進來不會蓋住表格。
const FORM_PRINT_TRAY_KEY = 'dmis.formPrintTray';
// 無痕模式或封鎖儲存時讀寫會丟例外，一律當作沒記過（回傳 null，改用預設值）。
function formPrintTrayRead(storage) {
  try {
    const saved = JSON.parse(storage?.getItem(FORM_PRINT_TRAY_KEY) || 'null');
    return typeof saved?.open === 'boolean' ? saved.open : null;
  } catch { return null; }
}
function formPrintTrayWrite(storage, open) {
  try { storage?.setItem(FORM_PRINT_TRAY_KEY, JSON.stringify({open: !!open})); return true; } catch { return false; }
}
if (typeof module !== 'undefined' && module.exports) module.exports = {formPrintTrayRead, formPrintTrayWrite, FORM_PRINT_TRAY_KEY};
(() => {
  if (typeof document === 'undefined') return;
  const dock = document.currentScript?.closest('[data-tray-dock]') || document.querySelector('[data-tray-dock]');
  if (!dock || dock.dataset.dockReady) return;
  dock.dataset.dockReady = 'true';
  const rail = dock.querySelector('[data-tray-rail]');
  const panel = dock.querySelector('[data-tray-panel]');
  const closer = dock.querySelector('[data-tray-close]');
  const backdrop = dock.querySelector('[data-tray-backdrop]');
  const overlay = matchMedia('(max-width: 800px)');
  const wide = matchMedia('(min-width: 1100.02px)');
  const storage = () => { try { return window.localStorage; } catch { return null; } };
  let open = false;

  function initial() {
    if (overlay.matches) return false;
    const saved = formPrintTrayRead(storage());
    return saved === null ? wide.matches : saved;
  }
  function render() {
    panel.classList.toggle('is-open', open);
    rail.setAttribute('aria-expanded', String(open));
    rail.setAttribute('title', open ? '收合列印清單' : '展開列印清單');
    closer?.setAttribute('aria-expanded', String(open));
    const overlayOpen = overlay.matches && open;
    dock.classList.toggle('is-overlay-open', overlayOpen);
    if (backdrop) backdrop.hidden = !overlayOpen;
    document.documentElement.classList.toggle('form-print-tray-locked', overlayOpen);
  }
  function setOpen(next, {focus = null} = {}) {
    open = next;
    if (!overlay.matches) formPrintTrayWrite(storage(), open);
    render();
    if (focus === 'panel') requestAnimationFrame(() => closer?.focus({preventScroll: true}));
    if (focus === 'rail') rail.focus({preventScroll: true});
  }
  function instant() {
    dock.classList.add('is-instant');
    render();
    requestAnimationFrame(() => requestAnimationFrame(() => dock.classList.remove('is-instant')));
  }

  rail.addEventListener('click', () => setOpen(!open, {focus: overlay.matches && !open ? 'panel' : null}));
  closer?.addEventListener('click', () => setOpen(false, {focus: 'rail'}));
  backdrop?.addEventListener('click', () => setOpen(false, {focus: 'rail'}));
  document.addEventListener('keydown', event => {
    // 預覽對話框開著時，Esc 交給對話框自己關。
    if (event.key !== 'Escape' || !dock.classList.contains('is-overlay-open') || document.querySelector('dialog[open]')) return;
    event.preventDefault();
    setOpen(false, {focus: 'rail'});
  });
  // 手機與桌面切換（例如平板轉向）：進手機一律收起；回桌面恢復記住的狀態。
  overlay.addEventListener('change', () => { open = initial(); instant(); });

  // 載入時直接套用記住的狀態，不播動畫。
  open = initial();
  instant();
})();
