// 大數據分析群組的樹狀篩選（T-151）：總計 → 品牌 → 能源別 → 車型。
// 勾選後交給報表篩選表單（report-interactions.js）防抖、寫進網址並原地更新；
// 全選＝不帶 model，全部取消＝empty_model=1（不顯示資料）。ARIA tree：方向鍵移動／展開／收合，空白鍵或 Enter 勾選。
function reportTreeCheckedState(checked, total) {
  if (!total) return 'false';
  return checked === total ? 'true' : checked ? 'mixed' : 'false';
}
function reportTreeStatus(checked, total) {
  if (checked === total) return `全部 ${total} 個車型`;
  return checked ? `已選 ${checked}／${total} 個車型` : '未選取（不顯示資料）';
}
// 送出前改寫表單資料：全選不帶條件，全部取消改送 empty_model。
function reportTreeFormData(formData, checked, total) {
  formData.delete('empty_model');
  if (checked === total) formData.delete('model');
  if (!checked) { formData.delete('model'); formData.set('empty_model', '1'); }
  return formData;
}
if (typeof module !== 'undefined' && module.exports) module.exports = {reportTreeCheckedState, reportTreeStatus, reportTreeFormData};
(() => {
  if (typeof document === 'undefined') return;
  const root = document.querySelector('[data-report-tree]');
  const form = document.getElementById('report-filter-form');
  const tree = root?.querySelector('[role="tree"]');
  if (!root || !form || !tree || root.dataset.treeReady) return;
  root.dataset.treeReady = 'true';
  const proxy = form.querySelector('[data-report-tree-proxy]');
  const items = [...tree.querySelectorAll('[role="treeitem"]')];
  const inputs = [...tree.querySelectorAll('[data-tree-input]')];
  const status = root.querySelector('[data-report-tree-status]');
  const parentOf = item => item.parentElement.closest('[role="treeitem"]');
  const leavesOf = item => [...item.querySelectorAll('[data-tree-input]')];
  const isVisible = item => { for (let parent = parentOf(item); parent; parent = parentOf(parent)) if (parent.getAttribute('aria-expanded') === 'false') return false; return true; };
  const visibleItems = () => items.filter(isVisible);
  // 節點名稱只取自己的名稱與台數，不把展開的子節點文字一併念出。
  items.forEach((item, index) => {
    const row = item.querySelector(':scope > .report-tree__row');
    const label = row.querySelector('.report-tree__label'), count = row.querySelector('[data-tree-count-text]');
    label.id = `report-tree-label-${index}`; count.id = `report-tree-count-${index}`;
    item.setAttribute('aria-labelledby', `${label.id} ${count.id}`);
  });

  function refresh() {
    items.forEach(item => {
      const leaves = leavesOf(item);
      item.setAttribute('aria-checked', reportTreeCheckedState(leaves.filter(input => input.checked).length, leaves.length));
    });
    status.textContent = reportTreeStatus(inputs.filter(input => input.checked).length, inputs.length);
  }
  function apply() { refresh(); proxy?.dispatchEvent(new Event('change', {bubbles: true})); }
  function toggleChecked(item) {
    const value = item.getAttribute('aria-checked') !== 'true';
    leavesOf(item).forEach(input => { input.checked = value; });
    apply();
  }
  function setExpanded(item, value) {
    if (item.hasAttribute('aria-expanded')) item.setAttribute('aria-expanded', String(value));
  }
  function focusItem(item) {
    if (!item) return;
    items.forEach(other => { other.tabIndex = other === item ? 0 : -1; });
    item.focus({preventScroll: false});
  }

  form.addEventListener('formdata', event => {
    reportTreeFormData(event.formData, inputs.filter(input => input.checked).length, inputs.length);
  });
  tree.addEventListener('click', event => {
    const item = event.target.closest('[role="treeitem"]');
    if (!item || !event.target.closest('.report-tree__row')) return;
    if (event.target.closest('[data-tree-toggle]')) setExpanded(item, item.getAttribute('aria-expanded') !== 'true');
    else toggleChecked(item);
    focusItem(item);
  });
  tree.addEventListener('keydown', event => {
    const item = event.target.closest('[role="treeitem"]');
    if (!item || event.altKey || event.ctrlKey || event.metaKey) return;
    const visible = visibleItems(), index = visible.indexOf(item);
    const expanded = item.getAttribute('aria-expanded');
    const handlers = {
      ArrowDown: () => focusItem(visible[index + 1]),
      ArrowUp: () => focusItem(visible[index - 1]),
      Home: () => focusItem(visible[0]),
      End: () => focusItem(visible[visible.length - 1]),
      ArrowRight: () => expanded === 'false' ? setExpanded(item, true) : expanded === 'true' && focusItem(item.querySelector('[role="treeitem"]')),
      ArrowLeft: () => expanded === 'true' ? setExpanded(item, false) : focusItem(parentOf(item)),
      ' ': () => toggleChecked(item),
      Enter: () => toggleChecked(item),
    };
    if (!handlers[event.key]) return;
    event.preventDefault();
    handlers[event.key]();
  });
  tree.addEventListener('focusin', event => {
    const item = event.target.closest('[role="treeitem"]');
    if (item) items.forEach(other => { other.tabIndex = other === item ? 0 : -1; });
  });
  root.querySelectorAll('[data-report-tree-expand]').forEach(button => button.addEventListener('click', () => {
    const all = button.dataset.reportTreeExpand === 'all';
    items.forEach(item => setExpanded(item, all || Number(item.getAttribute('aria-level')) === 1));
  }));

  // 窄螢幕：放在報表內容上方，預設收合成一列，點「展開」才顯示樹。
  const drawer = root.querySelector('[data-report-tree-drawer]');
  const drawerText = root.querySelector('[data-report-tree-drawer-text]');
  const narrow = matchMedia('(max-width: 1280px)');
  function setDrawer(open) {
    root.classList.toggle('is-collapsed', !open);
    drawer.setAttribute('aria-expanded', String(open));
    drawerText.textContent = open ? '收合' : '展開';
  }
  drawer.hidden = false;
  drawer.addEventListener('click', () => setDrawer(root.classList.contains('is-collapsed')));
  setDrawer(!narrow.matches);

  // 原地更新後（含移除標籤、上一頁）：勾選與台數以伺服器結果為準，展開狀態與焦點保留。
  document.addEventListener('report-filters-synced', event => {
    const next = event.detail?.doc?.querySelector('[data-report-tree]');
    if (!next) return;
    items.forEach(item => {
      const source = next.querySelector(`[data-tree-key="${CSS.escape(item.dataset.treeKey)}"]`);
      if (!source) return;
      const count = source.dataset.treeCount;
      item.dataset.treeCount = count;
      item.classList.toggle('is-empty', count === '0');
      const text = item.querySelector(':scope > .report-tree__row [data-tree-count-text]');
      const nextText = source.querySelector(':scope > .report-tree__row [data-tree-count-text]');
      if (text && nextText) text.replaceChildren(...[...nextText.childNodes].map(node => document.importNode(node, true)));
      const input = item.querySelector(':scope > [data-tree-input]'), nextInput = source.querySelector(':scope > [data-tree-input]');
      if (input && nextInput) input.checked = nextInput.checked;
    });
    refresh();
  });
  refresh();
})();
