const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const css = fs.readFileSync('static/css/ppt-refinements.css', 'utf8');
test('配件卡片有明確間距，平板名稱欄不跨滿整列', () => {
  assert.match(css, /\.accessory-section #accessory-forms\{display:grid;gap:24px;/);
  assert.match(css, /\.accessory-section \.accessory-row>\.field:first-of-type\{grid-column:auto;padding-right:0\}/);
  assert.match(css, /@media\(min-width:601px\) and \(max-width:1100px\)\{\.accessory-section \.accessory-row\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)\}\}/);
});
test('手機保持單欄，備註跨欄，自訂名稱仍由選擇其他控制顯示', () => {
  assert.match(css, /@media\(max-width:600px\)\{\.accessory-section #accessory-forms\{gap:20px\}/);
  assert.match(css, /\.accessory-section \.accessory-row>\.field:last-child\{grid-column:1 \/ -1\}/);
  assert.match(css, /\[data-custom-accessory\]\[hidden\]\{display:none!important\}/);
});
