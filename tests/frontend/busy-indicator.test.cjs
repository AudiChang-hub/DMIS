const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {isTrackedLink, isTrackedForm, isActivationKey, messageFor} = require('../../static/js/busy-indicator.js');

const page = 'https://dmis.example/orders/?page=2';

function anchor(href, attrs = {}) {
  return {
    href: new URL(href, page).href,
    dataset: attrs.dataset || {},
    getAttribute: name => (name === 'href' ? href : attrs[name] ?? null),
    hasAttribute: name => name in attrs,
  };
}

const click = (extra = {}) => ({defaultPrevented: false, button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, ...extra});

test('站內換頁連結顯示處理中，另開分頁、下載、錨點與外部網站不顯示', () => {
  assert.equal(isTrackedLink(anchor('/orders/12/'), click(), page), true);
  assert.equal(isTrackedLink(anchor('?page=3'), click(), page), true);
  assert.equal(isTrackedLink(anchor('/orders/12/', {target: '_blank'}), click(), page), false);
  assert.equal(isTrackedLink(anchor('/files/a.pdf', {download: ''}), click(), page), false);
  assert.equal(isTrackedLink(anchor('#drafts'), click(), page), false);
  assert.equal(isTrackedLink(anchor('?page=2#drafts'), click(), page), false);
  assert.equal(isTrackedLink(anchor('https://maps.google.com/'), click(), page), false);
  assert.equal(isTrackedLink(anchor('tel:0912000000'), click(), page), false);
});

test('頁面已自行處理的點擊、修飾鍵與標記不追蹤的連結不顯示', () => {
  assert.equal(isTrackedLink(anchor('/orders/12/'), click({defaultPrevented: true}), page), false);
  assert.equal(isTrackedLink(anchor('/orders/12/'), click({ctrlKey: true}), page), false);
  assert.equal(isTrackedLink(anchor('/orders/12/', {dataset: {noBusy: ''}}), click(), page), false);
});

test('一般送出顯示處理中，下載與另開分頁的表單不顯示', () => {
  const form = (attrs = {}, dataset = {}) => ({dataset, getAttribute: name => attrs[name] ?? null});
  assert.equal(isTrackedForm(form()), true);
  assert.equal(isTrackedForm(form({target: '_blank'})), false);
  assert.equal(isTrackedForm(form({}, {download: 'true'})), false);
  assert.equal(isTrackedForm(form({}, {noBusy: ''})), false);
  assert.equal(isTrackedForm(form(), {getAttribute: () => '_blank'}), false);
});

test('提示文字依操作類型，等候過久改為請勿關閉頁面', () => {
  assert.equal(messageFor('navigate', false), '正在開啟頁面…');
  assert.equal(messageFor('submit', false), '正在送出，請稍候…');
  assert.equal(messageFor('request', false), '處理中，請稍候…');
  assert.match(messageFor('submit', true), /不要關閉/);
});

test('打字不算按下功能，只有在按鈕、連結、開關上按 Enter／空白鍵才算', () => {
  const at = selector => ({closest: s => (s.split(',').some(part => part.trim() === selector) ? {} : null)});
  assert.equal(isActivationKey({key: 'a', target: at('input')}), false);
  assert.equal(isActivationKey({key: ' ', target: at('input')}), false);
  assert.equal(isActivationKey({key: 'Enter', target: at('textarea')}), false);
  assert.equal(isActivationKey({key: 'Enter', target: at('input')}), true);
  assert.equal(isActivationKey({key: ' ', target: at('button')}), true);
});

test('定時輪詢、上線狀態與自動儲存不顯示操作中提示', () => {
  const order = fs.readFileSync('templates/sales/_order_form_scripts.html', 'utf8');
  for (const endpoint of ['/api/id-card-ocr/${jobId}/`', '/edit/presence/`', '/presence/`', "draft_save' %}\""]) {
    const at = order.indexOf(endpoint);
    assert.ok(at > 0, endpoint);
    assert.match(order.slice(at, at + 120), /busy: false/, endpoint);
  }
  assert.match(fs.readFileSync('static/js/app-update.js', 'utf8'), /busy: false/);
  assert.match(fs.readFileSync('static/js/legacy-import-master-workspace.js', 'utf8'), /busy: false/);
});