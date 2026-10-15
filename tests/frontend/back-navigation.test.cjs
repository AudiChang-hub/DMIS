const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/ui-navigation.js'), 'utf8');

const sessionStore = () => {
  const data = new Map();
  return {getItem: key => (data.has(key) ? data.get(key) : null), setItem: (key, value) => data.set(key, String(value)), removeItem: key => data.delete(key)};
};

// 在指定網址載入 ui-navigation.js；同一個 sessionStorage 代表同一個瀏覽器分頁。
function loadPage(href, {storage, links = [], historyBack = [], referrer = '', scrollY = 0} = {}) {
  const location = new URL(href);
  const listeners = {};
  const scrolled = [];
  const assigned = [];
  const history = {
    length: 2, backCalls: 0,
    back() { this.backCalls += 1; },
    pushState(state, title, url) { const next = new URL(url, location.href); location.search = next.search; location.pathname = next.pathname; },
    replaceState(state, title, url) { this.pushState(state, title, url); },
  };
  const window = {
    location, history, sessionStorage: storage, scrollY,
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    scrollTo(options) { scrolled.push(options); },
    requestAnimationFrame(fn) { fn(); },
  };
  location.assign = url => assigned.push(url);
  const document = {
    readyState: 'complete', referrer,
    querySelector: () => null,
    querySelectorAll(selector) {
      if (selector === 'a[data-return-to]') return links;
      if (selector === '[data-history-back]') return historyBack;
      return [];
    },
  };
  vm.runInNewContext(source, {window, document, URL, URLSearchParams, JSON, Math});
  return {window, listeners, scrolled, assigned, fire: type => (listeners[type] || []).forEach(fn => fn())};
}

const returnLink = href => ({
  href, attrs: {href}, handlers: {},
  getAttribute(name) { return this.attrs[name]; },
  addEventListener(type, fn) { this.handlers[type] = fn; },
});

test('返回列帶回列表上次的篩選，不帶編輯中等一次性參數', () => {
  const storage = sessionStore();
  loadPage('https://dmis.test/orders/?status=active&q=王&edit=3', {storage});

  const back = returnLink('/orders/');
  loadPage('https://dmis.test/orders/12/', {storage, links: [back]});

  assert.equal(back.href, '/orders/?status=active&q=%E7%8E%8B');
});

test('分頁籤以 pushState 改篩選時，記住最新的篩選', () => {
  const storage = sessionStore();
  const list = loadPage('https://dmis.test/orders/', {storage});
  list.window.history.pushState({}, '', '/orders/?status=closed&page=3');

  const back = returnLink('/orders/');
  loadPage('https://dmis.test/orders/12/', {storage, links: [back]});
  assert.equal(back.href, '/orders/?status=closed&page=3');
});

test('從主選單回到沒有篩選的列表後，返回列也不再帶舊篩選', () => {
  const storage = sessionStore();
  loadPage('https://dmis.test/orders/?status=active', {storage});
  loadPage('https://dmis.test/orders/', {storage});

  const back = returnLink('/orders/');
  loadPage('https://dmis.test/orders/12/', {storage, links: [back]});
  assert.equal(back.href, '/orders/');
});

test('連結本身已指定條件時不覆寫', () => {
  const storage = sessionStore();
  loadPage('https://dmis.test/reports/sales/?month=2026-09', {storage});

  const back = returnLink('/reports/sales/?month=2026-10');
  loadPage('https://dmis.test/reports/sales/detail/', {storage, links: [back]});
  assert.equal(back.href, '/reports/sales/?month=2026-10');
});

test('經由返回列回到列表時回到離開前的捲動位置；直接進入列表則停在頁首', () => {
  const storage = sessionStore();
  const list = loadPage('https://dmis.test/orders/?status=active', {storage, scrollY: 1480});
  list.fire('pagehide');

  const back = returnLink('/orders/');
  loadPage('https://dmis.test/orders/12/', {storage, links: [back]});
  back.handlers.click();

  const returned = loadPage('https://dmis.test/orders/?status=active', {storage});
  assert.ok(returned.scrolled.length > 0);
  assert.ok(returned.scrolled.every(options => options.top === 1480 && options.behavior === 'instant'));

  const direct = loadPage('https://dmis.test/orders/?status=active', {storage});
  assert.deepEqual(direct.scrolled, []);
});

test('錯誤頁的返回上一頁：有本站上一頁才退回，否則回首頁', () => {
  const button = {dataset: {fallbackUrl: '/'}, addEventListener(type, fn) { this.click = fn; }};
  const withReferrer = loadPage('https://dmis.test/missing/', {storage: sessionStore(), historyBack: [button], referrer: 'https://dmis.test/orders/'});
  button.click();
  assert.equal(withReferrer.window.history.backCalls, 1);

  const external = loadPage('https://dmis.test/missing/', {storage: sessionStore(), historyBack: [button], referrer: 'https://other.example/'});
  button.click();
  assert.equal(external.window.history.backCalls, 0);
  assert.deepEqual(external.assigned, ['https://dmis.test/']);
});
