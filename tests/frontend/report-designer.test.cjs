const test = require('node:test');
const assert = require('node:assert/strict');
const {designerScale, designerCanvasWidth, designerChipText} = require('../../static/js/report-designer.js');
const {reportAnalysisFill} = require('../../static/js/report-analysis.js');
test('人口分析覆寫配色時，圖形沿用與提示及圖例相同的顏色', () => {
  assert.equal(reportAnalysisFill('男性', '#0072b2', 'accessible'), '#0072b2');
  assert.equal(reportAnalysisFill('男性', '#0072b2', ''), 'var(--chart-s1)');
});
test('畫布縮放不改變目標內容寬度', () => {
  assert.equal(designerScale('fit', 1440, 2000, 720, 600), .5);
  assert.equal(designerScale('page', 1440, 2000, 720, 600), .3);
  assert.equal(designerScale('1', 1440, 2000, 720, 600), 1);
  assert.equal(designerScale('fit', 390, 2000, 900, 600), 1);
});
test('縮放防呆及極窄容器', () => {
  assert.equal(designerScale('fit', 1440, 2000, 0, 600), .1);
  assert.equal(designerScale('page', 1440, 2000, 0, 0), .05);
  assert.equal(designerScale('bad', 1440, 2000, 500, 600), 1);
});
test('T-164 自動寬度：電腦至少 1180 px、更寬時以實際大小排版；手機以實際寬度；指定裝置寬度照用', () => {
  assert.equal(designerCanvasWidth('auto', 891), 1180);
  assert.equal(designerCanvasWidth('auto', 326), 326);
  assert.equal(designerCanvasWidth('auto', 100), 320);
  assert.equal(designerCanvasWidth('auto', 1320.4), 1320);
  assert.equal(designerCanvasWidth('390', 891), 390);
  assert.equal(designerCanvasWidth('1440', 2000), 1440);
  assert.equal(designerScale('fit', designerCanvasWidth('auto', 891), 2000, 891, 600).toFixed(3), '0.755');
});
test('T-164 條件標籤最多列 3 項，其餘摘要為「等 N 項」', () => {
  assert.equal(designerChipText(['SUZUKI']), 'SUZUKI');
  assert.equal(designerChipText(['A', 'B', 'C']), 'A、B、C');
  assert.equal(designerChipText(['A', 'B', 'C', 'D', '']), 'A、B、C 等 4 項');
  assert.equal(designerChipText([]), '');
});
test('T-268 選了「顏色（不分車型）」才提示改用「車型＋顏色」', () => {
  const {designerColorHint} = require('../../static/js/report-designer.js');
  assert.equal(designerColorHint('color', 'age_group'), true);
  assert.equal(designerColorHint('family', 'color'), true);
  assert.equal(designerColorHint('family_color', 'age_group'), false);
  assert.equal(designerColorHint('month', ''), false);
});
test('T-268 人口分析堆疊段落：style.backgroundColor 讀不到 var() 簡寫時改用 data-point-color，與圖例同色', () => {
  const {reportAnalysisStackColor} = require('../../static/js/report-analysis.js');
  // 根因：background:var(--chart-s3) 讀 style.backgroundColor 得到 ''，舊寫法一律退回 --chart-s1。
  assert.equal(reportAnalysisStackColor('30-39歲', '', 'var(--chart-s3)', '', true), 'var(--chart-s3)');
  assert.equal(reportAnalysisStackColor('30-39歲', '', 'var(--chart-s3)', 'accessible', true), 'var(--chart-s3)');
  // 原本就固定配色的分類與中性分類不變。
  assert.equal(reportAnalysisStackColor('男性', '', 'var(--chart-s5)', '', true), 'var(--chart-s1)');
  assert.equal(reportAnalysisStackColor('生日未填', '', 'var(--chart-other)', '', true), 'var(--chart-other)');
  // 非堆疊長條（每列一段、背景色以屬性設定，讀得到）照舊。
  assert.equal(reportAnalysisStackColor('黑（消光）', 'var(--chart-s2)', undefined, '', false), 'var(--chart-s2)');
  assert.equal(reportAnalysisStackColor('黑（消光）', '', undefined, '', false), 'var(--chart-s1)');
});
test('T-268 車型＋顏色橫條標籤：放得下就一行，放不下在「 · 」處換行、單段太長再逐字換行，不加省略號', () => {
  const {reportWrapLabel} = require('../../static/js/report-interactions.js');
  assert.deepEqual(reportWrapLabel('Fun · 白 EW1', 160), ['Fun · 白 EW1']);
  assert.deepEqual(reportWrapLabel('New NEX 125 · 白 RB5／W13', 100), ['New NEX 125 ·', '白 RB5／W13']);
  const long = reportWrapLabel('Saluto 125 · 盧卡綠 N34／T94／Q11／Z22', 90);
  const squash = text => text.replace(/\s+/g, '');
  assert.equal(squash(long.join(' ')), squash('Saluto 125 · 盧卡綠 N34／T94／Q11／Z22'));  // 只在空白處斷行，文字不少
  // 優先在空白處換行，不把 125 拆成「12」「5」。
  assert.ok(reportWrapLabel('New NEX 125 · 白', 70).every(line => !/12$/.test(line)));
  assert.ok(long.length >= 3);
  assert.ok(long.every(line => !line.includes('…')));
});
test('T-274 系列是車色時保留引擎給的車色，不被固定配色表蓋掉（藍、金不同色）', () => {
  const {reportAnalysisStackColor} = require('../../static/js/report-analysis.js');
  // 重現：「藍」在人口分析固定配色表是 --chart-s5（粉紅），「金」沒有對應時也落在同一色。
  const blue = reportAnalysisStackColor('藍', '', '#2f6fd6', '', true, true);
  const gold = reportAnalysisStackColor('金', '', '#e0a800', '', true, true);
  assert.equal(blue, '#2f6fd6');
  assert.equal(gold, '#e0a800');
  assert.notEqual(blue, gold);
  // 系列不是車色（例如性別）時照舊用固定配色。
  assert.equal(reportAnalysisStackColor('男性', '', '#123456', '', true, false), 'var(--chart-s1)');
});
