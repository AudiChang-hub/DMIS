const test = require('node:test');
const assert = require('node:assert/strict');
const {designerScale, designerCanvasWidth, designerChipText} = require('../../static/js/report-designer.js');
const {reportAnalysisFill} = require('../../static/js/report-analysis.js');
test('人口分析覆寫配色時，圖形沿用與提示及圖例相同的顏色', () => {
  assert.equal(reportAnalysisFill('男性', '#0072b2', 'accessible'), '#0072b2');
  assert.equal(reportAnalysisFill('男性', '#0072b2', ''), '#737373');
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
