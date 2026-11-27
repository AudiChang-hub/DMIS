// T-322：車行／平台頁的熱度格，有數字的格子可以點，從側邊看那一格的訂單。
// 這裡用最小的假 DOM 驗證：格子怎麼變成按鈕、空白格不能點、開、關、鍵盤、換格子、載入失敗的畫面。
const test = require('node:test');
const assert = require('node:assert/strict');
const heat = require('../../static/js/report-heat.js');
const {reportHeatCellLabel, reportHeatCellUrl, reportHeatNeighbor, reportHeatFailure, createReportHeatDrawer, initReportHeatDrawer} = heat;

/* ── 最小假 DOM ── */
class El {
  constructor(tag, doc) {
    this.tagName = tag.toUpperCase(); this.ownerDocument = doc; this.children = []; this.parent = null; this.attrs = {}; this.dataset = {};
    this.listeners = {}; this.className = ''; this.text = ''; this.hidden = false; this.tabIndex = -1; this.style = {setProperty() {}};
    const self = this;
    this.classList = {
      add: (...names) => { self.className = [...new Set([...self.className.split(' ').filter(Boolean), ...names])].join(' '); },
      remove: (...names) => { self.className = self.className.split(' ').filter(name => name && !names.includes(name)).join(' '); },
      contains: name => self.className.split(' ').includes(name),
    };
  }
  get childNodes() { return this.children; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.children.forEach(child => { child.parent = null; }); this.children = []; this.text = String(value); }
  append(...nodes) { nodes.forEach(node => { if (typeof node === 'string') { this.text += node; return; } node.parent = this; this.children.push(node); }); }
  replaceChildren(...nodes) { this.children.forEach(child => { child.parent = null; }); this.children = []; this.text = ''; this.append(...nodes); }
  before(node) { node.parent = this.parent; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
  hasAttribute(name) { return name in this.attrs; }
  removeAttribute(name) { delete this.attrs[name]; }
  addEventListener(type, handler) { (this.listeners[type] = this.listeners[type] || []).push(handler); }
  get isConnected() { let node = this; while (node.parent) node = node.parent; return node === this.ownerDocument.body; }
  contains(node) { for (let current = node; current; current = current.parent) if (current === this) return true; return false; }
  matches(selector) { const key = /^\[data-([a-z-]+)\]$/.exec(selector); return Boolean(key) && key[1].replace(/-(\w)/g, (_m, letter) => letter.toUpperCase()) in this.dataset; }
  closest(selector) { for (let current = this; current; current = current.parent) if (current.matches(selector)) return current; return null; }
  querySelectorAll(selector) { const found = []; const walk = node => node.children.forEach(child => { if (child.matches(selector)) found.push(child); walk(child); }); walk(this); return found; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  focus() { this.ownerDocument.activeElement = this; this.closest('[data-heat-cell]') && bubble(this, 'focusin', {}); }
}
function bubble(target, type, init) {
  const path = []; for (let node = target; node; node = node.parent) path.push(node);
  const event = {type, target, defaultPrevented: false, stopped: false, composedPath: () => path,
    preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }, ...init};
  const doc = target.ownerDocument;
  (doc.captures[type] || []).forEach(handler => handler(event));
  if (event.stopped) return event;
  for (const node of path) { (node.listeners[type] || []).slice().forEach(handler => handler(event)); if (event.stopped) return event; }
  (doc.bubbles[type] || []).forEach(handler => handler(event));
  return event;
}
function page() {
  const doc = {captures: {}, bubbles: {}, activeElement: null,
    createElement(tag) { return new El(tag, doc); },
    addEventListener(type, handler, capture) { const store = capture ? doc.captures : doc.bubbles; (store[type] = store[type] || []).push(handler); },
    importNode: node => node};
  doc.body = new El('body', doc); doc.activeElement = doc.body;
  const calls = [];
  // 逾時計時器不擋住測試結束（被取代的請求在假 fetch 裡不會自己結束）。
  const win = {AbortController, setTimeout: (handler, wait) => { const timer = setTimeout(handler, wait); timer.unref(); return timer; }, clearTimeout, calls, reloaded: 0,
    location: {href: 'https://dmis.test/reports/8/?months=2026-11', reload() { win.reloaded += 1; }},
    addEventListener(type, handler) { win[`on${type}`] = handler; },
    DOMParser: class { parseFromString(html) {
      const match = /data-cell-count="(\d+)"/.exec(html);
      return {querySelector: () => { if (!match) return null; const node = doc.createElement('div'); node.dataset.cellOrders = ''; node.dataset.cellCount = match[1]; node.text = html; return node; }};
    } },
    fetch(url, options) { return new Promise((resolve, reject) => { calls.push({url, options, resolve, reject}); }); }};
  return {doc, win};
}
const ok = count => ({ok: true, status: 200, redirected: false, text: async () => `<div data-cell-orders data-cell-count="${count}">訂單 ${count} 張</div>`});
const settle = () => new Promise(resolve => setImmediate(resolve));
function cellButton(doc, {label = '示範車行甲', month = '2026/11', value = 3, group = 'c%3A%5B%22v%3A1%22%2C%222026-11-01%22%5D'} = {}) {
  const button = doc.createElement('button');
  Object.assign(button.dataset, {heatCell: `/reports/8/charts/0/orders/?months=2026-11&revision=r1&group=${group}`, heatLabel: label, heatMonth: month,
    heatValue: String(value), heatUnit: ' 張', heatChart: '油車車行每月銷售'});
  button.setAttribute('aria-expanded', 'false');
  doc.body.append(button);
  return button;
}

/* ── 純函式 ── */
test('格子的讀屏名稱寫出哪一家、哪個月、幾張', () => {
  assert.equal(reportHeatCellLabel('示範車行甲', '2026/11', '3', ' 張'), '示範車行甲 2026 年 11 月 3 張，看明細');
  assert.equal(reportHeatCellLabel('合成平台', '2025/04', '1,204', ''), '合成平台 2025 年 4 月 1,204，看明細');
});

test('片段網址＝原本那一段的下鑽連結再加 inline、view，其他條件原樣帶著', () => {
  const url = new URL(reportHeatCellUrl('/reports/8/charts/0/orders/?months=2026-09&months=2026-11&revision=r1&group=c%3A%5B1%2C2%5D', 'https://dmis.test/reports/8/'));
  assert.equal(url.pathname, '/reports/8/charts/0/orders/');
  assert.deepEqual(url.searchParams.getAll('months'), ['2026-09', '2026-11']);
  assert.equal(url.searchParams.get('group'), 'c:[1,2]');
  assert.equal(url.searchParams.get('revision'), 'r1');
  assert.equal(url.searchParams.get('inline'), '1');
  assert.equal(url.searchParams.get('view'), 'cell');
});

test('方向鍵：左右留在同一列，上下到最近一列最靠近的欄', () => {
  const cells = [{row: 0, col: 0}, {row: 0, col: 3}, {row: 0, col: 5}, {row: 2, col: 4}, {row: 2, col: 9}, {row: 3, col: 3}];
  assert.equal(reportHeatNeighbor(cells, 1, 'ArrowRight'), 2);
  assert.equal(reportHeatNeighbor(cells, 1, 'ArrowLeft'), 0);
  assert.equal(reportHeatNeighbor(cells, 0, 'ArrowLeft'), -1);     // 已經在最左
  assert.equal(reportHeatNeighbor(cells, 1, 'ArrowDown'), 3);      // 第 1 列沒有按鈕，跳到第 2 列最近的欄
  assert.equal(reportHeatNeighbor(cells, 3, 'ArrowDown'), 5);
  assert.equal(reportHeatNeighbor(cells, 5, 'ArrowDown'), -1);
  assert.equal(reportHeatNeighbor(cells, 4, 'ArrowUp'), 2);
  assert.equal(reportHeatNeighbor(cells, 2, 'Home'), 0);
  assert.equal(reportHeatNeighbor(cells, 0, 'End'), 2);
  assert.equal(reportHeatNeighbor(cells, 1, 'Enter'), -1);         // 其他鍵不攔
});

test('載入不成功：沒有權限、報表已更新、登入逾時、等太久、其他錯誤各有畫面', () => {
  assert.equal(reportHeatFailure({status: 403}).kind, 'denied');
  assert.equal(reportHeatFailure({status: 404}).kind, 'denied');
  assert.equal(reportHeatFailure({status: 403}).retry, undefined);                 // 沒有權限不給「再試一次」
  assert.deepEqual([reportHeatFailure({status: 409}).kind, reportHeatFailure({status: 409}).reload], ['stale', true]);
  assert.equal(reportHeatFailure({status: 200, redirected: true}).kind, 'login');
  assert.deepEqual([reportHeatFailure({status: 500}).kind, reportHeatFailure({status: 500}).retry], ['error', true]);
  assert.equal(reportHeatFailure(null, new TypeError('network')).kind, 'error');
  assert.equal(reportHeatFailure(null, {name: 'AbortError'}).kind, 'timeout');
});

/* ── 格子變按鈕 ── */
function chartStub(doc, {links = true} = {}) {
  // 車行版：每列一家車行、細分是月份。示範車行甲 2026/09＝2、2026/11＝3；示範車行乙只有 2026/09＝1。
  const segment = (label, value, key) => ({dataset: {seriesLabel: label, pointValue: String(value)},
    querySelector: () => (links ? {getAttribute: () => `/reports/8/charts/0/orders/?revision=r1&group=${key}`} : null)});
  const group = (name, segments) => ({querySelector: () => ({textContent: name}), querySelectorAll: () => segments});
  const groups = [group('示範車行甲', [segment('2026/11', 3, 'A11'), segment('2026/09', 2, 'A09')]), group('示範車行乙', [segment('2026/09', 1, 'B09')])];
  const rows = [{dataset: {pointValue: '5'}, querySelector: () => null}, {dataset: {pointValue: '1'}, querySelector: () => null}];
  const stacks = new El('div', doc); doc.body.append(stacks);
  let wrap = null; stacks.before = node => { wrap = node; doc.body.append(node); };
  const chart = {ownerDocument: doc, dataset: {dimension: 'legacy_dealer', series: 'month', metricLabel: '訂單台數', total: '6'}, classList: {add() {}},
    querySelectorAll: selector => (selector === '.report-stack-row' ? groups : selector.startsWith('.report-results') ? rows : []),
    querySelector: selector => (selector === 'h2' ? {textContent: '油車車行每月銷售'} : selector === '.report-stacks' ? stacks : null)};
  return {chart, box: () => wrap.querySelector('[data-heat-cell]') && wrap, wrapper: () => wrap};
}

test('有數字的格子是按鈕、空白格不是；整張表只有一個 Tab 停點', () => {
  const {doc} = page();
  const {chart, wrapper} = chartStub(doc);
  assert.equal(heat.renderReportHeat(chart, {currentMonth: '2026/11'}), true);
  const buttons = wrapper().querySelectorAll('[data-heat-cell]');
  // 月份補成連續的 2026/09、10、11：示範車行甲 09、11 有數字，10 是空白；示範車行乙只有 09。
  assert.deepEqual(buttons.map(button => `${button.dataset.heatLabel} ${button.dataset.heatMonth} ${button.textContent}`), ['示範車行甲 2026/09 2', '示範車行甲 2026/11 3', '示範車行乙 2026/09 1']);
  assert.ok(buttons.every(button => button.tagName === 'BUTTON' && button.type === 'button'));
  assert.equal(buttons[1].getAttribute('aria-label'), '示範車行甲 2026 年 11 月 3 張，看明細');
  assert.equal(buttons[1].getAttribute('aria-haspopup'), 'dialog');
  assert.match(buttons[1].dataset.heatCell, /group=A11$/);
  assert.deepEqual(buttons.map(button => button.tabIndex), [0, -1, -1]);
  const cells = [];
  const walk = node => node.children.forEach(child => { if (child.className.split(' ').includes('report-heat__cell')) cells.push(child); walk(child); });
  walk(wrapper());
  assert.equal(cells.length, 6);                                              // 2 家 × 3 個月
  const empty = cells.filter(cell => !cell.querySelector('[data-heat-cell]'));
  assert.equal(empty.length, 3);                                              // 空白格：沒有按鈕、沒有數字
  assert.ok(empty.every(cell => cell.textContent === '' && cell.getAttribute('role') === 'cell'));
  // 方向鍵移動焦點，Tab 停點跟著走
  buttons[0].focus();
  const right = bubble(buttons[0], 'keydown', {key: 'ArrowRight'});
  assert.equal(right.defaultPrevented, true);
  assert.equal(doc.activeElement, buttons[1]);
  assert.deepEqual(buttons.map(button => button.tabIndex), [-1, 0, -1]);
  bubble(buttons[1], 'keydown', {key: 'ArrowDown'});
  assert.equal(doc.activeElement, buttons[2]);
  assert.equal(bubble(buttons[2], 'keydown', {key: 'Enter'}).defaultPrevented, false);   // Enter／空白鍵交給按鈕本身
});

test('沒有下鑽連結（預覽、沒有權限）時，格子照舊只顯示數字', () => {
  const {doc} = page();
  const {chart, wrapper} = chartStub(doc, {links: false});
  heat.renderReportHeat(chart, {});
  assert.equal(wrapper().querySelectorAll('[data-heat-cell]').length, 0);
  assert.match(wrapper().textContent, /示範車行甲/);
});

/* ── 面板：開、關、鍵盤、換格子 ── */
test('點格子：面板滑出、標題寫哪一家哪個月共幾張，焦點進面板，載入那一格的訂單', async () => {
  const {doc, win} = page();
  initReportHeatDrawer(doc, win);
  const cell = cellButton(doc);
  const event = bubble(cell, 'click', {});
  assert.equal(event.defaultPrevented, true);
  const drawer = doc.body.children.find(node => node.classList.contains('report-cell-drawer'));
  assert.ok(drawer.classList.contains('is-open'));
  assert.equal(drawer.hasAttribute('inert'), false);
  assert.equal(drawer.getAttribute('role'), 'dialog');
  assert.equal(drawer.dataset.state, 'loading');
  assert.equal(drawer.getAttribute('aria-busy'), 'true');
  assert.match(drawer.textContent, /油車車行每月銷售示範車行甲2026 年 11 月共 3 張/);
  assert.equal(cell.getAttribute('aria-expanded'), 'true');
  assert.equal(doc.activeElement.id, 'report-cell-drawer-title');
  assert.equal(win.calls.length, 1);
  const url = new URL(win.calls[0].url);
  assert.equal(url.searchParams.get('inline'), '1');
  assert.equal(url.searchParams.get('view'), 'cell');
  assert.equal(url.searchParams.get('group'), 'c:["v:1","2026-11-01"]');
  assert.equal(url.searchParams.get('months'), '2026-11');           // 篩選條件原樣帶著
  assert.equal(win.calls[0].options.credentials, 'same-origin');
  win.calls[0].resolve(ok(3)); await settle();
  assert.equal(drawer.dataset.state, 'ready');
  assert.equal(drawer.hasAttribute('aria-busy'), false);
  assert.match(drawer.textContent, /共 3 張/);
  assert.match(drawer.textContent, /訂單 3 張/);
  assert.doesNotMatch(drawer.textContent, /打開報表時的數字/);       // 筆數和格子一樣就不多說
});

test('關閉鈕、Esc、點面板外都能關；焦點回到原本的格子', async () => {
  const {doc, win} = page();
  initReportHeatDrawer(doc, win);
  const cell = cellButton(doc);
  const find = () => doc.body.children.find(node => node.classList.contains('report-cell-drawer'));
  const isOpen = () => find().classList.contains('is-open');
  // 關閉鈕
  bubble(cell, 'click', {}); win.calls.at(-1).resolve(ok(3)); await settle();
  const close = find().children[0].children[1];
  assert.equal(close.getAttribute('aria-label'), '關閉訂單明細');
  bubble(close, 'click', {});
  assert.equal(isOpen(), false);
  assert.equal(find().hasAttribute('inert'), true);
  assert.equal(cell.getAttribute('aria-expanded'), 'false');
  assert.equal(doc.activeElement, cell);
  // Esc：只關面板，不往下傳
  bubble(cell, 'click', {});
  const escape = bubble(doc.activeElement, 'keydown', {key: 'Escape'});
  assert.equal(escape.stopped, true);
  assert.equal(isOpen(), false);
  assert.equal(doc.activeElement, cell);
  assert.equal(bubble(cell, 'keydown', {key: 'Escape'}).stopped, false);   // 面板沒開時不攔 Esc
  // 點面板外的空白處：關，焦點還給格子
  bubble(cell, 'click', {});
  doc.activeElement = doc.body;
  bubble(doc.body, 'click', {});
  assert.equal(isOpen(), false);
  assert.equal(doc.activeElement, cell);
  // 點面板外的另一個控制項：關，焦點留在使用者點的地方
  const other = doc.createElement('a'); doc.body.append(other);
  bubble(cell, 'click', {});
  doc.activeElement = other;
  bubble(other, 'click', {});
  assert.equal(isOpen(), false);
  assert.equal(doc.activeElement, other);
  // 點面板裡面：不關
  bubble(cell, 'click', {});
  bubble(find().children[2], 'click', {});
  assert.equal(isOpen(), true);
});

test('點面板外：焦點落在 tabindex="-1" 的 main 也還給格子；點到別的控制項焦點留在那個控制項', () => {
  const {doc, win} = page();
  initReportHeatDrawer(doc, win);
  const main = doc.createElement('main'); main.setAttribute('id', 'main-content'); main.setAttribute('tabindex', '-1'); doc.body.append(main);
  const blank = doc.createElement('div'); main.append(blank);
  const cell = doc.createElement('button');
  Object.assign(cell.dataset, {heatCell: '/reports/8/charts/0/orders/?group=A11', heatLabel: '示範車行甲', heatMonth: '2026/11', heatValue: '3', heatUnit: ' 張', heatChart: '油車車行每月銷售'});
  main.append(cell);
  const isOpen = () => doc.body.children.find(node => node.classList.contains('report-cell-drawer')).classList.contains('is-open');
  // 點 main 裡的空白處：瀏覽器把焦點放到 main（tabindex="-1"），仍要回到格子
  bubble(cell, 'click', {});
  doc.activeElement = main;
  bubble(blank, 'click', {});
  assert.equal(isOpen(), false);
  assert.equal(doc.activeElement, cell);
  // 焦點落在其他 tabindex 為負的區塊也一樣回到格子
  const region = doc.createElement('section'); region.setAttribute('tabindex', '-2'); main.append(region);
  bubble(cell, 'click', {});
  doc.activeElement = region;
  bubble(region, 'click', {});
  assert.equal(doc.activeElement, cell);
  // 點另一個按鈕（點在按鈕裡的文字上）：焦點留在那個按鈕
  const other = doc.createElement('button'); const label = doc.createElement('span'); other.append(label); main.append(other);
  bubble(cell, 'click', {});
  doc.activeElement = other;
  bubble(label, 'click', {});
  assert.equal(isOpen(), false);
  assert.equal(doc.activeElement, other);
  // 瀏覽器點連結時沒有給焦點（焦點還在面板或 body）：焦點移到使用者點的連結，不搶回格子
  const link = doc.createElement('a'); link.setAttribute('href', '/orders/'); main.append(link);
  bubble(cell, 'click', {});
  assert.equal(doc.activeElement.id, 'report-cell-drawer-title');
  bubble(link, 'click', {});
  assert.equal(isOpen(), false);
  assert.equal(doc.activeElement, link);
  // tabindex="-1" 的按鈕仍是控制項（例如用方向鍵切換的工具列），焦點留在那裡
  const roving = doc.createElement('button'); roving.setAttribute('tabindex', '-1'); main.append(roving);
  bubble(cell, 'click', {});
  doc.activeElement = roving;
  bubble(roving, 'click', {});
  assert.equal(doc.activeElement, roving);
});

test('面板開著再點別的格子：直接換內容，先前那一格較晚回來的資料不會蓋掉', async () => {
  const {doc, win} = page();
  initReportHeatDrawer(doc, win);
  const first = cellButton(doc, {label: '示範車行甲', month: '2026/11', value: 3, group: 'A11'});
  const second = cellButton(doc, {label: '示範車行乙', month: '2026/09', value: 1, group: 'B09'});
  bubble(first, 'click', {});
  bubble(second, 'click', {});
  const drawer = doc.body.children.find(node => node.classList.contains('report-cell-drawer'));
  assert.equal(doc.body.children.filter(node => node.classList.contains('report-cell-drawer')).length, 1);   // 同一個面板
  assert.ok(drawer.classList.contains('is-open'));
  assert.match(drawer.textContent, /示範車行乙2026 年 9 月共 1 張/);
  assert.equal(first.getAttribute('aria-expanded'), 'false');
  assert.equal(second.getAttribute('aria-expanded'), 'true');
  assert.equal(win.calls[0].options.signal.aborted, true);          // 前一格的請求被取消
  win.calls[1].resolve(ok(1)); await settle();
  win.calls[0].resolve(ok(3)); await settle();                      // 就算晚到也不採用
  assert.match(drawer.textContent, /訂單 1 張/);
  assert.doesNotMatch(drawer.textContent, /訂單 3 張/);
  bubble(drawer.children[0].children[1], 'click', {});
  assert.equal(doc.activeElement, second);                          // 焦點回到最後點的那一格
});

test('手機遮罩：點到的位置底下是另一個格子就換內容，否則關閉', () => {
  const {doc, win} = page();
  initReportHeatDrawer(doc, win);
  const first = cellButton(doc, {group: 'A11'});
  const second = cellButton(doc, {label: '示範車行乙', month: '2026/09', value: 1, group: 'B09'});
  bubble(first, 'click', {});
  const scrim = doc.body.children.find(node => node.classList.contains('report-cell-drawer-scrim'));
  const drawer = doc.body.children.find(node => node.classList.contains('report-cell-drawer'));
  assert.equal(scrim.hidden, false);
  doc.elementFromPoint = () => second;
  bubble(scrim, 'click', {clientX: 10, clientY: 10});
  assert.ok(drawer.classList.contains('is-open'));
  assert.match(drawer.textContent, /示範車行乙/);
  doc.elementFromPoint = () => doc.body;
  bubble(scrim, 'click', {clientX: 10, clientY: 10});
  assert.equal(drawer.classList.contains('is-open'), false);
  assert.equal(scrim.hidden, true);
});

test('載入失敗有說明與「再試一次」；沒有權限只說明；筆數和格子不同時寫出原因', async () => {
  const {doc, win} = page();
  initReportHeatDrawer(doc, win);
  const cell = cellButton(doc);
  bubble(cell, 'click', {});
  const drawer = doc.body.children.find(node => node.classList.contains('report-cell-drawer'));
  win.calls[0].resolve({ok: false, status: 500, redirected: false}); await settle();
  assert.equal(drawer.dataset.state, 'error');
  assert.match(drawer.textContent, /訂單載入失敗。再試一次改開完整明細 →/);
  const notice = drawer.children[2].children[0];
  assert.equal(notice.getAttribute('role'), 'alert');
  const retry = notice.children[1].children[0];
  bubble(retry, 'click', {});                                       // 按鈕被換掉後，面板不能因此被當成「點到外面」而關閉
  assert.ok(drawer.classList.contains('is-open'));
  assert.equal(win.calls.length, 2);
  win.calls[1].resolve({ok: false, status: 403, redirected: false}); await settle();
  assert.equal(drawer.dataset.state, 'denied');
  assert.match(drawer.textContent, /目前不能查看這份報表的訂單/);
  assert.doesNotMatch(drawer.textContent, /再試一次/);
  bubble(cell, 'click', {});
  win.calls[2].resolve({ok: false, status: 409, redirected: false}); await settle();
  assert.equal(drawer.dataset.state, 'stale');
  bubble(drawer.children[2].children[0].children[1].children[0], 'click', {});
  assert.equal(win.reloaded, 1);
  bubble(cell, 'click', {});
  win.calls[3].resolve(ok(2)); await settle();                      // 格子寫 3，現在查到 2
  assert.equal(drawer.dataset.state, 'ready');
  assert.match(drawer.textContent, /共 2 張/);
  assert.match(drawer.textContent, /格子上寫 3 張，是打開報表時的數字；訂單之後有異動，現在是 2 張/);
});

test('桌機面板蓋到格子區時往左讓；沒蓋到或剩下太窄就不動', () => {
  const {reportHeatRoom} = heat;
  assert.equal(reportHeatRoom(130, 1320, 1020), 316);   // 1440 寬：格子區右緣 1320，面板從 1020 起，讓出 300＋間距 16
  assert.equal(reportHeatRoom(130, 900, 1020), 0);      // 沒蓋到
  assert.equal(reportHeatRoom(130, 900, 560), 0);       // 讓完不到 480px：不擠，面板直接蓋上
});
