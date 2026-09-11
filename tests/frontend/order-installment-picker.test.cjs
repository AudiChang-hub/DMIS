const test = require('node:test');
const assert = require('node:assert/strict');
const {create, companyNames, companyOptions} = require('../../static/js/order-installment-picker.js');
const options = [
  {company:'甲公司',periods:12,monthly_amount:6000,opening_fee:500},
  {company:'甲公司',periods:24,monthly_amount:3200,opening_fee:600},
  {company:'乙公司',periods:36,monthly_amount:2400,opening_fee:800},
];
class Control {
  constructor(value='') { this.value=value; this.listeners={}; this.children=[]; this.attrs={}; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  dispatchEvent(event) { for (const callback of this.listeners[event.type] || []) callback(event); }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children=[]; this.value=''; }
  setAttribute(name,value) { this.attrs[name]=value; }
}
function setup(fetcher, values={}) {
  const elements={};
  for (const id of ['installment-company-choice','installment-period-choice','installment-manual-toggle','installment-apply',
    'id_installment_company','id_installment_periods','id_installment_monthly','id_installment_opening_fee']) elements[id]=new Control(values[id] || '');
  const manualFields=[{},{}];
  const doc={getElementById:id=>elements[id],querySelectorAll:()=>manualFields,createElement:()=>new Control()};
  const config={document:doc,fetcher,endpoint:'/api/plans/',orderId:'41',vehicleModel:new Control('7'),paymentType:new Control('installment'),hint:new Control()};
  return {elements,config,manualFields,picker:create(config)};
}
const response = (items=options) => ({ok:true,json:async()=>({options:items,order_date:'2025-09-01',version:{effective_from:'2025-01-01'}})});
const original = {'id_installment_company':'甲公司','id_installment_periods':'12','id_installment_monthly':'5900','id_installment_opening_fee':'0'};

test('公司去重且期數只顯示對應公司',()=>{
  assert.deepEqual(companyNames(options),['甲公司','乙公司']);
  assert.deepEqual(companyOptions(options,'甲公司').map(x=>x.periods),[12,24]);
});
test('載入舊訂單方案帶 order_id，保留人工金額及零開辦費',async()=>{
  let url;
  const {picker,elements,config}=setup(async value=>{url=value;return response();},original);
  await picker.load();
  assert.match(url,/order_id=41/);
  for(const [key,value] of Object.entries(original)) assert.equal(elements[key].value,value);
  assert.equal(elements['installment-period-choice'].value,'12');
  assert.match(config.hint.textContent,/2025-09-01/);
  assert.match(config.hint.textContent,/保留原訂單/);
});
test('明確選取公司和期數才帶入，且可重新套用同一期方案',async()=>{
  const {picker,elements}=setup(async()=>response(),original);
  await picker.load();
  elements['installment-apply'].dispatchEvent(new Event('click'));
  assert.equal(elements.id_installment_opening_fee.value,'500');
  const company=elements['installment-company-choice'];
  company.value='乙公司'; company.dispatchEvent(new Event('change'));
  assert.equal(elements.id_installment_periods.value,'');
  const periods=elements['installment-period-choice'];
  assert.deepEqual(periods.children.map(x=>x.value),['','36']);
  periods.value='36'; periods.dispatchEvent(new Event('change'));
  assert.equal(elements.id_installment_company.value,'乙公司');
  assert.equal(elements.id_installment_periods.value,'36');
  assert.equal(elements.id_installment_monthly.value,'2400');
  assert.equal(elements.id_installment_opening_fee.value,'800');
});
test('無有效版本及歷史公司已不存在時顯示人工欄位且保留原值',async()=>{
  for(const items of [[],[options[2]]]) {
    const {picker,elements,manualFields}=setup(async()=>response(items),original);
    await picker.load();
    assert.ok(manualFields.every(field=>!field.hidden));
    for(const [key,value] of Object.entries(original)) assert.equal(elements[key].value,value);
  }
});
test('HTTP 錯誤不清空原值並提供可操作的人工欄位',async()=>{
  const {picker,elements,manualFields,config}=setup(async()=>({ok:false,json:async()=>({error:'禁止存取'})}),original);
  await picker.load();
  assert.ok(manualFields.every(field=>!field.hidden));
  assert.equal(elements.id_installment_monthly.value,'5900');
  assert.match(config.hint.textContent,/讀取失敗/);
});
test('切換車型後舊回應不能蓋掉新選單',async()=>{
  const pending=[];
  const {picker,elements,config}=setup(()=>new Promise(resolve=>pending.push(resolve)));
  const first=picker.load(); config.vehicleModel.value='8'; const second=picker.load();
  pending[1](response([options[2]])); await second;
  pending[0](response([options[0]])); await first;
  assert.deepEqual(elements['installment-company-choice'].children.map(x=>x.value),['','乙公司']);
});
test('選單模式只驗可見選單，非分期不要求選取',async()=>{
  const {picker,elements,config,manualFields}=setup(async()=>response(),original);
  await picker.load();
  assert.ok(manualFields.every(field=>field.hidden));
  assert.equal(elements.id_installment_company.required,false);
  assert.equal(elements['installment-period-choice'].required,true);
  config.paymentType.value='cash'; picker.syncRequired();
  assert.equal(elements['installment-period-choice'].required,false);
});
