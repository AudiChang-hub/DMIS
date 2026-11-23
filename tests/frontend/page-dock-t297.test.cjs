// T-297 右下角懸浮鈕：超過一個畫面高才出現、回到頂部附近才隱藏；「↑」回頂端並把焦點移到頁面開頭，
// 減少動態時直接跳（全站 html 是 smooth，要明確用 instant）；遇到底部固定列往上讓開。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/page-dock.js'), 'utf8');
const plainCopy = value => JSON.parse(JSON.stringify(value));  // vm 內建立的物件原型不同，比對前轉成一般物件

const classList = () => {
  const set = new Set();
  return {toggle(name, on) { if (on) set.add(name); else set.delete(name); }, contains: name => set.has(name)};
};

function loadPage({innerHeight = 800, scrollY = 0, reduce = false, obstacles = [], withDock = true} = {}) {
  const listeners = {};
  const scrolls = [];
  const focused = [];
  const frames = [];
  const main = {id: 'main-content', focus(options) { focused.push(options); document.activeElement = main; }};
  const topListeners = {};
  const topButton = {addEventListener(type, fn) { topListeners[type] = fn; }, focus() { document.activeElement = topButton; }};
  const dockStyle = {};
  const dock = {
    classList: classList(),
    style: {setProperty(name, value) { dockStyle[name] = value; }},
    querySelector: selector => (selector === '[data-page-dock-top]' ? topButton : null),
    contains: node => node === dock || node === topButton,
    getBoundingClientRect: () => ({left: 1200, right: 1400, top: innerHeight - 68, bottom: innerHeight - 20, width: 200, height: 48}),
  };
  const spacer = {hidden: true};
  const window = {
    innerHeight, scrollY,
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    requestAnimationFrame(fn) { frames.push(fn); return frames.length; },
    scrollTo(options) { scrolls.push(options); },
    matchMedia: query => ({matches: reduce && query === '(prefers-reduced-motion: reduce)'}),
    getComputedStyle: node => node.style || {position: 'static', bottom: 'auto'},
  };
  const document = {
    activeElement: null, body: {}, documentElement: {},
    querySelector(selector) {
      if (selector === '[data-page-dock]') return withDock ? dock : null;
      if (selector === '[data-page-dock-spacer]') return spacer;
      if (selector === 'main') return main;
      return null;
    },
    getElementById: id => (id === 'main-content' ? main : null),
    elementsFromPoint: () => obstacles,
  };
  vm.runInNewContext(source, {window, document, Math, Set});
  const flush = () => { while (frames.length) frames.shift()(); };
  const scrollTo = y => { window.scrollY = y; (listeners.scroll || []).forEach(fn => fn()); flush(); };
  return {dock, dockStyle, spacer, scrolls, focused, topButton, topListeners, scrollTo, main, document, window, listeners, flush};
}

test('沒有懸浮鈕的頁面不做任何事', () => {
  const page = loadPage({withDock: false});
  assert.equal(page.listeners.scroll, undefined);
});

test('超過一個畫面高才出現，門檻之內不出現', () => {
  const page = loadPage({innerHeight: 800});
  assert.equal(page.dock.classList.contains('is-shown'), false);
  page.scrollTo(800);
  assert.equal(page.dock.classList.contains('is-shown'), false, '剛好一個畫面高還不出現');
  page.scrollTo(801);
  assert.equal(page.dock.classList.contains('is-shown'), true);
  assert.equal(page.spacer.hidden, false, '出現後頁尾留空，最後一段內容不被蓋住');
});

test('回到頂部附近（半個畫面內）才隱藏，中間維持原狀不閃爍', () => {
  const page = loadPage({innerHeight: 800});
  page.scrollTo(2000);
  page.scrollTo(600);
  assert.equal(page.dock.classList.contains('is-shown'), true, '往回捲到一個畫面內仍顯示');
  page.scrollTo(401);
  assert.equal(page.dock.classList.contains('is-shown'), true);
  page.scrollTo(400);
  assert.equal(page.dock.classList.contains('is-shown'), false);
  page.scrollTo(700);
  assert.equal(page.dock.classList.contains('is-shown'), false, '隱藏後要再超過一個畫面才出現');
});

test('載入時已在下方（重新整理、回到列表捲動還原）就直接顯示', () => {
  const page = loadPage({innerHeight: 800, scrollY: 3000});
  assert.equal(page.dock.classList.contains('is-shown'), true);
});

test('↑ 一般用平滑捲動，並把焦點移到頁面開頭（不再捲一次）', () => {
  const page = loadPage();
  page.topListeners.click();
  assert.deepEqual(plainCopy(page.scrolls), [{top: 0, behavior: 'smooth'}]);
  assert.deepEqual(plainCopy(page.focused), [{preventScroll: true}]);
  assert.equal(page.document.activeElement, page.main);
});

test('↑ 在減少動態時用 instant 直接跳到頂端', () => {
  const page = loadPage({reduce: true});
  page.topListeners.click();
  assert.deepEqual(plainCopy(page.scrolls), [{top: 0, behavior: 'instant'}]);
});

test('隱藏時焦點若在懸浮鈕上，交給頁面開頭', () => {
  const page = loadPage({innerHeight: 800});
  page.scrollTo(2000);
  page.topButton.focus();
  page.scrollTo(0);
  assert.equal(page.dock.classList.contains('is-shown'), false);
  assert.equal(page.document.activeElement, page.main);
});

test('底部黏住的儲存列或固定列在下面時往上讓開；一般內容與大遮罩不算', () => {
  const bar = {style: {position: 'sticky', bottom: '12px'}, getBoundingClientRect: () => ({top: 700, bottom: 788, height: 88})};
  const savebarChild = {style: {position: 'static', bottom: 'auto'}, parentElement: bar};
  const page = loadPage({innerHeight: 800, obstacles: [savebarChild]});
  page.scrollTo(2000);
  // 懸浮鈕底在 780：讓到儲存列頂（700）上方 12px → 往上 92px。
  assert.equal(page.dockStyle['--page-dock-lift'], '92px');

  const header = {style: {position: 'sticky', bottom: 'auto'}, getBoundingClientRect: () => ({top: 700, bottom: 788, height: 88})};
  const backdrop = {style: {position: 'fixed', bottom: '0px'}, getBoundingClientRect: () => ({top: 0, bottom: 800, height: 800})};
  const plain = loadPage({innerHeight: 800, obstacles: [header, backdrop, {style: {position: 'static', bottom: 'auto'}}]});
  plain.scrollTo(2000);
  assert.equal(plain.dockStyle['--page-dock-lift'], '0px');
});
