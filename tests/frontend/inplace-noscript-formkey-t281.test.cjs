// T-281 QA：給付頁每列的 csrf、next 只放在 noscript 裡。畫面上的 noscript 內容不是欄位，
// 但原地更新換入的新區塊是 DOMParser 解析的（不執行腳本），noscript 裡的 input 會變成真的欄位。
// 同一張表單在兩邊的 formKey 必須相同，第一次存備註時 swap() 才找得到換入後的同一張表單（提示、焦點照舊）。
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {formKey} = require('../../static/js/inplace-regions.js');

function field(name, value, {inNoscript = false} = {}) {
  return {name, value, closest: (selector) => (selector === 'noscript' && inNoscript ? {tagName: 'NOSCRIPT'} : null)};
}

function form(action, fields) {
  return {getAttribute: (key) => (key === 'action' ? action : null), querySelectorAll: () => fields};
}

const action = '/data/dealer-payouts/update/';

function noteForm(key, {parsed}) {
  const fields = [field('key', key), field('action', 'note')];
  // 畫面上（瀏覽器開著 JavaScript）noscript 內容只是文字；DOMParser 解析的文件裡才是 input。
  if (parsed) {
    fields.push(field('csrfmiddlewaretoken', 'token', {inNoscript: true}));
    fields.push(field('next', '/data/dealer-payouts/?dealer=3', {inNoscript: true}));
  }
  return form(action, fields);
}

test('畫面上的備註表單與換入的新版（noscript 解析成欄位）是同一張表單', () => {
  const current = noteForm('commission:23672', {parsed: false});
  const fresh = noteForm('commission:23672', {parsed: true});
  assert.equal(formKey(current), formKey(fresh));
  // swap() 以 formKey 找換入後的同一張表單：第一次存備註就找得到。
  const swappedForms = [noteForm('commission:23666', {parsed: true}), fresh];
  assert.equal(swappedForms.find((candidate) => formKey(candidate) === formKey(current)), fresh);
});

test('換入過一次後（畫面上的 noscript 也有 input）再存，仍是同一張表單', () => {
  assert.equal(formKey(noteForm('commission:23672', {parsed: true})), formKey(noteForm('commission:23672', {parsed: false})));
});

test('不同列、不同動作仍是不同表單；noscript 外的隱藏欄位照舊用來辨識', () => {
  assert.notEqual(formKey(noteForm('commission:23672', {parsed: true})), formKey(noteForm('commission:23666', {parsed: false})));
  const paid = form(action, [field('key', 'commission:23672'), field('action', 'paid')]);
  assert.notEqual(formKey(paid), formKey(noteForm('commission:23672', {parsed: false})));
  const withNext = form(action, [field('key', 'a'), field('next', '/x/')]);
  const withoutNext = form(action, [field('key', 'a')]);
  assert.notEqual(formKey(withNext), formKey(withoutNext));
});
