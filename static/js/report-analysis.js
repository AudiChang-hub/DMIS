/* 人口分析的長條圖；只使用已授權模板資料與既有交叉篩選連結。
   T-182：改用與其他堆疊圖相同的橫向長條（report-interactions.js 的 reportStackPlot），依卡片寬度繪製，手機不再左右捲動。 */
function reportAnalysisColor(label, fallback) {
  const neutral = ['公司或其他', '生日未填', '生日異常', '其他', '其他系列（合併）'];
  if (neutral.includes(label)) return 'var(--chart-other)';
  const slots = {'男性':1, '女性':2, '灰':3, '白':4, '藍':5, '帕瑪森白':6, '黑':7, '魔綠幻紫':8, '黃':1, '海神藍':2};
  return label in slots ? `var(--chart-s${slots[label]})` : fallback;
}
function reportAnalysisFill(label, fallback, palette) {
  return palette === 'accessible' ? fallback : reportAnalysisColor(label, fallback);
}
/* T-268 根因：堆疊段的顏色寫在 style="background:var(--chart-sN)"（簡寫＋變數），讀 style.backgroundColor 會得到空字串，
   人口分析的堆疊圖因此除了固定配色的分類（男性、女性、白…）以外全部退回第一色。改用段落上的 data-point-color（與圖例同色）。 */
function reportAnalysisStackColor(label, fallback, pointColor, palette, stacked) {
  const own = fallback || pointColor;
  return reportAnalysisFill(label, palette === 'accessible' && stacked ? own : own || 'var(--chart-s1)', palette);
}
function renderReportAnalysis(chart, attach) {
  const rows = [...chart.querySelectorAll('.report-results tr[data-point-value]')];
  if (!rows.length) return;
  const stacked = chart.dataset.chart === 'stacked';
  let groups = [...chart.querySelectorAll('.report-stack-row')];
  const seriesColors = new Map([...chart.querySelectorAll('[data-stack-segment][data-point-color]')].map(segment => [segment.dataset.seriesLabel, segment.dataset.pointColor]));
  if (!stacked) {
    // 單一系列的長條：每列當成只有一段的堆疊，顏色依分類固定。
    groups = rows.map(row => {
      const group = document.createElement('div'), caption = document.createElement('strong'), wrap = document.createElement('div');
      wrap.className = 'report-stack-caption'; wrap.append(caption); caption.textContent = row.dataset.pointLabel;
      const segment = document.createElement('span'); segment.dataset.stackSegment = '';
      Object.assign(segment.dataset, {seriesLabel: row.dataset.pointLabel, pointValue: row.dataset.pointValue, pointDisplay: row.dataset.pointDisplay});
      segment.style.backgroundColor = row.dataset.pointColor || 'var(--chart-s1)';
      group.append(wrap, segment); return group;
    });
  }
  const {svg, node} = reportStackPlot(chart, groups, rows, {
    interactiveSegments: stacked,
    colorOf: (label, fallback) => reportAnalysisStackColor(label, fallback, seriesColors.get(label), chart.dataset.palette, stacked),
    attach,
  });
  svg.classList.add('report-analysis-plot');
  const table = chart.querySelector('.report-table-wrap'); table.before(node); if (node !== svg) node.scrollLeft = node.scrollWidth; table.hidden = true;
  const stacks = chart.querySelector('.report-stacks'); if (stacks) stacks.hidden = true;
}
if (typeof module !== 'undefined' && module.exports) module.exports = {reportAnalysisColor, reportAnalysisFill, reportAnalysisStackColor};
