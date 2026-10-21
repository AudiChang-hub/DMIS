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
function setup(fetcher, values={}, extra=[], extraConfig={}) {
  const elements={};
  for (const id of ['installment-company-choice','installment-period-choice','installment-manual-toggle',
    'id_installment_company','id_installment_periods','id_installment_monthly','id_installment_opening_fee','installment-period-field', ...extra]) elements[id]=new Control(values[id] || '');
  const manualFields=[{},{}];
  const doc={getElementById:id=>elements[id],querySelectorAll:()=>manualFields,createElement:()=>new Control()};
  const config={document:doc,fetcher,endpoint:'/api/plans/',orderId:'41',vehicleModel:new Control('7'),paymentType:new Control('installment'),hint:new Control(),...extraConfig};
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
test('明確選取公司和期數就直接帶入，不需另按套用',async()=>{
  const {picker,elements}=setup(async()=>response(),original);
  await picker.load();
  const sameCompany=elements['installment-period-choice'];
  sameCompany.value='24'; sameCompany.dispatchEvent(new Event('change'));
  assert.equal(elements.id_installment_monthly.value,'3200');
  assert.equal(elements.id_installment_opening_fee.value,'600');
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
  assert.deepEqual(elements['installment-company-choice'].children.map(x=>x.value),['','乙公司','__custom__']);
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

test('其他分期展開人工欄位，不清空原值、不套用方案', async()=>{
  const {picker,elements,manualFields}=setup(async()=>response(),original);
  await picker.load();
  elements['installment-company-choice'].value='__custom__';
  elements['installment-company-choice'].dispatchEvent(new Event('change'));
  assert.ok(manualFields.every(field=>!field.hidden));
  assert.equal(elements['installment-period-choice'].disabled,true);
  assert.equal(elements['installment-period-choice'].required,false);
  for (const [key,value] of Object.entries(original)) assert.equal(elements[key].value,value);
});

test('自訂分期勾選框不顯示，由按鈕切換並同步勾選（使用者 2026-10-20）', async()=>{
  const {picker,elements,manualFields}=setup(async()=>response(),{}, ['id_installment_custom']);
  const custom=elements['id_installment_custom']; custom.checked=false;
  await picker.load();
  const toggle=elements['installment-manual-toggle'];
  assert.ok(manualFields.every(field=>field.hidden));
  toggle.dispatchEvent(new Event('click'));
  assert.equal(custom.checked,true);
  assert.ok(manualFields.every(field=>!field.hidden));
  assert.equal(toggle.textContent,'改用車型方案');
  assert.equal(elements['installment-company-choice'].value,'__custom__');
  assert.equal(elements['installment-period-choice'].disabled,true);
  toggle.dispatchEvent(new Event('click'));
  assert.equal(custom.checked,false);
  assert.equal(elements['installment-company-choice'].value,'');
  assert.ok(manualFields.every(field=>field.hidden));
  assert.equal(toggle.textContent,'其他／自訂分期');
});

test('既有自訂分期訂單載入時直接是人工模式，公司選單標示其他／自訂分期', async()=>{
  const {picker,elements,manualFields}=setup(async()=>response(),{...original,'id_installment_company':'其他融資'}, ['id_installment_custom']);
  elements['id_installment_custom'].checked=true;
  await picker.load();
  assert.ok(manualFields.every(field=>!field.hidden));
  assert.equal(elements['installment-company-choice'].value,'__custom__');
  assert.equal(elements.id_installment_company.value,'其他融資');
  assert.equal(elements.id_installment_monthly.value,'5900');
});

test('自訂分期每期金額＝分期價格÷期數四捨五入，並跟著期數與分期價格更新（使用者 2026-10-21）', async()=>{
  let price=100000;
  const {picker,elements}=setup(async()=>response(),{}, ['id_installment_custom'], {installmentPrice:()=>price});
  elements['id_installment_custom'].checked=false;
  await picker.load();
  elements['installment-manual-toggle'].dispatchEvent(new Event('click'));
  assert.equal(elements['id_installment_custom'].checked,true);
  assert.equal(elements.id_installment_monthly.value,'');
  const periods=elements.id_installment_periods;
  periods.value='24'; periods.dispatchEvent(new Event('input'));
  assert.equal(elements.id_installment_monthly.value,'4167');
  periods.value='36'; periods.dispatchEvent(new Event('input'));
  assert.equal(elements.id_installment_monthly.value,'2778');
  price=90000; picker.syncCustomMonthly();
  assert.equal(elements.id_installment_monthly.value,'2500');
});

test('自訂分期每期金額手動改過就保留，清空後恢復自動帶入', async()=>{
  let price=100000;
  const {picker,elements}=setup(async()=>response(),{'id_installment_periods':'24'}, ['id_installment_custom'], {installmentPrice:()=>price});
  elements['id_installment_custom'].checked=false;
  await picker.load();
  const company=elements['installment-company-choice'];
  company.value='__custom__'; company.dispatchEvent(new Event('change'));
  assert.equal(elements.id_installment_monthly.value,'4167');
  elements.id_installment_monthly.value='4000';
  const periods=elements.id_installment_periods;
  periods.value='12'; periods.dispatchEvent(new Event('input'));
  price=120000; picker.syncCustomMonthly();
  assert.equal(elements.id_installment_monthly.value,'4000');
  elements.id_installment_monthly.value='';
  picker.syncCustomMonthly();
  assert.equal(elements.id_installment_monthly.value,'10000');
});

test('既有自訂分期訂單載入時保留原本的每期金額，不套用公式', async()=>{
  const {picker,elements}=setup(async()=>response(),{...original,'id_installment_company':'其他融資'}, ['id_installment_custom'], {installmentPrice:()=>100000});
  elements['id_installment_custom'].checked=true;
  await picker.load();
  picker.syncCustomMonthly();
  assert.equal(elements.id_installment_monthly.value,'5900');
});

test('車型方案模式不套用自訂分期公式', async()=>{
  const {picker,elements}=setup(async()=>response(),original, ['id_installment_custom'], {installmentPrice:()=>100000});
  elements['id_installment_custom'].checked=false;
  await picker.load();
  picker.syncCustomMonthly();
  assert.equal(elements.id_installment_monthly.value,'5900');
});

test('選其他／自訂分期時隱藏期數與每期金額選單，切回車型方案再出現（使用者 2026-10-21 T-49）', async()=>{
  const {picker,elements}=setup(async()=>response(),{}, ['id_installment_custom']);
  elements['id_installment_custom'].checked=false;
  await picker.load();
  const company=elements['installment-company-choice'], field=elements['installment-period-field'];
  assert.equal(field.hidden,false);
  company.value='__custom__'; company.dispatchEvent(new Event('change'));
  assert.equal(field.hidden,true);
  assert.equal(elements['installment-period-choice'].disabled,true);
  company.value='甲公司'; company.dispatchEvent(new Event('change'));
  assert.equal(field.hidden,false);
  assert.equal(elements['installment-period-choice'].disabled,false);
  const toggle=elements['installment-manual-toggle'];
  toggle.dispatchEvent(new Event('click'));
  assert.equal(company.value,'__custom__');
  assert.equal(field.hidden,true);
  toggle.dispatchEvent(new Event('click'));
  assert.equal(field.hidden,false);
});

test('既有自訂分期訂單的公司與期數剛好跟方案相同，也不顯示方案的期數與每期金額', async()=>{
  const values={...original,'id_installment_periods':'24','id_installment_monthly':'1250'};
  const {picker,elements}=setup(async()=>response(),values, ['id_installment_custom']);
  elements['id_installment_custom'].checked=true;
  await picker.load();
  const periods=elements['installment-period-choice'];
  assert.equal(elements['installment-company-choice'].value,'__custom__');
  assert.equal(elements['installment-period-field'].hidden,true);
  assert.equal(periods.value,'');
  assert.equal(periods.disabled,true);
  assert.equal(periods.required,false);
  assert.equal(elements.id_installment_periods.value,'24');
  assert.equal(elements.id_installment_monthly.value,'1250');
});

test('自訂分期時期數選單即使被改值也不覆寫下方期數與每期金額', async()=>{
  const values={...original,'id_installment_periods':'24','id_installment_monthly':'1250'};
  const {picker,elements}=setup(async()=>response(),values, ['id_installment_custom']);
  elements['id_installment_custom'].checked=true;
  await picker.load();
  const periods=elements['installment-period-choice'];
  periods.value='24'; periods.dispatchEvent(new Event('change'));
  assert.equal(elements.id_installment_company.value,'甲公司');
  assert.equal(elements.id_installment_periods.value,'24');
  assert.equal(elements.id_installment_monthly.value,'1250');
  assert.equal(elements.id_installment_opening_fee.value,'0');
  assert.equal(elements['id_installment_custom'].checked,true);
});

// 自訂分期不留半邊空白（使用者 2026-10-21 T-51）：按鈕併在選單列右側；期數選單隱藏時公司選單延伸到按鈕前。
test('分期方案選擇列：按鈕同列、自訂分期時單欄延伸，窄版上下排', () => {
  const css = require('node:fs').readFileSync('static/css/app.css', 'utf8');
  assert.match(css, /\.installment-picker \{ display: grid; grid-template-columns: minmax\(0, 1fr\) auto; align-items: end;/);
  assert.match(css, /\.installment-picker \.form-grid:has\(> #installment-period-field\[hidden\]\) \{ grid-template-columns: minmax\(0, 1fr\); \}/);
  assert.match(css, /\.installment-picker \{ padding: var\(--inset-pad\); grid-template-columns: minmax\(0, 1fr\); \}/);
});
