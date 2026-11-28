// T-339：強制險期間只列規則有設定的年期、微電車一律三年；既有訂單存的年期跟畫面不同時要說明（static/js/order-insurance-period.js）。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {apply} = require('../../static/js/order-insurance-period.js');

// stored：伺服器輸出時選取的選項（資料庫存的值）。
function select(stored = '1') {
  const options = ['1', '2', '3'].map(v => ({value: v, disabled: false, hidden: false, defaultSelected: v === stored}));
  return {id: 'id_compulsory_insurance_period', value: stored, options, hidden: false, dataset: {}};
}
const fixedInput = () => ({id: 'id_compulsory_insurance_period_fixed', hidden: true, value: ''});
const noteEl = () => ({hidden: true, textContent: ''});
const visible = s => s.options.filter(o => !o.hidden).map(o => o.value);

test('微電車已交車舊單存一年：顯示三年，並說明存檔改三年、保留完成時金額', () => {
  const s = select('1');
  const fixed = fixedInput();
  const note = noteEl();
  const opts = {energyType: 'micro_electric', periods: [3], basis: 'micro_electric:9', keepExisting: true, fixedInput: fixed, note, completed: true};
  apply(s, opts);
  assert.equal(s.value, '3');
  assert.equal(fixed.value, '三年');
  assert.equal(note.hidden, false);
  assert.match(note.textContent, /原本存一年/);
  assert.match(note.textContent, /保留完成時的金額/);
  apply(s, opts); // 改其他欄位後再次套用，說明照留
  assert.equal(note.hidden, false);
});

test('微電車未交車舊單：說明存檔改三年並依規則試算', () => {
  const note = noteEl();
  apply(select('1'), {energyType: 'micro_electric', basis: 'micro_electric:9', keepExisting: true, note});
  assert.match(note.textContent, /牌險依規則重新試算/);
});

test('微電車存三年、建單、換成別的車型都不顯示說明', () => {
  const stored3 = noteEl();
  apply(select('3'), {energyType: 'micro_electric', basis: 'micro_electric:9', keepExisting: true, note: stored3});
  assert.equal(stored3.hidden, true);
  const create = noteEl();
  apply(select('1'), {energyType: 'micro_electric', basis: 'micro_electric:9', keepExisting: false, note: create});
  assert.equal(create.hidden, true);
  const s = select('1');
  const note = noteEl();
  apply(s, {energyType: 'micro_electric', basis: 'micro_electric:9', keepExisting: true, note});
  assert.equal(note.hidden, false);
  apply(s, {energyType: 'gas', periods: [1, 2], basis: 'gas:7', keepExisting: true, note});
  assert.equal(note.hidden, true);
  assert.equal(s.value, '1'); // 油車選到三年改回一年（既有行為）
});

test('電動車既有值不在規則內：照原值顯示並說明；改選規則年期後只列規則有的', () => {
  const s = select('1');
  const note = noteEl();
  const opts = {energyType: 'electric', periods: [2, 3], basis: 'electric:3', keepExisting: true, note};
  apply(s, opts);
  assert.equal(s.value, '1');
  assert.equal(note.hidden, false);
  assert.match(note.textContent, /一年不在此車型規則的年期內/);
  s.value = '2'; // 使用者改選規則有的年期
  apply(s, opts);
  assert.deepEqual(visible(s), ['2', '3']);
  assert.equal(note.hidden, true);
});

test('其他車種的預設與選項不變：油車一、兩年預設一年，電動類只列規則年期，沒有規則不限制', () => {
  const gas = select('1');
  const gasNote = noteEl();
  apply(gas, {energyType: 'gas', periods: [1, 2], basis: 'gas:7', keepExisting: true, note: gasNote});
  assert.deepEqual(visible(gas), ['1', '2']);
  assert.equal(gas.value, '1');
  assert.equal(gasNote.hidden, true);
  const electric = select('2');
  apply(electric, {energyType: 'electric', periods: [2, 3], basis: 'electric:3', keepExisting: true, note: noteEl()});
  assert.deepEqual(visible(electric), ['2', '3']);
  const free = select('1');
  apply(free, {energyType: 'electric', periods: [], basis: 'electric:5', keepExisting: true, note: noteEl()});
  assert.deepEqual(visible(free), ['1', '2', '3']);
});

test('頁面傳入說明元素與已交車旗標；完成後修正的比對把微電車視為三年', () => {
  const root = path.join(__dirname, '..', '..');
  const scripts = fs.readFileSync(path.join(root, 'templates/sales/_order_form_scripts.html'), 'utf8');
  assert.match(scripts, /note: document\.querySelector\("\[data-insurance-period-note\]"\)/);
  assert.match(scripts, /input === insurancePeriod && vehicleEnergyType\.value === "micro_electric" \? "3"/);
  const field = fs.readFileSync(path.join(root, 'templates/sales/_compulsory_insurance_period_field.html'), 'utf8');
  assert.match(field, /class="help-text"[^>]*data-insurance-period-note hidden/);
});
