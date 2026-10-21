const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const css = fs.readFileSync('static/css/app.css', 'utf8');
const row = fs.readFileSync('templates/sales/_order_accessory_row.html', 'utf8');
const form = fs.readFileSync('templates/sales/_order_form_content.html', 'utf8');
const scripts = fs.readFileSync('templates/sales/_order_form_scripts.html', 'utf8');

// 配件精簡列（使用者 2026-10-21 T-50）：依配件區寬度排版，寬版一個配件一列、欄名在表頭。
test('寬版一個配件一列，數量、類型、金額依內容給固定欄寬，表頭與列同一組欄寬', () => {
  assert.match(css, /\.accessory-section \{ container: accessory \/ inline-size; \}/);
  assert.match(css, /@container accessory \(min-width: 760px\) \{\s*\.accessory-head, \.accessory-section \.accessory-row \{\s*grid-template-columns: minmax\(0, 1fr\) 4rem 6rem 6rem 6rem 7\.5rem 7\.5rem;/);
  assert.match(css, /grid-template-areas: "name qty type price labor total actions" "note note note note note note note";/);
  assert.match(form, /class="accessory-head" aria-hidden="true"/);
});
test('窄版（手機）名稱與按鈕一列、數字分列，單件總額一行摘要；自訂名稱仍由選擇其他控制顯示', () => {
  assert.match(css, /grid-template-areas: "name name name name actions actions" "qty qty type type type type" "price price price labor labor labor" "total total total total total total" "note note note note note note";/);
  assert.match(css, /\[data-custom-accessory\]\[hidden\]\{display:none!important\}/);
  assert.match(css, /\.accessory-section \.remove-row-button \{ position: static;/);
});
test('刪除與備註鈕在同一列，備註需要時才展開，建單精靈與訂單頁共用同一段', () => {
  assert.match(row, /data-accessory-note-toggle/);
  assert.match(row, /class="accessory-row__note" data-accessory-note \{% if not accessory_form\.note\.value and not accessory_form\.note\.errors %\}hidden\{% endif %\}/);
  assert.equal((form.match(/sales\/_order_accessory_row\.html/g) || []).length, 2);
  assert.match(scripts, /notePanel\.hidden = !open;/);
  assert.match(scripts, /quantity === 1 \? "" : `本列 ×\$\{quantity\}＝/);
});
