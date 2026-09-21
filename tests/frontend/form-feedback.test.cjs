const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function helpers(document) {
  const source = fs.readFileSync('static/js/form-feedback.js', 'utf8');
  const functions = source.slice(source.indexOf('  function fieldLabel('), source.indexOf('  function showToast('));
  return vm.runInNewContext(`(() => {${functions} return {fieldLabel, errorMessage}; })()`, {document, CSS: {escape: value => value}});
}

test('同頁重複 id_reason 時折扣申請只取自己的標籤，取消表單保持原意', () => {
  const {errorMessage} = helpers({querySelector() {throw new Error('不應跨表單搜尋');}});
  for (const label of ['申請原因', '取消原因', '修改原因']) {
    const input = {id:'id_reason', name:'reason', form:{querySelector: () => ({textContent: `${label} 必填`})}, closest:() => null, validity:{valueMissing:true}};
    assert.equal(errorMessage(input), `請填寫「${label}」。`);
  }
});

test('沒有 for 的包覆標籤及欄位名稱仍可作提示，不誤用其他表單標籤', () => {
  const {fieldLabel, errorMessage} = helpers({querySelector() {throw new Error('不應跨表單搜尋');}});
  const input = {id:'local', name:'reason', form:{querySelector:() => null}, closest: selector => selector === 'label' ? {textContent:'申請原因'} : null, validity:{typeMismatch:true}};
  assert.equal(fieldLabel(input), '申請原因');
  assert.equal(errorMessage(input), '「申請原因」格式不正確，請重新確認。');
  input.closest = () => null;
  assert.equal(fieldLabel(input), 'reason');
});
