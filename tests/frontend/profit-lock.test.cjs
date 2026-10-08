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

const flush = () => new Promise(resolve => setImmediate(resolve));

function unlockEnv({until, now = 1000, replies = []}) {
  let clock = now;
  const events = {}, timers = [], values = [], fetchCalls = [], dispatched = [];
  const profit = {replaceChildren: (...items) => values.push(items)};
  const body = {dataset: {unlockUntil: String(until), unlockTouchUrl: '/account/unlock/touch/', unlockCsrf: 'tok'}};
  const document = {body, addEventListener: (name, fn) => events[name] = fn,
    createTextNode: text => text, createElement: () => ({}),
    dispatchEvent: event => dispatched.push(event.type),
    querySelectorAll: selector => selector === '[data-profit-value]' ? [profit] : []};
  const fetchStub = (url, options) => {
    fetchCalls.push({url, options});
    const reply = replies.shift();
    return Promise.resolve({json: () => Promise.resolve(reply)});
  };
  vm.runInNewContext(fs.readFileSync('static/js/profit-lock.js', 'utf8'), {
    document, Date: {now: () => clock}, fetch: fetchStub, Promise,
    setTimeout: (fn, ms) => { timers.push({fn, ms}); return timers.length; }, clearTimeout() {},
    CustomEvent: class { constructor(type) { this.type = type; } },
    location: {pathname: '/orders/', search: ''},
    window: {addEventListener: (name, fn) => events[`window:${name}`] = fn}, encodeURIComponent
  });
  return {events, timers, values, fetchCalls, dispatched, body, setNow: value => { clock = value; }};
}

test('真人操作會延長閒置期限，同一頁每分鐘最多通知一次', async () => {
  const T = 10000000;  // 接近真實的 Date.now() 量級，節流才會正確
  const env = unlockEnv({until: T + 100000, now: T + 50000, replies: [{ok: true, until: T + 650000}, {ok: true, until: T + 720000}]});
  env.events.pointerdown();
  assert.equal(env.fetchCalls.length, 1);
  assert.equal(env.fetchCalls[0].options.method, 'POST');
  assert.equal(env.fetchCalls[0].options.headers['X-CSRFToken'], 'tok');
  await flush();
  assert.equal(env.body.dataset.unlockUntil, String(T + 650000));
  assert.equal(env.timers.at(-1).ms, 650000 - 50000);  // 遮蔽計時已重新排定到新的期限
  env.setNow(T + 80000); env.events.keydown();
  assert.equal(env.fetchCalls.length, 1);              // 30 秒內不重複通知
  env.setNow(T + 111000); env.events.keydown();
  assert.equal(env.fetchCalls.length, 2);
});

test('已過期後的操作不再嘗試延長（不能復活）', async () => {
  const T = 10000000;
  const env = unlockEnv({until: T + 100000, now: T + 50000});
  env.setNow(T + 100001);
  env.events.pointerdown(); env.events.scroll(); env.events.touchstart();
  assert.equal(env.fetchCalls.length, 0);
});

test('到期時先向伺服器確認：其他分頁已延長就不遮蔽', async () => {
  const env = unlockEnv({until: 100000, now: 50000, replies: [{ok: true, until: 900000}]});
  env.setNow(100001);
  env.timers[0].fn();
  assert.equal(env.fetchCalls[0].options.method, undefined);  // 只查詢，不延長
  await flush();
  assert.equal(env.values.length, 0);
  assert.equal(env.body.dataset.unlockUntil, '900000');
});

test('伺服器確認已過期才遮蔽，並通知其他程式遮回已顯示的資料', async () => {
  const env = unlockEnv({until: 100000, now: 50000, replies: [{ok: false, locked: true}]});
  env.setNow(100001);
  env.timers[0].fn();
  await flush();
  assert.equal(env.values[0][0], '已鎖定');
  assert.deepEqual(env.dispatched, ['dmis:unlock-expired']);
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
