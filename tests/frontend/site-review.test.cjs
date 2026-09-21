const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('公告受眾只展開相應清單，搜尋後批次勾選不影響其他結果', () => {
  const listeners=[];
  const audience={value:'all',addEventListener:(e,f)=>listeners.push(f)};
  const makePicker=kind=>{
    const search={value:'',addEventListener(e,f){this.handler=f;}};
    const rows=['新北 甲車行','台北 乙車行'].map(text=>({textContent:text,parentElement:{hidden:false}}));
    const boxes=rows.map(row=>({checked:false,closest:()=>row}));
    const button={dataset:{recipientSelect:'yes'},addEventListener(e,f){this.handler=f;}};
    return {dataset:{audience:kind},closest:()=>({querySelector:()=>audience}),querySelector:()=>search,
      querySelectorAll:s=>s.includes('checkbox')?boxes:[button],search,boxes,button};
  };
  const dealers=makePicker('dealers'),people=makePicker('selected');
  vm.runInNewContext(fs.readFileSync('static/js/recipient-picker.js','utf8'),{document:{querySelectorAll:()=>[dealers,people]}});
  assert.equal(dealers.hidden,true);assert.equal(people.hidden,true);
  audience.value='dealers';listeners.forEach(f=>f());
  assert.equal(dealers.hidden,false);assert.equal(people.hidden,true);
  dealers.search.value='新北';dealers.search.handler();dealers.button.handler();
  assert.deepEqual(dealers.boxes.map(x=>x.checked),[true,false]);
  audience.value='selected';listeners.forEach(f=>f());
  assert.equal(dealers.hidden,true);assert.equal(people.hidden,false);
  assert.equal(dealers.boxes[0].checked,true);
});

test('公告圖片預覽驗證檔案、撤銷舊預覽，忽略過期解碼錯誤', () => {
  const events = {}, windowEvents = {}, revoked = [];
  const container = {children:[],replaceChildren(){this.children=[];},append(x){this.children.push(x);}};
  const status = {textContent:''};
  const form = {querySelector:s=>s==='[data-announcement-previews]'?container:status};
  const input = {files:[],closest:()=>form,setCustomValidity(message){this.error=message;},addEventListener:(e,f)=>events[e]=f};
  let sequence=0;
  vm.runInNewContext(fs.readFileSync('static/js/announcement-images.js','utf8'), {
    document:{querySelectorAll:s=>s==='[data-announcement-upload]'?[input]:[],createElement:tag=>({tag,dataset:{},children:[],addEventListener(){},append(...children){this.children.push(...children);}})},
    window:{addEventListener:(e,f)=>windowEvents[e]=f},
    URL:{createObjectURL:()=>`blob:${++sequence}`,revokeObjectURL:u=>revoked.push(u)}
  });
  const file = {name:'<img onerror=bad>.png',type:'image/png',size:100};
  input.files=[file];events.change();
  assert.equal(container.children.length,1);
  assert.equal(container.children[0].children[1].textContent,file.name);
  const oldImage=container.children[0].children[0];
  input.files=[{...file,name:'new.png'}];events.change();
  oldImage.onerror();
  assert.equal(input.error,'');
  assert.deepEqual(revoked,['blob:1']);
  container.children[0].children[0].onerror();
  assert.match(input.error,/無法讀取/);
  for (const files of [[{...file,size:9*1024*1024}],Array(9).fill(file),Array(4).fill({...file,size:7*1024*1024}),[{...file,type:'image/svg+xml'}]]) {
    input.files=files;events.change();
    assert.match(input.error,/最多/);
    assert.equal(container.children.length,0);
  }
  input.files=[];events.change();assert.equal(input.error,'');assert.equal(status.textContent,'');
  input.files=[file];events.change();windowEvents.pagehide();
  assert.equal(container.children.length,0);
  assert.ok(revoked.includes('blob:3'));
});

test('首頁頁籤本地切換與方向鍵導覽，不重新載入文件', () => {
  const element = (id, active=false) => ({id, dataset:{panel:id.replace('tab-','news-')}, attrs:active?{'aria-current':'page'}:{}, events:{},
    setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},hasAttribute(k){return k in this.attrs;},
    addEventListener(k,v){this.events[k]=v;},focus(){this.focused=true;},click(){this.events.click({preventDefault(){}});}});
  const tabs=[element('tab-announcements',true),element('tab-releases')];
  const panels=Object.fromEntries(tabs.map(t=>[t.dataset.panel,element(t.dataset.panel)]));
  const nav={querySelectorAll:()=>tabs,setAttribute(){}};
  let url='';
  vm.runInNewContext(fs.readFileSync('static/js/home-news.js','utf8'),{document:{querySelectorAll:()=>[nav],getElementById:id=>panels[id]},URL,location:{href:'https://example.test/?page=2'},history:{replaceState:(_a,_b,value)=>{url=String(value);}}});
  tabs[1].click();
  assert.equal(panels['news-announcements'].hidden,true);
  assert.equal(panels['news-releases'].hidden,false);
  assert.match(url,/page=2&news=releases/);
  tabs[1].events.keydown({key:'Home',preventDefault(){}});
  assert.equal(tabs[0].focused,true);
  assert.equal(tabs[0].attrs['aria-selected'],'true');
});

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
