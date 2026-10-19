const {test} = require('node:test');
const assert = require('node:assert/strict');
const {validateFile, linkError, createCell, MAX_BYTES} = require('../../static/js/catalog-photo-board.js');

const png = [137, 80, 78, 71, 13, 10, 26, 10];
function file(options = {}) {
  const {bytes = png, size = 32, type = 'image/png', name = '圖.png'} = options;
  return {size, type, name, slice: () => ({arrayBuffer: async () => Uint8Array.from(bytes).buffer})};
}
function element(extra = {}) {
  const attrs = {}, listeners = {};
  return {
    hidden: false, value: '', textContent: '', files: [], dataset: {}, classList: new Set(),
    getAttribute: key => attrs[key], setAttribute: (key, value) => {attrs[key] = String(value);},
    removeAttribute: key => {delete attrs[key];},
    addEventListener: (event, fn) => {listeners[event] = fn;},
    dispatch(event, payload = {}) {return listeners[event]?.({preventDefault() {this.prevented = true;}, ...payload});},
    focus() {this.focused = true;},
    ...extra,
  };
}
function fixture({hasPhoto = false, response = {ok: true, thumb: '/thumb?v=new.png', image: 'catalog/new.png', replaced: hasPhoto}, status = 200} = {}) {
  const nodes = {};
  for (const key of ['[data-photo-drop]', '[data-photo-img]', '[data-photo-message]', '[data-photo-file]',
    '[data-photo-file-label]', '[data-photo-badge]', '[data-photo-link-toggle]', '[data-photo-link-form]',
    '[data-photo-url]', '[data-photo-confirm]', '[data-photo-confirm-yes]', '[data-photo-confirm-no]']) nodes[key] = element();
  const img = nodes['[data-photo-img]'];
  if (hasPhoto) img.setAttribute('src', '/thumb?v=old.png'); else img.hidden = true;
  nodes['[data-photo-link-form]'].hidden = true;
  const classes = new Set();
  const cell = {dataset: {hasPhoto: hasPhoto ? '1' : '0', expected: hasPhoto ? 'catalog/old.png' : '', saveUrl: '/save/9/', state: 'idle'},
    classList: {add: name => classes.add(name), remove: name => classes.delete(name)},
    querySelector: key => nodes[key]};
  const calls = [], saved = [], revoked = [];
  class FormData { constructor() {this.entries = [];} append(key, value) {this.entries.push([key, value]);} }
  const deps = {
    token: 'csrf', FormData, onSaved: (node, wasMissing) => saved.push(wasMissing),
    URL: {createObjectURL: () => 'blob:1', revokeObjectURL: url => revoked.push(url)},
    fetch: async (url, options) => {
      calls.push({url, options});
      if (response instanceof Error) throw response;
      return {ok: status < 400, json: async () => response};
    },
  };
  const controller = createCell(cell, deps);
  return {cell, nodes, img, calls, saved, revoked, classes, controller};
}

test('檔案驗證與連結格式檢查', async () => {
  assert.equal(await validateFile(file()), '');
  assert.equal(await validateFile(file({size: MAX_BYTES})), '');
  for (const options of [{size: 0}, {size: MAX_BYTES + 1}, {type: 'image/gif'}, {bytes: [1, 2, 3]}]) {
    assert.notEqual(await validateFile(file(options)), '');
  }
  assert.equal(linkError('https://www.e-moving.com.tw/a.jpg'), '');
  assert.notEqual(linkError('javascript:alert(1)'), '');
  assert.notEqual(linkError('不是網址'), '');
});

test('缺圖格放入檔案就直接上傳並更新狀態', async () => {
  const f = fixture();
  f.nodes['[data-photo-file]'].files = [file()];
  await f.nodes['[data-photo-file]'].dispatch('change');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.calls.length, 1);
  const {options} = f.calls[0];
  assert.equal(options.method, 'POST');
  assert.equal(options.headers['X-CSRFToken'], 'csrf');
  assert.deepEqual(options.body.entries.map(([key]) => key), ['expected', 'image']);
  assert.equal(f.cell.dataset.hasPhoto, '1');
  assert.equal(f.cell.dataset.expected, 'catalog/new.png');
  assert.equal(f.cell.dataset.state, 'saved');
  assert.equal(f.img.getAttribute('src'), '/thumb?v=new.png');
  assert.equal(f.nodes['[data-photo-file-label]'].textContent, '換圖');
  assert.deepEqual(f.saved, [true]);
  assert.deepEqual(f.revoked, ['blob:1']);
});

test('拖入連結或貼上網址走連結下載，失敗顯示原因並還原', async () => {
  const f = fixture({response: {ok: false, error: '這個連結指向內部網路或保留位址，基於安全不能下載。'}, status: 400});
  const drop = f.nodes['[data-photo-drop]'];
  await drop.dispatch('drop', {dataTransfer: {files: [], getData: type => type === 'text/uri-list' ? 'http://10.0.0.1/a.jpg\n' : ''}});
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(f.calls[0].options.body.entries, [['expected', ''], ['url', 'http://10.0.0.1/a.jpg']]);
  assert.equal(f.cell.dataset.state, 'error');
  assert.match(f.nodes['[data-photo-message]'].textContent, /內部網路/);
  assert.equal(f.img.hidden, true);
  assert.equal(f.cell.dataset.hasPhoto, '0');
  assert.deepEqual(f.saved, []);
  await drop.dispatch('paste', {clipboardData: {files: [], getData: () => 'ftp://x/a.jpg'}});
  assert.equal(f.calls.length, 1);
  assert.match(f.nodes['[data-photo-message]'].textContent, /http/);
});

test('已有圖的格子要先確認才取代，取消會還原原圖', async () => {
  const f = fixture({hasPhoto: true});
  await f.controller.accept({kind: 'file', value: file()});
  assert.equal(f.cell.dataset.state, 'confirm');
  assert.equal(f.nodes['[data-photo-confirm]'].hidden, false);
  assert.equal(f.img.getAttribute('src'), 'blob:1');
  assert.equal(f.calls.length, 0);
  f.nodes['[data-photo-confirm-no]'].dispatch('click');
  assert.equal(f.img.getAttribute('src'), '/thumb?v=old.png');
  assert.equal(f.cell.dataset.state, 'idle');
  await f.controller.accept({kind: 'url', value: 'https://a.example/new.jpg'});
  await f.nodes['[data-photo-confirm-yes]'].dispatch('click');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(f.calls[0].options.body.entries, [['expected', 'catalog/old.png'], ['url', 'https://a.example/new.jpg']]);
  assert.match(f.nodes['[data-photo-message]'].textContent, /已換上新圖片/);
  assert.deepEqual(f.saved, [false]);
});

test('連線失敗不改動格子，連結表單可開關', async () => {
  const f = fixture({response: new Error('')});
  f.nodes['[data-photo-link-toggle]'].dispatch('click');
  assert.equal(f.nodes['[data-photo-link-form]'].hidden, false);
  assert.equal(f.nodes['[data-photo-url]'].focused, true);
  f.nodes['[data-photo-url]'].value = ' https://a.example/x.jpg ';
  await f.nodes['[data-photo-link-form]'].dispatch('submit');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.cell.dataset.state, 'error');
  assert.ok(f.nodes['[data-photo-message]'].textContent);
  assert.equal(f.cell.dataset.hasPhoto, '0');
  assert.equal(f.nodes['[data-photo-link-form]'].hidden, false);
});
