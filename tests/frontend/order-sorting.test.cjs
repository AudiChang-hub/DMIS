const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/order-sorting.js', 'utf8');
// order-sorting.js 以 document 事件委派處理排序連結（1.72.3：頁籤局部替換列表後仍可用）。
function click(current, key, extra = {}) {
  let callback, target;
  const controls = {dataset:{orderSort:current}};
  const link = {dataset:{orderSortKey:key}};
  vm.runInNewContext(source, {document:{querySelector:()=>controls,addEventListener:(_,fn)=>{callback=fn;}},URL,
    location:{href:'https://example.test/orders/?q=abc&status=completed&page=3&per_page=25',assign:url=>{target=url;}}});
  callback({button:0,preventDefault(){},target:{closest:()=>link},...extra});
  return target && new URL(target);
}
test('單欄切換、追加順位、清除及保留搜尋',()=>{
  assert.equal(click('established_on','established_on').searchParams.get('sort'),'-established_on');
  assert.equal(click('established_on','profit').searchParams.get('sort'),'established_on,profit');
  assert.equal(click('established_on,profit','established_on').searchParams.get('sort'),'-established_on,profit');
  assert.equal(click('established_on,profit','profit').searchParams.get('sort'),'established_on,-profit');
  assert.equal(click('-established_on,profit','established_on').searchParams.get('sort'),'established_on,profit');
  const result=click('profit','owner_name');
  assert.equal(result.searchParams.get('sort'),'profit,owner_name');
  assert.equal(result.searchParams.get('page'),null);
  assert.equal(result.searchParams.get('q'),'abc');
  assert.equal(result.searchParams.get('status'),'completed');
  assert.equal(result.searchParams.get('per_page'),'25');
  assert.equal(click('profit',undefined).searchParams.get('sort'),null);
  assert.equal(click('profit','owner_name',{ctrlKey:true}),undefined);
});
test('點到排序連結以外的地方不處理',()=>{
  let callback, target;
  vm.runInNewContext(source, {document:{querySelector:()=>({dataset:{orderSort:''}}),addEventListener:(_,fn)=>{callback=fn;}},URL,
    location:{href:'https://example.test/orders/',assign:url=>{target=url;}}});
  callback({button:0,preventDefault(){throw new Error('不應攔截');},target:{closest:()=>null}});
  assert.equal(target,undefined);
});
