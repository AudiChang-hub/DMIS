// 領牌年月樹狀（T-212）：年 → 月。勾年份＝全選該年各月，取消年份＝全部取消；只勾部分月份時年份半選（aria-checked="mixed"）。
// 月份仍是原本 name="months" 的勾選框：送出參數、自動套用、「只選此項」「全部取消」都沿用 report-interactions.js 的複選邏輯。
// 鍵盤：Tab 移到年份，空白鍵或 Enter 勾選；右鍵展開、左鍵收合；展開鈕也可直接按。
function reportMonthYearState(checked, total) {
  if (!total) return 'false';
  return checked === total ? 'true' : checked ? 'mixed' : 'false';
}
// 點年份後月份的勾選：全選時改成全部取消，未選或半選時全選。
function reportMonthYearTarget(state) {
  return state !== 'true';
}
function reportMonthYearCount(checked, total) {
  return `${checked}／${total}`;
}
// 搜尋時：有符合月份的年份顯示並展開，沒有的整年藏起來；清空搜尋就全部顯示、維持原本開合。
function reportMonthYearVisibility(query, visibleMonths) {
  if (!query) return {hidden: false, expand: false};
  return {hidden: visibleMonths === 0, expand: visibleMonths > 0};
}
if (typeof module !== 'undefined' && module.exports) module.exports = {reportMonthYearState, reportMonthYearTarget, reportMonthYearCount, reportMonthYearVisibility};
(() => {
  if (typeof document === 'undefined') return;
  const init = tree => {
    if (tree.dataset.monthTreeReady) return;
    tree.dataset.monthTreeReady = 'true';
    const control = tree.closest('[data-report-multi]');
    if (!control) return;
    const years = [...tree.querySelectorAll('[data-month-year]')].map(year => ({
      year,
      check: year.querySelector('[data-month-year-check]'),
      toggle: year.querySelector('[data-month-year-toggle]'),
      group: year.querySelector('.report-month-tree__months'),
      count: year.querySelector('[data-month-year-count]'),
      inputs: [...year.querySelectorAll('input[type="checkbox"]')],
    }));
    const setOpen = (item, open) => {
      item.toggle.setAttribute('aria-expanded', String(open));
      item.toggle.setAttribute('aria-label', `${open ? '收合' : '展開'} ${item.year.dataset.monthYear} 年的月份`);
      item.group.hidden = !open;
      item.year.classList.toggle('is-open', open);
    };
    const refresh = () => years.forEach(item => {
      const checked = item.inputs.filter(input => input.checked).length;
      item.check.setAttribute('aria-checked', reportMonthYearState(checked, item.inputs.length));
      item.count.textContent = reportMonthYearCount(checked, item.inputs.length);
    });
    years.forEach(item => {
      item.toggle.addEventListener('click', () => setOpen(item, item.group.hidden));
      item.check.addEventListener('click', () => {
        const target = reportMonthYearTarget(item.check.getAttribute('aria-checked'));
        item.inputs.forEach(input => { input.checked = target; });
        refresh();
        control.dispatchEvent(new Event('change', {bubbles: true}));
      });
      item.check.addEventListener('keydown', event => {
        if (event.key === 'ArrowRight') { setOpen(item, true); event.preventDefault(); }
        if (event.key === 'ArrowLeft') { setOpen(item, false); event.preventDefault(); }
      });
    });
    // 「只選此項」「全部取消」、伺服器同步（syncFromServer）之後都會送 change；打開選單時再對一次狀態。
    control.addEventListener('change', refresh);
    control.addEventListener('toggle', refresh);
    const search = control.querySelector('[data-multi-search]');
    // 共用搜尋（report-interactions.js）先藏不符合的月份，這裡等它做完再決定年份。
    search?.addEventListener('input', () => setTimeout(() => {
      const query = search.value.trim();
      years.forEach(item => {
        const visible = item.inputs.filter(input => !input.closest('label').hidden).length;
        const view = reportMonthYearVisibility(query, visible);
        item.year.hidden = view.hidden;
        if (view.expand) setOpen(item, true);
      });
    }));
    refresh();
    // report-interactions.js 初始化時可能把來源樣式的月份全部勾上（全部＝不限）；defer 腳本都跑完才有 DOMContentLoaded，屆時再對一次。
    if (document.readyState !== 'complete') document.addEventListener('DOMContentLoaded', refresh, {once: true});
    setTimeout(refresh);
  };
  const start = () => document.querySelectorAll('[data-month-tree]').forEach(init);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
