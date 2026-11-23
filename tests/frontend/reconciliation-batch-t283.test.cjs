// T-283（使用者 2026-11-23）：撥款對帳頁的分期公司撥款列也能勾選、和平台列一起入帳。
// 分期列的實際金額照樣逐張自己填（不帶入預計）；勾選的列有空白或 0，一筆都不送出並標出每一張。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function input(value, extra = {}) {
  const attrs = {};
  return {
    value, dataset: {}, validity: '', reported: 0,
    setCustomValidity(message) { this.validity = message; },
    reportValidity() { this.reported += 1; },
    setAttribute(name, val) { attrs[name] = val; },
    removeAttribute(name) { delete attrs[name]; },
    getAttribute(name) { return attrs[name] ?? null; },
    matches: () => false,
    closest() { return this.row; },
    ...extra,
  };
}

function row({pk, channel, number, actual, expected = null}) {
  const actualInput = input(actual, {matches: selector => selector === '[data-actual-input]'});
  const expectedInput = expected === null ? null : input(expected);
  const pick = input('', {value: String(pk), checked: false, dataset: {batchChannel: channel, orderNumber: number},
    matches: selector => selector === '[data-batch-pick]'});
  const classes = new Set();
  const element = {
    classList: {toggle(name, on) { if (on) classes.add(name); else classes.delete(name); }, has: name => classes.has(name)},
    querySelector: selector => ({'[data-actual-input]': actualInput, '[data-expected-input]': expectedInput,
      '[data-difference-preview]': null})[selector] ?? null,
  };
  for (const item of [actualInput, pick, expectedInput].filter(Boolean)) item.row = element;
  return {element, actualInput, expectedInput, pick};
}

function mount(rows) {
  const listeners = {shell: {}, batch: {}};
  const appended = [];
  const parts = {
    '[data-batch-label]': {textContent: '合併入帳'},
    '[data-batch-count]': {textContent: '0'},
    '[data-batch-total]': {textContent: '$0'},
    '[data-batch-submit]': {textContent: '一起入帳'},
    '[data-batch-clear]': {addEventListener() {}},
  };
  const batch = {
    hidden: true,
    querySelector: selector => parts[selector],
    querySelectorAll: () => appended.filter(item => !item.removed).map(item => ({remove() { item.removed = true; }})),
    append(node) { appended.push(node); },
    addEventListener(type, fn) { (listeners.batch[type] ||= []).push(fn); },
  };
  const shell = {
    querySelectorAll: selector => (selector === '[data-batch-pick]' ? rows.map(r => r.pick)
      : selector === '[data-reconciliation-row]' ? rows.map(r => r.element) : []),
    addEventListener(type, fn) { (listeners.shell[type] ||= []).push(fn); },
  };
  const document = {
    querySelector: selector => ({'[data-reconciliation]': shell, '[data-reconciliation-batch]': batch})[selector] ?? null,
    createElement: () => ({dataset: {}}),
  };
  vm.runInNewContext(fs.readFileSync('static/js/reconciliation.js', 'utf8'), {document, Intl, Number, Math, String, Set});
  const pick = r => { r.pick.checked = true; listeners.shell.change.forEach(fn => fn({target: r.pick})); };
  const submit = () => {
    const event = {prevented: false, preventDefault() { this.prevented = true; }, stopImmediatePropagation() {}};
    listeners.batch.submit.forEach(fn => fn(event));
    return {event, sent: Object.fromEntries(appended.filter(item => !item.removed).map(item => [item.name, item.value]))};
  };
  return {batch, parts, pick, submit};
}

test('分期與平台混選：各列實際金額照使用者填的值送出，分期另送預計金額', () => {
  const platform = row({pk: 1, channel: 'platform', number: 'SO-1', actual: '61000'});
  const installment = row({pk: 2, channel: 'installment', number: 'SO-2', actual: '76000', expected: '77000'});
  const view = mount([platform, installment]);
  view.pick(installment);
  assert.equal(view.parts['[data-batch-label]'].textContent, '分期公司合併撥款');
  view.pick(platform);
  assert.equal(view.batch.hidden, false);
  assert.equal(view.parts['[data-batch-label]'].textContent, '合併入帳');
  assert.equal(view.parts['[data-batch-count]'].textContent, '2');
  assert.equal(view.parts['[data-batch-submit]'].textContent, '2 張一起入帳');
  const {event, sent} = view.submit();
  assert.equal(event.prevented, false);
  assert.deepEqual(sent, {amount_1: '61000', amount_2: '76000', expected_2: '77000'});
});

test('只勾平台列時標籤和送出內容照舊', () => {
  const platform = row({pk: 1, channel: 'platform', number: 'SO-1', actual: '61000'});
  const view = mount([platform]);
  view.pick(platform);
  assert.equal(view.parts['[data-batch-label]'].textContent, '平台合併撥款');
  assert.equal(view.parts['[data-batch-submit]'].textContent, '入帳');
  assert.deepEqual(view.submit().sent, {amount_1: '61000'});
});

test('勾選的列有空白或 0：一筆都不送，每張都標出來，訊息列出單號', () => {
  const filled = row({pk: 1, channel: 'installment', number: 'SO-1', actual: '76000', expected: '76608'});
  const blank = row({pk: 2, channel: 'installment', number: 'SO-2', actual: '', expected: '76608'});
  const zero = row({pk: 3, channel: 'platform', number: 'SO-3', actual: '0'});
  const view = mount([filled, blank, zero]);
  [filled, blank, zero].forEach(view.pick);
  const {event, sent} = view.submit();
  assert.equal(event.prevented, true);
  assert.deepEqual(sent, {});
  assert.equal(filled.actualInput.getAttribute('aria-invalid'), null);
  for (const r of [blank, zero]) {
    assert.equal(r.actualInput.getAttribute('aria-invalid'), 'true');
    assert.match(r.actualInput.validity, /SO-2、SO-3/);
  }
  assert.equal(blank.actualInput.reported, 1, '只在第一張跳出提示');
  assert.equal(zero.actualInput.reported, 0);
  assert.equal(blank.actualInput.value, '', '不自動帶入預計金額');
});
