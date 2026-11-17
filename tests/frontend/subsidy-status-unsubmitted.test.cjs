// T-216：補助申請項目的狀態下拉切換時即時換色：改成已申請拿掉紅底 class，改回未申請加回去；其他欄位的 change 不碰。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function classes(initial = []) {
  const set = new Set(initial);
  return {set, contains: name => set.has(name), add: name => set.add(name), remove: name => set.delete(name),
    toggle(name, force) { const on = force === undefined ? !set.has(name) : force; if (on) set.add(name); else set.delete(name); return on; }};
}

function field(selectorMatch, value, initial) {
  return {value, classList: classes(initial), matches: selector => selector === selectorMatch, closest: () => null};
}

function mount() {
  const listeners = [];
  const list = {querySelectorAll: () => [], addEventListener(type, fn) { if (type === 'change') listeners.push(fn); }};
  const section = {
    querySelector: selector => ({'[data-form-list]': list, "input[name$='-TOTAL_FORMS']": {value: '0'}})[selector] || null,
    addEventListener() {},
  };
  let ready;
  const document = {
    querySelector: selector => (selector === '[data-subsidy-items]' ? section : null),
    querySelectorAll: () => [],
    addEventListener(type, fn) { if (type === 'DOMContentLoaded') ready = fn; },
  };
  vm.runInNewContext(fs.readFileSync('static/js/subsidy-items.js', 'utf8'), {document, window: {}, Number, String});
  ready();
  return target => listeners.forEach(fn => fn({target}));
}

const STATUS = 'select[data-subsidy-status]';

test('改成已申請：紅底 class 拿掉', () => {
  const change = mount();
  const select = field(STATUS, 'submitted', ['subsidy-status', 'is-unsubmitted']);
  change(select);
  assert.equal(select.classList.contains('is-unsubmitted'), false);
  assert.equal(select.classList.contains('subsidy-status'), true);
});

test('改回未申請：紅底 class 加回', () => {
  const change = mount();
  const select = field(STATUS, 'not_submitted', ['subsidy-status']);
  change(select);
  assert.equal(select.classList.contains('is-unsubmitted'), true);
});

test('其他下拉（類別）的 change 不會被加上紅底', () => {
  const change = mount();
  const category = field("select[name$='-category']", 'not_submitted', []);
  change(category);
  assert.deepEqual([...category.classList.set], []);
});
