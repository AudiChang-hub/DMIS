const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/import-row-review.js', 'utf8');

function setup({error=false, primary=true, known=true, loaded=true}={}) {
  const calls=[]; const listeners={};
  const target = id => ({id, focus:opts=>calls.push(['focus',id,opts]), closest:()=>null, scrollIntoView:opts=>calls.push(['scroll',id,opts])});
  const fields={error:target('error'),primary:target('primary'),known:target('known'),summary:target('summary')};
  let click;
  const editor={
    addEventListener:(name,callback)=>listeners[name]=callback,
    querySelector:selector=>selector.startsWith('.has-error') ? (error?fields.error:null) : selector.includes('primary') ? (primary?fields.primary:null) : selector.includes('field') ? (known?fields.known:null) : fields.summary,
    querySelectorAll:()=>[{getAttribute:()=> '#known',addEventListener:(_event,callback)=>click=callback}],
    contains:()=>true,
  };
  const context={document:{readyState:loaded?'complete':'loading', getElementById:id=>id==='row-editor'?editor:fields[id]},window:{addEventListener:(name,callback)=>listeners[name]=callback},requestAnimationFrame:callback=>callback()};
  vm.runInNewContext(source, context);
  return {calls,listeners,click};
}
test('修正定位優先表單錯誤，再選主要差異欄位',()=>{
  assert.equal(setup({error:true}).calls[0][1],'error');
  assert.equal(setup().calls[0][1],'primary');
  assert.equal(setup({primary:false}).calls[0][1],'known');
  assert.equal(setup({primary:false,known:false}).calls[0][1],'summary');
});
test('頁面載入後才定位，避免被瀏覽器的錨點捲動蓋過',()=>{
  const state=setup({loaded:false}); assert.equal(state.calls.length,0);
  state.listeners.load(); assert.equal(state.calls[0][1],'primary');
  assert.equal(state.calls[1][2].behavior,'instant');
});
test('核對摘要可定位其他欄位，不送出或改值',()=>{
  const state=setup(); let prevented=false;
  state.click({preventDefault:()=>prevented=true});
  assert.equal(prevented,true); assert.equal(state.calls.at(-2)[1],'known');
});
test('其他頁面沒有修正表單時不介入',()=>{
  vm.runInNewContext(source,{document:{getElementById:()=>null}});
});
test('使用者已操作時不再強制搶走焦點',()=>{
  const state=setup({loaded:false}); state.listeners.pointerdown(); state.listeners.load();
  assert.equal(state.calls.length,0);
});
