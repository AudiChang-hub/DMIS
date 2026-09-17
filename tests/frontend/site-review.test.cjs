const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('另開分頁的證件下載不會永久鎖住原按鈕，一般儲存仍防連點', () => {
  const events = {};
  class Form {
    constructor(target) {this.target=target;this.dataset={};}
    setAttribute() {}
    querySelector() {return null;}
  }
  const document = {addEventListener:(key,fn)=>events[key]=fn,querySelectorAll:()=>[]};
  vm.runInNewContext(fs.readFileSync('static/js/form-feedback.js','utf8'), {document,window:{addEventListener(){}},HTMLFormElement:Form});
  const download = new Form('_blank');
  events.submit({target:download});
  assert.equal(download.dataset.submitting,undefined);
  const normal = new Form('');
  events.submit({target:normal});
  assert.equal(normal.dataset.submitting,'true');
});

test('自訂折數或金額切換，僅啟用對應輸入並預覽總價', () => {
  const field = value => ({value,disabled:false,box:{hidden:false},closest(){return this.box;}});
  const mode=field('rate'),amount=field('1234'),rate=field('9.25'),output={textContent:''},events={};
  const fields={'[name="mode"]':mode,'[name="amount"]':amount,'[name="rate"]':rate,'[data-discount-preview]':output};
  const form={dataset:{discountTotal:'10001'},querySelector:s=>fields[s],addEventListener:(e,f)=>events[e]=f};
  vm.runInNewContext(fs.readFileSync('static/js/discount-preview.js','utf8'),{document:{querySelectorAll:()=>[form]}});
  assert.match(output.textContent,/750 元/);
  assert.equal(amount.disabled,true);
  mode.value='amount'; events.change();
  assert.match(output.textContent,/8,767 元/);
  assert.equal(rate.disabled,true);
  amount.value='20000';events.input();
  assert.match(output.textContent,/有效/);
});
