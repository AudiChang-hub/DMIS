// T-317 庫存列表「實際位置」選擇器（static/js/inventory-location.js）：
// 打字篩選、打的字標色、上下鍵加 Enter 選取並存、停在目前位置按 Enter 不存、Esc／Tab／點外面只關閉不存、
// 已停用的車行保留在清單、手機改用底部 <dialog>、按鈕 title 帶完整名稱（按鈕上的字會截斷）。
// 專案沒有 jsdom，這裡用一份只夠這支程式用的小型 DOM。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../../static/js/inventory-location.js'), 'utf8');
const FOCUSABLE_TAGS = new Set(['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA']);
const kebab = name => name.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`);

// 支援這支程式用到的寫法：tag、.class、[attr]、[attr='value'] 的組合。
function matches(node, selector) {
  const found = selector.trim().match(/^([a-z]+)?((?:\.[\w-]+)*)((?:\[[^\]]+\])*)$/i);
  if (!found) throw new Error(`測試用 DOM 不支援選擇器：${selector}`);
  const [, tag, classes, attrs] = found;
  if (tag && node.tagName !== tag.toUpperCase()) return false;
  if (classes.split('.').filter(Boolean).some(name => !node.classList.contains(name))) return false;
  return [...attrs.matchAll(/\[([\w-]+)(?:=['"]?([^'"\]]*)['"]?)?\]/g)]
    .every(([, name, value]) => node.hasAttribute(name) && (value === undefined || node.getAttribute(name) === value));
}

class El {
  constructor(tag, page) {
    this.tagName = tag.toUpperCase();
    this.page = page;
    this.attrs = new Map();
    this.children = [];
    this.parentElement = null;
    this.listeners = {};
    this.style = {};
    this.hidden = false;
    this.open = false;
    this.selected = false;
    this.inputValue = '';
    this.tabIndex = FOCUSABLE_TAGS.has(this.tagName) ? 0 : -1;
    const el = this;
    this.dataset = new Proxy({}, {
      get: (_, name) => el.attrs.get(`data-${kebab(name)}`),
      set: (_, name, value) => { el.attrs.set(`data-${kebab(name)}`, String(value)); return true; },
      has: (_, name) => el.attrs.has(`data-${kebab(name)}`),
      deleteProperty: (_, name) => { el.attrs.delete(`data-${kebab(name)}`); return true; },
    });
    this.classList = {
      names: () => (el.attrs.get('class') || '').split(/\s+/).filter(Boolean),
      contains: name => el.classList.names().includes(name),
      add: name => { if (!el.classList.contains(name)) el.attrs.set('class', [...el.classList.names(), name].join(' ')); },
      remove: name => el.attrs.set('class', el.classList.names().filter(item => item !== name).join(' ')),
      toggle: (name, on) => (on ? el.classList.add(name) : el.classList.remove(name)),
    };
  }
  setAttribute(name, value) { this.attrs.set(name, String(value)); if (name === 'tabindex') this.tabIndex = Number(value); }
  getAttribute(name) { return this.attrs.has(name) ? this.attrs.get(name) : null; }
  hasAttribute(name) { return this.attrs.has(name); }
  removeAttribute(name) { this.attrs.delete(name); }
  get id() { return this.attrs.get('id') || ''; }
  set className(value) { this.attrs.set('class', value); }
  get className() { return this.attrs.get('class') || ''; }
  get label() { return this.attrs.get('label') || ''; }
  get title() { return this.attrs.get('title') || ''; }
  set title(value) { this.attrs.set('title', String(value)); }
  get elements() { return this.children.filter(child => child instanceof El); }
  get textContent() { return this.children.map(child => (child instanceof El ? child.textContent : child)).join(''); }
  set textContent(value) { this.replaceChildren(); if (value !== '') this.children.push(String(value)); }
  append(...nodes) {
    nodes.forEach(node => {
      if (node instanceof Fragment) { this.append(...node.children.splice(0)); return; }
      if (node instanceof El) { node.remove(); node.parentElement = this; }
      this.children.push(node instanceof El ? node : String(node));
    });
  }
  remove() {
    if (!this.parentElement) return;
    const siblings = this.parentElement.children;
    siblings.splice(siblings.indexOf(this), 1);
    this.parentElement = null;
  }
  before(node) {
    node.remove();
    const siblings = this.parentElement.children;
    siblings.splice(siblings.indexOf(this), 0, node);
    node.parentElement = this.parentElement;
  }
  replaceChildren(...nodes) {
    this.elements.forEach(child => { child.parentElement = null; });
    this.children = [];
    this.append(...nodes);
  }
  cloneNode() {
    const copy = new El(this.tagName, this.page);
    this.attrs.forEach((value, name) => copy.attrs.set(name, value));
    this.children.forEach(child => copy.append(child instanceof El ? child.cloneNode() : child));
    return copy;
  }
  descendants() { return this.elements.flatMap(child => [child, ...child.descendants()]); }
  querySelectorAll(selector) { return this.descendants().filter(node => matches(node, selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) {
    for (let node = this; node; node = node.parentElement) if (matches(node, selector)) return node;
    return null;
  }
  contains(node) {
    for (let current = node; current; current = current.parentElement) if (current === this) return true;
    return false;
  }
  addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
  focus() { this.page.document.activeElement = this; }
  scrollIntoView() {}
  getBoundingClientRect() { return {left: 100, right: 300, top: 200, bottom: 236, width: 200, height: 36}; }
  getClientRects() { return [1]; }
  get offsetWidth() { return 300; }
  get offsetHeight() { return 320; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  // <select>
  get options() { return this.descendants().filter(node => node.tagName === 'OPTION'); }
  get selectedOptions() { return this.options.filter(option => option.selected).slice(-1); }
  get value() {
    if (this.tagName === 'SELECT') return (this.selectedOptions[0] || this.options[0])?.value ?? '';
    if (this.tagName === 'OPTION') return this.attrs.get('value') ?? '';
    return this.inputValue;
  }
  set value(next) {
    if (this.tagName === 'SELECT') this.options.forEach(option => { option.selected = option.value === next; });
    else if (this.tagName === 'OPTION') this.attrs.set('value', String(next));
    else this.inputValue = String(next);
  }
}

class Fragment {
  constructor(children = []) { this.children = children; }
  cloneNode() { return new Fragment(this.children.map(child => child.cloneNode())); }
}

const HOME = [['home-1', '示範總店'], ['home-2', '示範二店']];
const DEALERS = [['dealer-1', '甲車行'], ['dealer-2', '大同示範車業行'], ['dealer-3', '大同二店車業']];

function loadPage({rows = [{pk: 1, current: 'home-1', label: '示範總店'}], mobile = false, respond = null} = {}) {
  const page = {};
  const media = {matches: mobile};
  const make = (tag, attrs = {}, ...children) => {
    const node = new El(tag, page);
    Object.entries(attrs).forEach(([name, value]) => node.setAttribute(name, value));
    node.append(...children);
    return node;
  };
  const body = make('body');
  const documentListeners = {};
  const document = {
    activeElement: null, body, documentElement: {clientWidth: 1265},
    createElement: tag => new El(tag, page),
    getElementById: id => [body, ...body.descendants(), template].find(node => node.id === id) || null,
    querySelectorAll(selector) {
      // tabFrom() 用的那一長串可聚焦元素選擇器：回傳所有可聚焦的元素，其餘條件由程式自己再篩。
      if (selector.includes(':not(')) return body.descendants().filter(node => FOCUSABLE_TAGS.has(node.tagName));
      return body.querySelectorAll(selector);
    },
    addEventListener(type, handler) { (documentListeners[type] ||= []).push(handler); },
  };
  page.document = document;

  const option = ([value, label]) => make('option', {value}, label);
  const template = make('template', {id: 'inventory-location-options', 'data-csrf': 'csrf-token'});
  template.content = new Fragment([
    make('optgroup', {label: '本店'}, ...HOME.map(option)),
    make('optgroup', {label: '車行'}, ...DEALERS.map(option)),
  ]);

  const built = rows.map(({pk, current, label}) => {
    const selected = make('option', {value: current}, label);
    selected.selected = true;
    const select = make('select', {class: 'inventory-location__select', name: 'location', 'data-location-current': current}, selected);
    const status = make('p', {class: 'inventory-location__status', 'data-location-status': ''});
    status.hidden = true;
    const wrap = make('div', {class: 'inventory-location', 'data-inventory-location': '', 'data-url': `/inventory/${pk}/location/`, 'data-identifier': `ENG-${pk}`}, select, status);
    const edit = make('a', {href: `/inventory/${pk}/edit/`}, '查看／編輯');
    body.append(make('div', {class: 'row'}, wrap, edit));
    return {select, status, wrap, edit};
  });

  const posts = [];
  const labels = new Map([...HOME, ...DEALERS]);
  const fetch = async (url, {body: form}) => {
    const fields = Object.fromEntries(form.entries());
    posts.push({url, ...fields});
    const payload = respond ? respond(fields) : {
      ok: true, changed: true, value: fields.location, label: labels.get(fields.location),
      previous_value: fields.expected, previous_label: labels.get(fields.expected),
    };
    return {ok: payload.ok !== false, status: 200, json: async () => payload};
  };
  const window = {
    innerHeight: 800, scrollX: 0, scrollY: 0, setTimeout, clearTimeout,
    matchMedia: () => media,
    addEventListener() {},
  };
  vm.runInNewContext(source, {window, document, fetch, FormData, AbortController});

  // 事件由目標一路往上傳到 document，和瀏覽器一樣。
  const fire = (target, type, init = {}) => {
    const event = {
      type, target, key: '', shiftKey: false, isComposing: false, defaultPrevented: false, stopped: false,
      preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }, ...init,
    };
    for (let node = target; node && !event.stopped; node = node.parentElement) {
      [...(node.listeners[type] || [])].forEach(handler => handler(event));
    }
    if (!event.stopped) [...(documentListeners[type] || [])].forEach(handler => handler(event));
    return event;
  };
  const settle = () => new Promise(resolve => setImmediate(resolve));

  const api = rowIndex => {
    const row = built[rowIndex];
    const button = row.wrap.querySelector('[data-location-button]');
    const ui = () => ({
      pop: body.querySelector('[data-location-pop]'),
      dialog: body.querySelector('dialog'),
      input: body.querySelector('.inventory-location-picker__input'),
      list: body.querySelector('.inventory-location-picker__list'),
    });
    const items = () => (ui().list ? ui().list.querySelectorAll("[role='option']") : []);
    return {
      ...row, button, ui, items,
      open: () => fire(button, 'click'),
      isOpen: () => button.getAttribute('aria-expanded') === 'true',
      type(text) { ui().input.value = text; fire(ui().input, 'input'); },
      key: (key, init = {}) => fire(ui().input, 'keydown', {key, ...init}),
      labels: () => items().map(item => item.querySelector('span').textContent),
      groups: () => ui().list.querySelectorAll('.transfer-out-suggest__group').map(node => node.textContent),
      active: () => items().find(item => item.classList.contains('is-active'))?.querySelector('span').textContent ?? null,
      note: text => items().find(item => item.querySelector('span').textContent === text)?.querySelector('small')?.textContent ?? '',
    };
  };
  return {document, body, media, posts, fire, settle, row: api};
}

test('每列換成一顆按鈕：顯示目前位置、title 帶完整名稱，原生選單保留但不進 Tab 順序', () => {
  const page = loadPage({rows: [{pk: 7, current: 'dealer-9', label: '超長名稱示範車業股份有限公司北區營業所'}]});
  const row = page.row(0);
  assert.equal(row.button.querySelector('[data-location-label]').textContent, '超長名稱示範車業股份有限公司北區營業所');
  assert.equal(row.button.title, '超長名稱示範車業股份有限公司北區營業所');
  assert.match(row.button.getAttribute('aria-label'), /^實際位置 ENG-7：超長名稱示範車業股份有限公司北區營業所/);
  assert.equal(row.button.getAttribute('aria-expanded'), 'false');
  assert.equal(row.select.tabIndex, -1);
  assert.equal(row.wrap.classList.contains('is-enhanced'), true);
  assert.equal(row.select.parentElement, row.wrap);
});

test('點開分「本店／車行」兩組，停在目前位置；打字只留符合的選項並把打的字標色', () => {
  const page = loadPage();
  const row = page.row(0);
  row.open();
  assert.equal(row.isOpen(), true);
  assert.equal(row.ui().pop.hidden, false);
  assert.deepEqual(row.groups(), ['本店', '車行']);
  assert.deepEqual(row.labels(), ['示範總店', '示範二店', '甲車行', '大同示範車業行', '大同二店車業']);
  assert.equal(row.active(), '示範總店');
  assert.equal(row.note('示範總店'), '目前位置');

  row.type('大同');
  assert.deepEqual(row.groups(), ['車行']);
  assert.deepEqual(row.labels(), ['大同示範車業行', '大同二店車業']);
  assert.equal(row.active(), '大同示範車業行', '打字後停在第一個符合的');
  const marks = row.items().map(item => item.querySelectorAll('mark').map(mark => mark.textContent));
  assert.deepEqual(marks, [['大同'], ['大同']]);
  // 標色不改變文字本身：前後文字還在，只是中間那段包在 <mark> 裡。
  assert.deepEqual(row.items()[0].querySelector('span').children.map(child => (child instanceof El ? `<${child.textContent}>` : child)), ['', '<大同>', '示範車業行']);

  row.type('二店');
  assert.deepEqual(row.groups(), ['本店', '車行']);
  assert.deepEqual(row.labels(), ['示範二店', '大同二店車業']);

  row.type('沒有這家');
  assert.deepEqual(row.labels(), []);
  assert.equal(row.active(), null);
  assert.match(row.ui().list.querySelector('.transfer-out-suggest__warning').textContent, /找不到「沒有這家」/);
  row.key('Enter');
  assert.equal(row.isOpen(), true, '沒有選項時按 Enter 不關閉也不存');
  assert.deepEqual(page.posts, []);
});

test('上下鍵加 Enter：選取、送出一次、按鈕換成新位置，並出現「復原」', async () => {
  const page = loadPage();
  const row = page.row(0);
  row.open();
  row.key('ArrowDown');
  assert.equal(row.active(), '示範二店');
  row.key('ArrowDown');
  assert.equal(row.active(), '甲車行');
  row.key('ArrowUp');
  assert.equal(row.active(), '示範二店');
  const enter = row.key('Enter');
  assert.equal(enter.defaultPrevented, true);
  assert.equal(row.isOpen(), false);
  assert.equal(page.document.activeElement, row.button, '存的時候焦點回到按鈕');
  await page.settle();
  assert.deepEqual(page.posts, [{url: '/inventory/1/location/', csrfmiddlewaretoken: 'csrf-token', location: 'home-2', expected: 'home-1'}]);
  assert.equal(row.button.querySelector('[data-location-label]').textContent, '示範二店');
  assert.equal(row.button.title, '示範二店');
  assert.equal(row.select.dataset.locationCurrent, 'home-2');
  assert.equal(row.status.hidden, false);
  assert.match(row.status.textContent, /已改放到 示範二店/);

  page.fire(row.status.querySelector('.inventory-location__undo'), 'click');
  await page.settle();
  assert.deepEqual(page.posts[1], {url: '/inventory/1/location/', csrfmiddlewaretoken: 'csrf-token', location: 'home-1', expected: 'home-2', undo: '1'});
  assert.equal(row.button.querySelector('[data-location-label]').textContent, '示範總店');
});

test('打字篩選後按 Enter 存第一個符合的；點選項也會存', async () => {
  const page = loadPage({rows: [{pk: 1, current: 'home-1', label: '示範總店'}, {pk: 2, current: 'home-1', label: '示範總店'}]});
  const first = page.row(0);
  first.open();
  first.type('甲');
  first.key('Enter');
  await page.settle();
  assert.deepEqual(page.posts.map(post => [post.url, post.location]), [['/inventory/1/location/', 'dealer-1']]);

  const second = page.row(1);
  second.open();
  page.fire(second.items()[3].querySelector('span'), 'click');
  await page.settle();
  assert.equal(page.posts.length, 2);
  assert.deepEqual([page.posts[1].url, page.posts[1].location, page.posts[1].expected], ['/inventory/2/location/', 'dealer-2', 'home-1']);
  assert.equal(second.button.querySelector('[data-location-label]').textContent, '大同示範車業行');
});

test('停在目前位置按 Enter：關閉，不送出', async () => {
  const page = loadPage();
  const row = page.row(0);
  row.open();
  assert.equal(row.active(), '示範總店');
  row.key('Enter');
  await page.settle();
  assert.equal(row.isOpen(), false);
  assert.deepEqual(page.posts, []);
  assert.equal(row.status.hidden, true);
  // 繞一圈回到目前位置再按 Enter 也一樣。
  row.open();
  row.key('ArrowDown');
  row.key('ArrowUp');
  row.key('Enter');
  await page.settle();
  assert.deepEqual(page.posts, []);
});

test('Esc 關閉不存，焦點回到按鈕', async () => {
  const page = loadPage();
  const row = page.row(0);
  row.open();
  row.key('ArrowDown');
  const escape = row.key('Escape');
  await page.settle();
  assert.equal(escape.defaultPrevented, true);
  assert.equal(row.isOpen(), false);
  assert.equal(row.ui().pop.hidden, true);
  assert.equal(page.document.activeElement, row.button);
  assert.deepEqual(page.posts, []);
  assert.equal(row.select.value, 'home-1');
  assert.equal(row.button.querySelector('[data-location-label]').textContent, '示範總店');
});

test('Tab 關閉不存，焦點移到按鈕的下一個（Shift+Tab 上一個）可操作元素', async () => {
  const page = loadPage({rows: [{pk: 1, current: 'home-1', label: '示範總店'}, {pk: 2, current: 'home-1', label: '示範總店'}]});
  const second = page.row(1);
  second.open();
  second.key('ArrowDown');
  const tab = second.key('Tab');
  await page.settle();
  assert.equal(tab.defaultPrevented, true);
  assert.equal(second.isOpen(), false);
  assert.equal(page.document.activeElement, second.edit);
  assert.deepEqual(page.posts, []);

  second.open();
  second.key('ArrowDown');
  second.key('Tab', {shiftKey: true});
  await page.settle();
  assert.equal(second.isOpen(), false);
  assert.equal(page.document.activeElement, page.row(0).edit);
  assert.deepEqual(page.posts, []);
  assert.equal(second.select.value, 'home-1');
});

test('點選擇器外面、再點一次按鈕、改點另一列：都只關閉不存', async () => {
  const page = loadPage({rows: [{pk: 1, current: 'home-1', label: '示範總店'}, {pk: 2, current: 'home-2', label: '示範二店'}]});
  const first = page.row(0);
  const second = page.row(1);
  first.open();
  first.key('ArrowDown');
  page.fire(first.edit, 'pointerdown');
  assert.equal(first.isOpen(), false);

  first.open();
  page.fire(first.ui().input, 'pointerdown');
  assert.equal(first.isOpen(), true, '點選擇器裡面不關閉');
  first.open();
  assert.equal(first.isOpen(), false, '再點一次按鈕就關閉');

  first.open();
  first.key('ArrowDown');
  second.open();
  assert.equal(first.isOpen(), false);
  assert.equal(second.isOpen(), true);
  assert.equal(second.active(), '示範二店', '換一列後停在那一列的目前位置');
  await page.settle();
  assert.deepEqual(page.posts, []);
});

test('目前放在已停用的車行：那一項保留在「車行」組並標示「已停用」', async () => {
  const page = loadPage({rows: [{pk: 3, current: 'dealer-99', label: '停用示範車行'}]});
  const row = page.row(0);
  row.open();
  assert.deepEqual(row.groups(), ['本店', '車行']);
  assert.deepEqual(row.labels(), ['示範總店', '示範二店', '甲車行', '大同示範車業行', '大同二店車業', '停用示範車行']);
  assert.equal(row.note('停用示範車行'), '目前位置・已停用');
  assert.equal(row.active(), '停用示範車行');
  row.type('停用');
  assert.deepEqual(row.labels(), ['停用示範車行']);
  row.key('Enter');
  await page.settle();
  assert.deepEqual(page.posts, [], '選回目前位置不送出');
  // 改到別處照常可以存。
  row.open();
  row.type('甲');
  row.key('Enter');
  await page.settle();
  assert.deepEqual(page.posts.map(post => [post.location, post.expected]), [['dealer-1', 'dealer-99']]);
});

test('存檔失敗：退回原位置並顯示伺服器的訊息', async () => {
  const page = loadPage({respond: () => ({ok: false, message: '這台車剛被別人改過位置。', value: 'home-1', label: '示範總店'})});
  const row = page.row(0);
  row.open();
  row.key('ArrowDown');
  row.key('Enter');
  await page.settle();
  assert.equal(page.posts.length, 1);
  assert.equal(row.select.value, 'home-1');
  assert.equal(row.button.querySelector('[data-location-label]').textContent, '示範總店');
  assert.equal(row.status.classList.contains('is-error'), true);
  assert.match(row.status.textContent, /剛被別人改過位置/);
  assert.equal(row.status.querySelector('.inventory-location__undo'), null);
});

test('手機寬度改從底部開 <dialog>：不自動聚焦輸入框，取消與 Esc（cancel）只關閉不存', async () => {
  const page = loadPage({mobile: true});
  const row = page.row(0);
  row.open();
  const {dialog, pop, input} = row.ui();
  assert.equal(dialog.open, true);
  assert.equal(pop.hidden, true);
  assert.equal(dialog.contains(input), true);
  assert.notEqual(page.document.activeElement, input, '不自動叫出鍵盤');
  assert.match(dialog.querySelector('header').textContent, /ENG-1・目前在 示範總店/);

  const cancel = page.fire(dialog, 'cancel');
  assert.equal(cancel.defaultPrevented, true);
  assert.equal(dialog.open, false);
  assert.equal(row.isOpen(), false);

  row.open();
  page.fire(dialog.querySelector('.transfer-out-dialog__actions').querySelector('button'), 'click');
  assert.equal(dialog.open, false);
  await page.settle();
  assert.deepEqual(page.posts, []);

  row.open();
  page.fire(row.items()[1], 'click');
  await page.settle();
  assert.equal(dialog.open, false);
  assert.deepEqual(page.posts.map(post => post.location), ['home-2']);
});
