// T-291 從哪來回哪去：來源頁的連結補 back_to，目的頁的篩選、分頁與 pushState 一路帶著來源。
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

const makeLink = (href, attrs = {}, inMain = true) => ({
  attrs: {href, ...attrs}, inMain,
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; },
  setAttribute(name, value) { this.attrs[name] = String(value); },
  hasAttribute(name) { return name in this.attrs; },
  closest(selector) { return selector === 'a[href]' && this.attrs.href !== undefined ? this : null; },
});

const makeForm = (attrs = {}, fields = []) => ({
  attrs, inMain: true, tagName: 'FORM', elements: fields.map(name => ({name})), appended: [],
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; },
  appendChild(node) { this.appended.push(node); this.elements.push(node); },
});

function loadPage(href, {isSource = false, forms = []} = {}) {
  const location = new URL(href);
  const listeners = {};
  const pushed = [];
  const history = {
    length: 2,
    pushState(state, title, url) { pushed.push(String(url)); const next = new URL(url, location.href); location.search = next.search; location.pathname = next.pathname; },
    replaceState(state, title, url) { this.pushState(state, title, url); },
  };
  const window = {
    location, history, sessionStorage: sessionStore(), scrollY: 0,
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    scrollTo() {}, requestAnimationFrame(fn) { fn(); },
  };
  const main = {contains: node => Boolean(node && node.inMain)};
  const document = {
    readyState: 'complete', referrer: '',
    querySelector(selector) {
      if (selector === 'main[data-link-source]') return isSource ? main : null;
      if (selector === 'main') return main;
      return null;
    },
    querySelectorAll(selector) { return selector === 'main form' ? forms : []; },
    createElement: () => ({}),
  };
  vm.runInNewContext(source, {window, document, URL, URLSearchParams, JSON, Math});
  const click = (link, type = 'click') => (listeners[type] || []).forEach(fn => fn({target: link}));
  const submit = form => (listeners.submit || []).forEach(fn => fn({target: form}));
  return {window, click, submit, pushed};
}

const param = (href, name = 'back_to') => new URL(href, 'https://dmis.test').searchParams.get(name);

test('來源頁點往其他頁的連結帶上目前路徑與期間，一次性參數不帶', () => {
  const page = loadPage('https://dmis.test/operations/?period=quarter&saved=1', {isSource: true});
  const link = makeLink('/data/inventory/?model=3');
  page.click(link);
  assert.equal(param(link.attrs.href), '/operations/?period=quarter');
  assert.equal(param(link.attrs.href, 'model'), '3');
});

test('中鍵或右鍵另開分頁也帶來源', () => {
  const page = loadPage('https://dmis.test/operations/', {isSource: true});
  const middle = makeLink('/orders/?attention=dealer');
  const context = makeLink('/data/inventory/');
  page.click(middle, 'mousedown');
  page.click(context, 'contextmenu');
  assert.equal(param(middle.attrs.href), '/operations/');
  assert.equal(param(context.attrs.href), '/operations/');
});

test('pushState 換了期間後，點連結帶最新的期間', () => {
  const page = loadPage('https://dmis.test/operations/?period=month', {isSource: true});
  page.window.history.pushState(null, '', '/operations/?period=year');
  const link = makeLink('/data/inventory/');
  page.click(link);
  assert.equal(param(link.attrs.href), '/operations/?period=year');
});

test('非來源頁、主內容外、錨點、下載、返回列與已有來源的連結都不動', () => {
  const plain = loadPage('https://dmis.test/help/');
  const other = makeLink('/data/inventory/');
  plain.click(other);
  assert.equal(other.attrs.href, '/data/inventory/');

  const page = loadPage('https://dmis.test/operations/', {isSource: true});
  const cases = [
    makeLink('/data/inventory/', {}, false),
    makeLink('#ops-stock-title'),
    makeLink('/operations/export/', {download: ''}),
    makeLink('/', {'data-return-to': ''}),
    makeLink('/orders/?back_to=%2Fdata%2F'),
    makeLink('/static/css/app.css'),
    makeLink('https://example.com/'),
    makeLink('/operations/?period=year'),
  ];
  const before = cases.map(link => link.attrs.href);
  cases.forEach(link => page.click(link));
  assert.deepEqual(cases.map(link => link.attrs.href), before);
});

test('目的頁連回自己的來源時不再疊一層，往更深的頁面帶上目前頁（含來源）', () => {
  const page = loadPage('https://dmis.test/data/inventory/?back_to=%2Foperations%2F', {isSource: true});
  const toSource = makeLink('/operations/');
  const deeper = makeLink('/data/inventory/5/edit/');
  page.click(toSource);
  page.click(deeper);
  assert.equal(toSource.attrs.href, '/operations/');
  assert.equal(param(deeper.attrs.href), '/data/inventory/?back_to=%2Foperations%2F');
});

test('目的頁的同頁篩選表單補上來源，POST 與送往他頁的表單不動', () => {
  const filter = makeForm({method: 'get'});
  const noAction = makeForm({});
  const already = makeForm({method: 'get'}, ['back_to']);
  const post = makeForm({method: 'post'});
  const elsewhere = makeForm({method: 'get', action: '/orders/'});
  loadPage('https://dmis.test/data/inventory/?status=active&back_to=%2Foperations%2F%3Fperiod%3Dmonth', {forms: [filter, noAction, already, post, elsewhere]});
  assert.deepEqual(filter.appended.map(node => [node.type, node.name, node.value]), [['hidden', 'back_to', '/operations/?period=month']]);
  assert.equal(noAction.appended.length, 1);
  assert.equal(already.appended.length, 0);
  assert.equal(post.appended.length, 0);
  assert.equal(elsewhere.appended.length, 0);
});

test('之後才插入的篩選表單送出時也補上來源', () => {
  const page = loadPage('https://dmis.test/orders/?back_to=%2Foperations%2F');
  const late = makeForm({method: 'get'});
  page.submit(late);
  assert.equal(late.appended[0].value, '/operations/');
});

test('目的頁的分頁、排序、清除篩選連結與 pushState 保留來源', () => {
  const page = loadPage('https://dmis.test/orders/?attention=dealer&back_to=%2Foperations%2F');
  const next = makeLink('?attention=dealer&page=2');
  const clear = makeLink('/orders/');
  page.click(next);
  page.click(clear);
  assert.equal(param(next.attrs.href), '/operations/');
  assert.equal(param(next.attrs.href, 'page'), '2');
  assert.equal(param(clear.attrs.href), '/operations/');

  page.window.history.pushState(null, '', '/orders/?status=done');
  assert.equal(param(page.pushed.at(-1)), '/operations/');
  assert.equal(param(page.pushed.at(-1), 'status'), 'done');
});

test('網址沒有來源時，同頁連結、表單與 pushState 都不變', () => {
  const filter = makeForm({method: 'get'});
  const page = loadPage('https://dmis.test/orders/?status=active', {forms: [filter]});
  const next = makeLink('?status=active&page=2');
  page.click(next);
  page.window.history.pushState(null, '', '/orders/?status=done');
  assert.equal(next.attrs.href, '?status=active&page=2');
  assert.equal(filter.appended.length, 0);
  assert.equal(page.pushed.at(-1), '/orders/?status=done');
});
