// T-333：建單與訂單頁的強制險期間選項（static/js/order-insurance-period.js）。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {allowedPeriods, apply} = require('../../static/js/order-insurance-period.js');

function select(value = '1') {
  const options = ['1', '2', '3'].map(v => ({value: v, disabled: false, hidden: false}));
  return {id: 'id_compulsory_insurance_period', value, options, hidden: false, dataset: {}};
}
const fixedInput = () => ({id: 'id_compulsory_insurance_period_fixed', hidden: true, value: ''});
const visible = s => s.options.filter(o => !o.hidden).map(o => o.value);

test('油車只有一年、兩年，預設一年，選到三年改回一年', () => {
  const s = select('1');
  const fixed = fixedInput();
  const result = apply(s, {energyType: 'gas', periods: [1, 2], basis: 'gas:7', fixedInput: fixed});
  assert.deepEqual(visible(s), ['1', '2']);
  assert.equal(s.value, '1');
  assert.equal(result.fixed, false);
  assert.equal(s.hidden, false);
  assert.equal(fixed.hidden, true);
  const three = select('3');
  apply(three, {energyType: 'gas', basis: 'gas:7'});
  assert.equal(three.value, '1');
});

test('微電車固定三年：下拉隱藏、顯示唯讀「三年」，label 指向唯讀欄', () => {
  const s = select('1');
  const fixed = fixedInput();
  const label = {htmlFor: s.id};
  const result = apply(s, {energyType: 'micro_electric', periods: [3], basis: 'micro_electric:9', fixedInput: fixed, label});
  assert.equal(s.value, '3');
  assert.equal(result.fixed, true);
  assert.equal(s.hidden, true);
  assert.equal(fixed.hidden, false);
  assert.equal(fixed.value, '三年');
  assert.equal(label.htmlFor, fixed.id);
  // 換回油車：下拉恢復、唯讀欄隱藏。
  apply(s, {energyType: 'gas', basis: 'gas:7', fixedInput: fixed, label});
  assert.equal(s.hidden, false);
  assert.equal(fixed.hidden, true);
  assert.equal(label.htmlFor, s.id);
  assert.equal(s.value, '1');
});

test('電動類依品牌固定規則的年期；沒有規則不限制', () => {
  assert.deepEqual(allowedPeriods('electric', [2, 1, 2]), [1, 2]);
  assert.deepEqual(allowedPeriods('light_electric', []), []);
  assert.deepEqual(allowedPeriods('electric', undefined), []);
  assert.deepEqual(allowedPeriods('', [1]), []);
  const s = select('1');
  apply(s, {energyType: 'electric', periods: [], basis: 'electric:3'});
  assert.deepEqual(visible(s), ['1', '2', '3']);
  // 建單：只有一種年期時直接換成那一種並固定顯示。
  const single = select('1');
  const fixed = fixedInput();
  apply(single, {energyType: 'electric', periods: [2], basis: 'electric:3', fixedInput: fixed});
  assert.equal(single.value, '2');
  assert.equal(fixed.value, '兩年');
});

test('訂單頁的電動車既有值不在規則內：載入與改其他欄位都照原值，換車型才換', () => {
  const s = select('1');
  const opts = {energyType: 'electric', periods: [2, 3], basis: 'electric:3', keepExisting: true, fixedInput: fixedInput()};
  apply(s, opts);
  assert.equal(s.value, '1');
  assert.deepEqual(visible(s), ['1', '2', '3']);
  apply(s, opts); // 例如改了選號費，車型沒變
  assert.equal(s.value, '1');
  apply(s, {...opts, basis: 'electric:4'}); // 換車型
  assert.equal(s.value, '2');
  assert.deepEqual(visible(s), ['2', '3']);
});

test('建單與訂單頁都載入模組，自動儲存會換新領牌試算卡', () => {
  const root = path.join(__dirname, '..', '..');
  const scripts = fs.readFileSync(path.join(root, 'templates/sales/_order_form_scripts.html'), 'utf8');
  assert.match(scripts, /js\/order-insurance-period\.js/);
  assert.match(scripts, /DmisInsurancePeriod\.apply\(insurancePeriod/);
  const workspace = fs.readFileSync(path.join(root, 'static/js/order-workspace.js'), 'utf8');
  assert.match(workspace, /payload\.finance_registration_html/);
  assert.match(workspace, /\[data-finance-registration\]/);
});
