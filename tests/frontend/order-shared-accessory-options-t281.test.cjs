const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

// T-281 h（使用者 2026-11-21 選 B）：訂單頁既有配件列的名稱下拉只帶已選項，載入時從新增列範本複製完整清單。
const scripts = fs.readFileSync('templates/sales/_order_form_scripts.html', 'utf8');
const block = scripts.match(/<script>\s*(\/\/ 訂單頁配件列（T-281 h）[\s\S]*?)<\/script>/);

class Node {
  constructor(tag, attrs = {}, children = []) {
    this.tagName = tag; this.attrs = {...attrs}; this.childNodes = children; this.selectedState = 'selected' in attrs;
  }
  cloneNode() { return new Node(this.tagName, this.attrs, this.childNodes.map((child) => child.cloneNode())); }
  get value() { return this.attrs.value ?? ''; }
  get defaultSelected() { return 'selected' in this.attrs; }
  set defaultSelected(on) { if (on) this.attrs.selected = ''; else delete this.attrs.selected; this.selectedState = on; }
  get selected() { return this.selectedState; }
  set selected(on) { this.selectedState = on; }
  removeAttribute(name) { delete this.attrs[name]; }
  get options() { return this.childNodes.flatMap((child) => child.tagName === 'OPTGROUP' ? child.childNodes : child.tagName === 'OPTION' ? [child] : []); }
  replaceChildren(...nodes) { this.childNodes = nodes; }
  html() {
    const attrs = Object.entries(this.attrs).map(([k, v]) => (v === '' ? ` ${k}` : ` ${k}="${v}"`)).join('');
    return this.tagName === '#text' ? this.attrs.text : `<${this.tagName}${attrs}>${this.childNodes.map((c) => c.html()).join('')}</${this.tagName}>`;
  }
}
const text = (value) => new Node('#text', {text: value});
const option = (value, label, selected) => new Node('OPTION', {value, ...(selected ? {selected: ''} : {})}, [text(label)]);
const group = (label, options) => new Node('OPTGROUP', {label}, options);
// 伺服器版本：完整清單，第一個值相同的選項帶 selected（同一配件在兩組時只標第一組）。
const full = (selected) => [
  text('\n  '), option('', '---------', selected === ''), text('\n  '),
  group('安全帽', [option('1', '輕便安全帽', selected === '1'), option('2', '五匹手機架', selected === '2')]),
  group('手機架', [option('2', '五匹手機架', false)]), text('\n  '), option('other', '自行填寫名稱', selected === 'other'),
];
const markSelected = (nodes, value) => { let done = false; nodes.forEach((n) => { if (n.tagName === 'OPTGROUP') n.childNodes = n.childNodes.map((o) => { const hit = !done && o.value === value; done ||= hit; return option(o.value, o.childNodes[0].attrs.text, hit); }); else if (n.tagName === 'OPTION') { const hit = !done && n.value === value; done ||= hit; n.attrs = hit ? {value: n.value, selected: ''} : {value: n.value}; } }); return nodes; };

function run(rows) {
  const template = new Node('SELECT', {name: 'accessories-__prefix__-accessory_product'}, full(''));
  const document = {
    getElementById: (id) => (id === 'empty-accessory' ? {content: {querySelector: () => template}} : null),
    querySelectorAll: () => rows.filter((row) => row.attrs['data-shared-options'] === 'accessory-product'),
  };
  Object.defineProperty(Node.prototype, 'value', {configurable: true, get() {
    if (this.tagName !== 'SELECT') return this.attrs.value ?? '';
    const options = this.options;
    return (options.find((o) => o.selected) || options[0])?.value ?? '';
  }});
  new Function('document', block[1])(document);
}

test('訂單頁的配件名稱下拉在其他配件程式之前還原完整清單', () => {
  assert.ok(block, '找不到 T-281 h 的還原程式');
  assert.ok(scripts.indexOf('訂單頁配件列（T-281 h）') < scripts.indexOf('function filterAccessoryProducts'));
});

test('還原後與伺服器原本輸出的完整下拉相同，送出的值不變', () => {
  for (const value of ['', '1', '2', 'other']) {
    const label = {'': '---------', 1: '輕便安全帽', 2: '五匹手機架', other: '自行填寫名稱'}[value];
    const row = new Node('SELECT', {name: 'accessories-0-accessory_product', class: 'form-control', 'data-shared-options': 'accessory-product'},
      [text('\n  '), option(value, label, true), text('\n')]);
    const untouched = new Node('SELECT', {name: 'accessories-1-accessory_product'}, full('1'));
    const before = untouched.html();
    run([row, untouched]);
    const expected = new Node('SELECT', {name: 'accessories-0-accessory_product', class: 'form-control'}, markSelected(full(''), value));
    assert.equal(row.html(), expected.html(), `值 ${value || '（空白）'}`);
    assert.equal(row.value, value);
    assert.equal(row.options.filter((o) => o.defaultSelected).length, 1);
    assert.equal(untouched.html(), before, '沒有標記的下拉不動');
  }
});
