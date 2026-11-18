const test = require('node:test');
const assert = require('node:assert/strict');
const {UNASSIGNED, groupByRegion, countLabel, bindRegionGroups, refreshRegionGroups} = require('../../static/js/region-groups.js');

// 最小的假 DOM：只實作分組程式用到的查詢與事件。
class El {
  constructor(attrs = {}, children = []) {
    this.attrs = {...attrs}; this.children = children; this.hidden = false; this.dataset = {}; this.listeners = {};
    this.textContent = ''; this.checked = false; this.parent = null; this.events = [];
    children.forEach(child => { child.parent = this; });
  }
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  matches(selector) {
    if (selector === 'input[type="checkbox"]') return this.attrs.type === 'checkbox';
    const [base, not] = selector.split(':not(');
    const has = name => name.replace(/[[\]]/g, '') in this.attrs || this.dataset[toKey(name)] !== undefined;
    return has(base) && !(not && has(not.replace(')', '')));
  }
  all() { return this.children.flatMap(child => [child, ...child.all()]); }
  querySelectorAll(selector) { return this.all().filter(el => el.matches(selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { for (let el = this; el; el = el.parent) if (el.matches(selector)) return el; return null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatchEvent(event) { this.events.push(event.type); return true; }
  click() { (this.listeners.click || []).forEach(fn => fn({preventDefault() {}})); }
}
const toKey = name => name.replace(/^\[data-|\]$/g, '').replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const box = () => new El({type: 'checkbox'});
const item = () => new El({'data-region-item': ''}, [box()]);
function region(count) {
  const items = Array.from({length: count}, item);
  const toggle = new El({'data-region-toggle': '', 'aria-expanded': 'true'});
  const all = new El({'data-region-select': ''}); all.dataset.regionSelect = 'all';
  const none = new El({'data-region-select': ''}); none.dataset.regionSelect = 'none';
  const counter = new El({'data-region-count': ''});
  const body = new El({'data-region-items': ''}, items);
  const group = new El({'data-region-group': ''}, [toggle, counter, all, none, body]);
  return {group, items, toggle, all, none, counter, body};
}

test('依縣市順序分組，未分區排最後，區內維持原順序', () => {
  const groups = groupByRegion([
    {name: 'a', region: '新北市', order: '1'}, {name: 'b', region: '', order: '22'},
    {name: 'c', region: '臺北市', order: '0'}, {name: 'd', region: '新北市', order: '1'},
  ]);
  assert.deepEqual(groups.map(g => [g.label, g.items.map(i => i.name)]), [['臺北市', ['c']], ['新北市', ['a', 'd']], [UNASSIGNED, ['b']]]);
});

test('家數：未搜尋顯示總數，搜尋時顯示符合／總數', () => {
  assert.equal(countLabel(3, 3), '3 家');
  assert.equal(countLabel(1, 3), '1／3 家');
});

test('搜尋：沒有符合的區整組隱藏，有符合的區展開並顯示符合家數', () => {
  const taipei = region(2), keelung = region(1);
  const scope = new El({}, [taipei.group, keelung.group]);
  bindRegionGroups(scope);
  taipei.toggle.click();  // 使用者先收合臺北市
  assert.equal(taipei.body.hidden, true);
  taipei.items[1].hidden = true; keelung.items[0].hidden = true;  // 元件自己的搜尋已隱藏不符合的選項
  refreshRegionGroups(scope, '台北');
  assert.equal(keelung.group.hidden, true);
  assert.equal(taipei.group.hidden, false);
  assert.equal(taipei.body.hidden, false, '搜尋時有符合的區一律展開');
  assert.equal(taipei.counter.textContent, '1／2 家');
  [...taipei.items, ...keelung.items].forEach(el => { el.hidden = false; });
  refreshRegionGroups(scope, '');
  assert.equal(keelung.group.hidden, false);
  assert.equal(taipei.body.hidden, true, '清空搜尋回到使用者的收合狀態');
  assert.equal(taipei.counter.textContent, '2 家');
});

test('全選此區／取消此區只動這區看得到的車行，並通知所屬選擇器', () => {
  const taipei = region(3), keelung = region(1);
  const control = new El({'data-report-multi': ''}, [new El({}, [taipei.group, keelung.group])]);
  bindRegionGroups(control);
  taipei.items[2].hidden = true;
  taipei.all.click();
  assert.deepEqual(taipei.items.map(el => el.children[0].checked), [true, true, false]);
  assert.equal(keelung.items[0].children[0].checked, false);
  assert.deepEqual(control.events, ['change']);
  taipei.none.click();
  assert.deepEqual(taipei.items.map(el => el.children[0].checked), [false, false, false]);
});
