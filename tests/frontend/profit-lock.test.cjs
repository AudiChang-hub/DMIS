const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('到期只遮蔽淨利，保留整頁與未儲存表單，不自動重載', () => {
  let now = 1000, timer;
  const events = {}, values = [], controls = [], removed = [];
  const profit = {replaceChildren: (...items) => values.push(items)};
  const control = {replaceChildren: (...items) => controls.push(items)};
  const sort = {removeAttribute: name => removed.push(name)};
  const body = {dataset: {profitUntil: '2000'}, replaceChildren() {throw Error('不應取代 body');}};
  const document = {body, addEventListener: (name, fn) => events[name] = fn,
    createTextNode: text => text, createElement: () => ({}),
    querySelectorAll: selector => {
      if (selector === '[data-profit-value]') return [profit];
      if (selector === '[data-order-sort-key="profit"]') return [sort];
      if (selector === '.profit-control[data-profit-until]') return [control];
      throw Error(`未預期的範圍 ${selector}`);
    }};
  vm.runInNewContext(fs.readFileSync('static/js/profit-lock.js', 'utf8'), {
    document, Date: {now: () => now}, setTimeout: fn => timer = fn,
    location: {pathname: '/orders/', search: '?sort=-profit', reload() {throw Error('不得重載');}},
    window: {addEventListener: (name, fn) => events[name] = fn}, encodeURIComponent
  });
  events.pageshow(); assert.equal(values.length, 0);
  now = 2001; timer();
  assert.equal(values[0][0], '已鎖定');
  assert.deepEqual(removed, ['href', 'data-order-sort-key']);
  assert.match(controls[0][0].textContent, /未儲存/);
  assert.match(controls[0][1].href, /profit\/unlock/);
  events.visibilitychange(); assert.equal(values.length, 2);
});

test('新增與動態插入帳密欄位保留 autocomplete 提示', () => {
  const source = fs.readFileSync('static/js/recent-field-values.js', 'utf8');
  const start = source.indexOf('  function disableNativeAutocomplete(');
  const end = source.indexOf('  function normalizedFieldName(', start);
  const run = vm.runInNewContext(`(function(root) { const EXCLUDED_NAME = /username|password/i; ${source.slice(start, end)} disableNativeAutocomplete(root); })`);
  const field = (name, type, autocomplete) => ({name, type, autocomplete,
    getAttribute() {return this.autocomplete;}, setAttribute(k, v) {this[k] = v;},
    querySelectorAll() {return [];}, matches() {return true;}});
  const username = field('username', 'text', 'section-new-dealer username');
  const password = field('credential', 'password', 'new-password');
  const ordinary = field('note', 'text', '');
  run({querySelectorAll: () => [username, password, ordinary]});
  run(password);
  assert.equal(username.autocomplete, 'section-new-dealer username');
  assert.equal(password.autocomplete, 'new-password');
  assert.equal(ordinary.autocomplete, 'off');
});
