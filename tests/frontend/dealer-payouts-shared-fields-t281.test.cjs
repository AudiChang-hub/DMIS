const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// T-281 h：給付頁各列的 csrf、next 整頁共用一份，送出時補回，伺服器收到的欄位與順序和以前相同。
const source = fs.readFileSync('static/js/dealer-payouts.js', 'utf8');

class FakeFormData {
  constructor(entries) { this.list = entries.slice(); }
  entries() { return this.list.slice()[Symbol.iterator](); }
  delete(name) { this.list = this.list.filter(([key]) => key !== name); }
  append(name, value) { this.list.push([name, value]); }
}

function load() {
  const listeners = {};
  const shared = {elements: {csrfmiddlewaretoken: {value: 'shared-token'}, next: {value: '/data/dealer-payouts/?dealer=3'}}};
  const document = {
    querySelector: (selector) => (selector === '[data-payout-page]' ? {addEventListener() {}} : null),
    getElementById: (id) => (id === 'payout-shared' ? shared : null),
    addEventListener: (type, handler, capture) => { listeners[type] = {handler, capture}; },
  };
  vm.runInNewContext(source, {document, Array, Set});
  return listeners;
}

const form = (row) => ({matches: (selector) => row && selector === 'form.payout-item__toggle, form[data-payout-note]'});

test('勾選與備註表單送出時，csrf 與 next 照原本的順序放在最前面', () => {
  const {formdata} = load();
  assert.equal(formdata.capture, true, 'formdata 事件不冒泡，要用捕獲階段');
  const toggle = new FakeFormData([['key', 'commission:order:7'], ['action', 'unpaid'], ['paid_toggle', 'on']]);
  formdata.handler({target: form(true), formData: toggle});
  assert.deepEqual(toggle.list, [['csrfmiddlewaretoken', 'shared-token'], ['next', '/data/dealer-payouts/?dealer=3'],
    ['key', 'commission:order:7'], ['action', 'unpaid'], ['paid_toggle', 'on']]);
  const note = new FakeFormData([['key', 'commission:order:7'], ['action', 'note'], ['note', '11/20 匯款']]);
  formdata.handler({target: form(true), formData: note});
  assert.deepEqual(note.list.map(([name]) => name), ['csrfmiddlewaretoken', 'next', 'key', 'action', 'note']);
});

test('其他表單（結算、批次、篩選）不動', () => {
  const {formdata} = load();
  const batch = new FakeFormData([['csrfmiddlewaretoken', 'own'], ['next', '/x'], ['action', 'paid'], ['key', 'a'], ['key', 'b']]);
  const before = batch.list.slice();
  formdata.handler({target: form(false), formData: batch});
  assert.deepEqual(batch.list, before);
});

test('同名欄位（多個 key）保留全部與順序', () => {
  const {formdata} = load();
  const data = new FakeFormData([['key', 'a'], ['action', 'paid'], ['key', 'b']]);
  formdata.handler({target: form(true), formData: data});
  assert.deepEqual(data.list.slice(2), [['key', 'a'], ['action', 'paid'], ['key', 'b']]);
});

// 使用者操作後區塊由 inplace-regions.js 用 DOMParser 換入：noscript 裡的 csrf、next 變成真的欄位，不可重複送出。
test('原地更新後 noscript 的欄位進入表單時，csrf 與 next 仍只送一次', () => {
  const {formdata} = load();
  const note = new FakeFormData([['key', 'commission:order:3'], ['action', 'note'], ['note', '11/23 匯款'],
    ['csrfmiddlewaretoken', 'from-noscript'], ['next', '/data/dealer-payouts/?dealer=3']]);
  formdata.handler({target: form(true), formData: note});
  assert.deepEqual(note.list, [['csrfmiddlewaretoken', 'shared-token'], ['next', '/data/dealer-payouts/?dealer=3'],
    ['key', 'commission:order:3'], ['action', 'note'], ['note', '11/23 匯款']]);
});
