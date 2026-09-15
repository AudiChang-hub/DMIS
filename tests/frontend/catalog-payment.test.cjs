const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = name => fs.readFileSync(path.join(__dirname, '../../static/js', name), 'utf8');

test('付款摘要跟隨選取與返回頁面狀態，不寫入 HTML', () => {
  const summary = {textContent:''};
  const inputs = ['現金','公司／24 期'].map((label,i) => ({checked:!i,dataset:{paymentLabel:label},
    addEventListener(type,fn){this.change=fn;}}));
  let restore;
  vm.runInNewContext(script('catalog-payment.js'), {document:{querySelector:()=>summary,querySelectorAll:()=>inputs},
    window:{addEventListener(type,fn){restore=fn;}}});
  assert.equal(summary.textContent,'現金');
  inputs[0].checked=false; inputs[1].checked=true; inputs[1].change();
  assert.equal(summary.textContent,'公司／24 期');
  inputs[1].dataset.paymentLabel='<img onerror=alert(1)>'; restore();
  assert.equal(summary.textContent,'<img onerror=alert(1)>');
  assert.equal(summary.innerHTML, undefined);
});

test('更換方案清除舊確認與期款，保留車主／備註並要求重選', () => {
  const events=[];
  const nodes={};
  for(const id of ['id_catalog_selection','id_installment_company','id_installment_periods','id_installment_monthly','id_installment_opening_fee'])
    nodes[id]={value:'old',dispatchEvent:event=>events.push(event.type)};
  nodes.id_payment_type={value:'installment',dispatchEvent:event=>events.push('payment:'+event.type)};
  nodes.id_owner_name={value:'原車主'}; nodes.id_note={value:'原備註'};
  for(const id of ['vehicle','payment']) nodes[id]={open:false,querySelector:()=>({focus(){}})};
  const summary={hidden:false}; let change;
  vm.runInNewContext(script('catalog-intake.js'), {Event:class {constructor(type){this.type=type;}},document:{
    getElementById:id=>nodes[id],querySelector:selector=>selector==='[data-catalog-change]'?{addEventListener(type,fn){change=fn;}}:summary}});
  change();
  assert.equal(nodes.id_catalog_selection.value,'');
  assert.equal(nodes.id_installment_periods.value,'');
  assert.equal(nodes.id_owner_name.value,'原車主'); assert.equal(nodes.id_note.value,'原備註');
  assert.equal(nodes.vehicle.open,true); assert.equal(nodes.payment.open,true); assert.equal(summary.hidden,true);
  assert.deepEqual(events,['payment:change','input']);
});
