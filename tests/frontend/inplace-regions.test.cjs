const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {formKey, mergeClassNames, classify, failureText, sameDocument} = require('../../static/js/inplace-regions.js');

const base = {
  status: 200, contentType: 'text/html; charset=utf-8',
  requestUrl: 'http://localhost/orders/7/registration-documents/upload/',
  responseUrl: 'http://localhost/orders/7/?tab=registration#registration-documents',
  currentPath: '/orders/7/', hasErrorMessage: false,
};

function fakeForm(action, hidden) {
  const inputs = Object.entries(hidden).map(([name, value]) => ({name, value}));
  return {getAttribute: key => (key === 'action' ? action : null), querySelectorAll: () => inputs};
}

test('上傳或刪除後導回同一頁：原地換新區塊，不換頁', () => {
  assert.equal(classify(base), 'saved');
});

test('伺服器導回同頁但帶錯誤訊息：就地顯示原因，不換掉已填內容', () => {
  assert.equal(classify({...base, hasErrorMessage: true}), 'rejected');
});

test('同網址重新顯示表單（驗證失敗）與存好後導回同網址可以分辨', () => {
  const same = {...base, requestUrl: 'http://localhost/data/print-templates/3/edit/', responseUrl: 'http://localhost/data/print-templates/3/edit/', currentPath: '/data/print-templates/3/edit/'};
  assert.equal(classify(same), 'invalid');
  assert.equal(classify({...same, hasSuccessMessage: true}), 'saved');
  assert.equal(classify({...same, hasSuccessMessage: true, hasErrorMessage: true}), 'invalid');
  assert.equal(classify({...same, status: 409}), 'invalid');
});

test('新增後導到另一頁（例如新範本的編輯頁）才換頁', () => {
  assert.equal(classify({...base, responseUrl: 'http://localhost/data/print-templates/9/edit/'}), 'navigate');
});

test('登入逾時被導到登入頁：不跟著換頁，輸入保留', () => {
  assert.equal(classify({...base, responseUrl: 'http://localhost/login/?next=/orders/7/'}), 'login');
});

test('網路中斷、非 HTML 回應與伺服器錯誤都視為失敗', () => {
  assert.equal(classify({...base, status: 0}), 'network');
  assert.equal(classify({...base, contentType: 'application/json'}), 'failed');
  assert.equal(classify({...base, status: 500, responseUrl: base.requestUrl}), 'failed');
});

test('失敗原因一律中文，伺服器錯誤附查修編號', () => {
  assert.match(failureText(0), /網路中斷/);
  assert.match(failureText(403), /登入或安全憑證已失效/);
  assert.match(failureText(413), /檔案太大/);
  assert.match(failureText(502, 'abc123'), /查修編號：abc123/);
  assert.match(failureText(400), /請確認內容/);
});

test('同一張表單在新舊畫面中用送出網址與文件類型對應，CSRF 不影響', () => {
  const a = fakeForm('/orders/7/registration/upload/', {csrfmiddlewaretoken: 'x', document_type: 'license'});
  const b = fakeForm('/orders/7/registration/upload/', {csrfmiddlewaretoken: 'y', document_type: 'license'});
  const c = fakeForm('/orders/7/registration/upload/', {csrfmiddlewaretoken: 'x', document_type: 'insurance'});
  assert.equal(formKey(a), formKey(b));
  assert.notEqual(formKey(a), formKey(c));
  assert.equal(formKey(null), '');
});

test('步驟狀態取伺服器新版，目前分頁與動畫狀態保留', () => {
  assert.equal(
    mergeClassNames('order-step is-current is-active is-entering', 'order-step is-done is-active'),
    'order-step is-done is-active is-entering',
  );
  assert.equal(mergeClassNames('order-step-tab is-current', 'order-step-tab is-done is-active'), 'order-step-tab is-done');
});

test('只差錨點視為同一份文件', () => {
  assert.ok(sameDocument('http://x/orders/1/?tab=a#b', 'http://x/orders/1/?tab=a'));
  assert.ok(!sameDocument('http://x/orders/1/?tab=a', 'http://x/orders/1/?tab=b'));
});

test('上傳完成不再重新整理頁面，也不跳到頁首', () => {
  const upload = fs.readFileSync('static/js/document-upload-progress.js', 'utf8');
  assert.doesNotMatch(upload, /location\.reload\(/);
  assert.match(upload, /inplace\.refresh\(/);
  const inplace = fs.readFileSync('static/js/inplace-regions.js', 'utf8');
  assert.doesNotMatch(inplace, /location\.reload\(/);
  // 全站 html 是 smooth 捲動，程式定位一律瞬間完成。
  for (const call of inplace.match(/scrollTo\([^)]*\)/g)) assert.match(call, /behavior: "instant"/);
  assert.match(inplace, /focus\(\{preventScroll: true\}\)/);
  const workspace = fs.readFileSync('static/js/order-workspace.js', 'utf8');
  assert.match(workspace, /takeRestore/);
  assert.match(workspace, /function land\(smooth\)/);
});
