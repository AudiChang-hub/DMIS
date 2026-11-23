const test = require('node:test');
const assert = require('node:assert/strict');
const {prefillDecision, initCostPrefill} = require('../../static/js/settlement-cost-prefill.js');

class Node extends EventTarget {
  constructor(properties = {}) { super(); Object.assign(this, {hidden: false, textContent: '', value: ''}, properties); }
}
const COSTS = {'7': {amount: 56000, from: '2026/10/24'}, '9': {amount: 43000, from: '2026/11/13'}};

function fixture({bound = false, model = '', amount = ''} = {}) {
  const select = new Node({value: model});
  const input = new Node({value: amount});
  const note = new Node({hidden: true});
  const nodes = {'[name="vehicle_model"]': select, '[name="amount"]': input, '[data-cost-prefill-note]': note};
  const form = new Node({hasAttribute: name => bound && name === 'data-cost-prefill-bound', querySelector: s => nodes[s]});
  initCostPrefill(form, COSTS);
  const choose = value => { select.value = value; select.dispatchEvent(new Event('change')); };
  const type = value => { input.value = value; input.dispatchEvent(new Event('input')); };
  return {select, input, note, choose, type};
}

test('選好機種帶入目前成本並說明來源版本', () => {
  const f = fixture();
  f.choose('7');
  assert.equal(f.input.value, '56000');
  assert.equal(f.note.hidden, false);
  assert.match(f.note.textContent, /2026\/10\/24 起版本/);
  f.choose('9');
  assert.equal(f.input.value, '43000');
});

test('沒有生效中成本的機種清空自動帶入的金額', () => {
  const f = fixture();
  f.choose('7');
  f.choose('8');
  assert.equal(f.input.value, '');
  assert.match(f.note.textContent, /沒有生效中的成本/);
  f.choose('');
  assert.equal(f.input.value, '');
  assert.equal(f.note.hidden, true);
});

test('使用者手動輸入的金額不被覆蓋；清空後才恢復帶入', () => {
  const f = fixture();
  f.choose('7');
  f.type('60000');
  f.choose('9');
  assert.equal(f.input.value, '60000');
  assert.match(f.note.textContent, /已保留你輸入的金額.*43,000/);
  f.choose('');
  assert.equal(f.input.value, '60000');
  f.type('');
  f.choose('9');
  assert.equal(f.input.value, '43000');
});

test('依 ?model= 開頁帶入的金額不算手動，換機種會更新', () => {
  const f = fixture({model: '7', amount: '56000'});
  f.choose('9');
  assert.equal(f.input.value, '43000');
});

test('驗證失敗回填的金額視為手動輸入', () => {
  const f = fixture({bound: true, model: '7', amount: '61000'});
  f.choose('9');
  assert.equal(f.input.value, '61000');
});

test('決策函式：未選機種且未手動時清空', () => {
  assert.deepEqual(prefillDecision({selected: '', entry: undefined, manual: false}), {amount: '', message: ''});
  assert.equal(prefillDecision({selected: '', entry: undefined, manual: true}).amount, null);
});
