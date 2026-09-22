const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('static/js/assisted-order.js', 'utf8');
function page(kind = 'store', revision = '') {
  function field(value) { return {value, listeners:{}, addEventListener(type, fn){this.listeners[type] = fn;}}; }
  const source = field('1'), type = field(kind), confirmed = {checked:true}, version = field(revision);
  const summary = {textContent:''};
  const block = {hidden:false, querySelector:()=>summary};
  const fields = {id_source:source, id_source_type:type, id_assisted_company_confirmed:confirmed,
    id_assisted_company_revision:version, 'assisted-companies':{textContent:JSON.stringify({'1':{
      legal_name:'試作車行',address:'測試地址',phone:'123',tax_id:'12345678',revision:2}})}};
  vm.runInNewContext(code, {document:{querySelector:()=>block,getElementById:id=>fields[id]}});
  return {source,type,confirmed,version,summary,block};
}
test('company confirmation appears only for assisted dealership orders', () => {
  const p = page();
  assert.equal(p.block.hidden, true);
  assert.equal(p.confirmed.required, false);
  p.type.value='dealer';p.type.listeners.change();
  assert.equal(p.block.hidden, false);
  assert.equal(p.confirmed.required, true);
  assert.equal(p.confirmed.checked, false);
  assert.match(p.summary.textContent,/試作車行/);
  assert.equal(p.version.value,'2');
});
test('restored confirmation requires unchanged company revision', () => {
  assert.equal(page('dealer','2').confirmed.checked,true);
  assert.equal(page('dealer','1').confirmed.checked,false);
});
test('changing dealership clears confirmation and does not reuse a company', () => {
  const p = page('dealer','2');
  p.source.value='404';p.source.listeners.change();
  assert.equal(p.confirmed.checked,false);
  assert.equal(p.version.value,'');
  assert.match(p.summary.textContent,/admin/);
});
