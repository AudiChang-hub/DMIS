const {test} = require('node:test');
const assert = require('node:assert/strict');
const {validateFile, attach, MAX_BYTES} = require('../../static/js/catalog-image-preview.js');
const png = [137, 80, 78, 71, 13, 10, 26, 10];
function file(options = {}) {
  const {bytes = png, size = 32, type = 'image/png', name = '測試.png'} = options;
  return {size, type, name, slice: () => ({arrayBuffer: async () => Uint8Array.from(bytes).buffer})};
}
function element() {
  const attrs = {}, listeners = {};
  return {
    hidden: false, checked: false, files: [], value: '', id: 'preview-status',
    getAttribute: key => attrs[key], setAttribute: (key, value) => {attrs[key] = value;},
    removeAttribute: key => {delete attrs[key];},
    addEventListener: (event, fn) => {listeners[event] = fn;},
    dispatch(event) {return listeners[event]?.();},
    setCustomValidity(value) {this.validationMessage = value;},
    focus() {this.focused = true;},
    set src(value) {attrs.src = value;}, get src() {return attrs.src;},
  };
}
function fixture(original = '', removable = true) {
  const input = element(), image = element(), placeholder = element(), status = element(), cancel = element();
  const remove = removable ? element() : null;
  if (original) image.src = original;
  image.hidden = !original; placeholder.hidden = !!original;
  const nodes = {'input[type="file"]': input, '[data-preview-image]': image,
    '[data-preview-placeholder]': placeholder, '[data-preview-status]': status,
    '[data-preview-cancel]': cancel, 'input[type="checkbox"]': remove};
  const details = {open: false};
  const root = {dataset: {}, querySelector: key => nodes[key], closest: () => details};
  const loaders = [], revoked = [];
  let counter = 0;
  const env = {URL: {createObjectURL: () => `blob:${++counter}`, revokeObjectURL: url => revoked.push(url)},
    Image: class {constructor() {loaders.push(this);}}};
  const controller = attach(root, env);
  async function select(value = file()) {input.files = [value]; input.value = value.name; await input.dispatch('change');}
  return {input, image, placeholder, status, cancel, remove, root, details, loaders, revoked, controller, select};
}

test('允許 JPEG、PNG、WebP 檔頭及空 MIME，包含剛好 8 MiB', async () => {
  for (const options of [{}, {size: MAX_BYTES}, {type: ''},
    {type: 'image/jpeg', bytes: [255,216,255]},
    {type: 'image/webp', bytes: [82,73,70,70,0,0,0,0,87,69,66,80]}]) {
    assert.equal(await validateFile(file(options)), '');
  }
});
test('拒絕空檔、超限、SVG、偽裝圖片', async () => {
  for (const options of [{size: 0}, {size: MAX_BYTES + 1}, {type: 'image/svg+xml'}, {bytes: [1,2,3]}]) {
    assert.notEqual(await validateFile(file(options)), '');
  }
});
test('解碼前阻擋送出，解碼後預覽並提示尚未儲存', async () => {
  const f = fixture();
  await f.select();
  assert.equal(f.root.dataset.previewState, 'checking');
  assert.ok(f.input.validationMessage);
  f.loaders[0].onload();
  assert.equal(f.image.src, 'blob:1');
  assert.equal(f.image.hidden, false);
  assert.equal(f.placeholder.hidden, true);
  assert.match(f.status.textContent, /尚未儲存：測試.png/);
  assert.equal(f.input.validationMessage, '');
  assert.equal(f.input.getAttribute('aria-describedby'), 'preview-status');
});
test('取消還原原圖或缺圖並釋放 URL，焦點回到選檔', async () => {
  for (const original of ['', '/saved.png']) {
    const f = fixture(original);
    await f.select(); f.loaders[0].onload(); f.cancel.dispatch('click');
    assert.equal(f.image.src || '', original);
    assert.equal(f.image.hidden, !original);
    assert.equal(f.input.value, '');
    assert.equal(f.cancel.hidden, true);
    assert.equal(f.input.focused, true);
    assert.deepEqual(f.revoked, ['blob:1']);
  }
});
test('損壞圖片保留原圖並阻擋送出，取消可恢復有效狀態', async () => {
  const f = fixture('/saved.png');
  await f.select(); f.loaders[0].onerror();
  assert.equal(f.root.dataset.previewState, 'error');
  assert.equal(f.image.src, '/saved.png');
  assert.equal(f.input.value, '');
  assert.ok(f.input.validationMessage);
  assert.deepEqual(f.revoked, ['blob:1']);
  f.cancel.dispatch('click');
  assert.equal(f.input.validationMessage, '');
});
test('重選與取消後舊解碼回呼不能覆蓋新狀態', async () => {
  const f = fixture();
  await f.select(); const stale = f.loaders[0].onload;
  await f.select(file({name: '新圖.png'}));
  stale();
  assert.equal(f.image.hidden, true);
  f.loaders[1].onload();
  assert.equal(f.image.src, 'blob:2');
  assert.match(f.status.textContent, /新圖.png/);
  f.controller.reset(); stale();
  assert.equal(f.image.hidden, true);
  assert.deepEqual(f.revoked, ['blob:1', 'blob:2']);
});
test('較慢的舊檔頭讀取不能建立過期預覽', async () => {
  let resolveRead;
  const f = fixture();
  const delayed = {...file(), slice: () => ({arrayBuffer: () => new Promise(resolve => {resolveRead = resolve;})})};
  const pending = f.select(delayed);
  await f.select(file({name: '新圖.png'}));
  resolveRead(Uint8Array.from(png).buffer); await pending;
  assert.equal(f.loaders.length, 1);
  f.loaders[0].onload();
  assert.match(f.status.textContent, /新圖.png/);
});
test('讀取拒絕、取消檔案選擇及卸載均安全處理', async () => {
  const f = fixture();
  await f.select({...file(), slice: () => {throw Error('read');}});
  assert.equal(f.root.dataset.previewState, 'error');
  f.input.files = []; await f.input.dispatch('change');
  assert.equal(f.root.dataset.previewState, 'saved');
  await f.select(); const stale = f.loaders[0].onload;
  f.controller.dispose(); stale();
  assert.deepEqual(f.revoked, ['blob:1']);
  assert.equal(f.image.hidden, true);
});
test('移除與上傳互斥且不影響其他車色及主圖', async () => {
  const f = fixture('/saved.png'), main = fixture('', false);
  await f.select(); f.loaders[0].onload();
  await main.select(); main.loaders[0].onload();
  f.remove.checked = true; f.remove.dispatch('change');
  assert.equal(f.input.value, '');
  assert.equal(f.image.hidden, true);
  assert.match(f.status.textContent, /儲存後移除/);
  assert.equal(main.image.hidden, false);
  await f.select();
  assert.equal(f.remove.checked, false);
  f.controller.reset();
  assert.equal(f.image.src, '/saved.png');
  assert.equal(main.root.dataset.previewState, 'pending');
});
test('主圖驗證錯誤會展開進階區，避免隱藏錯誤', () => {
  const f = fixture('', false);
  f.input.dispatch('invalid');
  assert.equal(f.details.open, true);
});
