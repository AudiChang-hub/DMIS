/* T-311 月份圖切換（_month_switch.html）：#4 #5 #7 的日期堆疊圖合成一張，切換鈕換細分方式。
   每個細分仍是原本的圖卡（連動、匯出、明細照舊）；圖都先依卡片寬度畫好，未選的細分只隱藏，切換不重畫。
   選到哪個細分記在本頁（點選連動換新圖卡後維持），重新整理後回到同一個（sessionStorage，讀寫失敗就用第一個）。 */
const reportMonthSwitchChoice = new Map();
function initReportMonthSwitch(root) {
  root.querySelectorAll('[data-chart-switch]').forEach(box => {
    if (box.dataset.switchReady) return;
    box.dataset.switchReady = 'true';
    const tabs = [...box.querySelectorAll('[data-switch-tab]')];
    const panels = [...box.querySelectorAll(':scope > [data-switch-panel]')];
    if (!tabs.length || !panels.length) return;
    const key = `report-month-switch:${location.pathname}:${tabs.map(tab => tab.dataset.switchTab).join(',')}`;
    const show = (index, focus = false) => {
      tabs.forEach(tab => {
        const on = tab.dataset.switchTab === index;
        tab.setAttribute('aria-selected', String(on)); tab.tabIndex = on ? 0 : -1;
        if (on && focus) tab.focus();
      });
      panels.forEach(panel => {
        const on = panel.dataset.chartIndex === index;
        panel.toggleAttribute('data-switch-current', on); panel.inert = !on;
      });
      box.dataset.active = index;
      reportMonthSwitchChoice.set(key, index);
      try { sessionStorage.setItem(key, index); } catch (error) { /* 無法記住時下次回到第一個細分 */ }
    };
    let stored = reportMonthSwitchChoice.get(key);
    if (!stored) { try { stored = sessionStorage.getItem(key); } catch (error) { stored = null; } }
    show(tabs.some(tab => tab.dataset.switchTab === stored) ? stored : tabs[0].dataset.switchTab);
    tabs.forEach((tab, position) => {
      tab.addEventListener('click', () => show(tab.dataset.switchTab));
      tab.addEventListener('keydown', event => {
        const target = {ArrowRight: position + 1, ArrowLeft: position - 1, Home: 0, End: tabs.length - 1}[event.key];
        if (target === undefined) return;
        event.preventDefault();
        show(tabs[(target + tabs.length) % tabs.length].dataset.switchTab, true);
      });
    });
  });
}
