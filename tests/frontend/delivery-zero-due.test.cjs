// T-156（使用者 2026-11-13 簡報第 7 頁「應收已經是0，不需要在填實收金額」）：
// 收款列自動儲存後應收變成 0（含以下）時，實收金額不必填、不顯示「必填」、提示改成可直接交車；應收大於 0 時照舊。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function node(extra = {}) {
  return {hidden: false, textContent: '', dataset: {}, classList: {toggle() {}}, setAttribute() {}, addEventListener() {}, ...extra};
}

function mount(due) {
  const listeners = {};
  const mark = node({textContent: '必填'});
  const amount = node({value: '', required: true, labels: [{querySelector: () => mark}],
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }});
  const parts = {'[data-balance-received]': node(), '[data-balance-gap-label]': node(), '[data-balance-gap]': node(), '[data-balance-state]': node()};
  const summary = node({querySelector: selector => parts[selector]});
  const hint = node();
  const zeroHint = node({hidden: true});
  const fieldset = node({dataset: {deliveryDue: String(due)},
    querySelector: selector => ({'[data-balance-hint]': hint, '[data-balance-hint-zero]': zeroHint, '[data-balance-summary]': summary})[selector] || null,
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }});
  const button = node({disabled: false});
  const blockers = node({hidden: true});
  const form = node({elements: {namedItem: () => amount},
    querySelector: selector => ({'.delivery-completion-actions button[type="submit"]': button, '[data-delivery-blockers]': blockers})[selector] || null,
    querySelectorAll: () => []});
  const document = {getElementById: id => (id === 'delivery-balance' ? fieldset : null), addEventListener() {}};
  const context = {document, MutationObserver: class { observe() {} }, Event: class {}, Number, Math, String, Boolean, Array};
  vm.runInNewContext(fs.readFileSync('static/js/delivery-form.js', 'utf8'), context);
  context.bindDeliveryForms({querySelectorAll: () => [form]});
  const fire = type => (listeners[type] || []).forEach(fn => fn());
  return {amount, mark, hint, zeroHint, button, fieldset, state: parts['[data-balance-state]'], fire};
}

test('應收 0：實收不必填、不標必填、提示改成可直接交車，按鈕不因實收停用', () => {
  const view = mount(0);
  assert.equal(view.amount.required, false);
  assert.equal(view.mark.hidden, true);
  assert.equal(view.hint.hidden, true);
  assert.equal(view.zeroHint.hidden, false);
  assert.doesNotMatch(view.state.textContent, /填入實收金額/);
  assert.equal(view.button.disabled, false);
});

test('應收大於 0：實收照舊必填，提示照舊，未足額停用按鈕', () => {
  const view = mount(4800);
  assert.equal(view.amount.required, true);
  assert.equal(view.mark.hidden, false);
  assert.equal(view.hint.hidden, false);
  assert.equal(view.zeroHint.hidden, true);
  assert.equal(view.state.textContent, '填入實收金額，足額後即可收尾款並完成交車。');
  assert.equal(view.button.disabled, true);
});

test('收款列存檔讓應收從 4800 變 0 再變回來：必填跟著切換', () => {
  const view = mount(4800);
  view.fieldset.dataset.deliveryDue = '0';
  view.fire('delivery:due');
  assert.equal(view.amount.required, false);
  assert.equal(view.mark.hidden, true);
  assert.equal(view.button.disabled, false);
  view.fieldset.dataset.deliveryDue = '-200';
  view.fire('delivery:due');
  assert.equal(view.amount.required, false);
  view.fieldset.dataset.deliveryDue = '1000';
  view.fire('delivery:due');
  assert.equal(view.amount.required, true);
  assert.equal(view.mark.hidden, false);
  assert.equal(view.zeroHint.hidden, true);
  assert.equal(view.button.disabled, true);
});
