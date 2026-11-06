const test = require('node:test');
const assert = require('node:assert/strict');
const {normalize, evaluate} = require('../../static/js/year-month-input.js');

test('自動儲存送回日期寫法時換回 6 碼年月（T-121）', () => {
  assert.equal(normalize('2012-02-01'), '201202');
  assert.equal(normalize('2012/2'), '201202');
  assert.equal(normalize('201202'), '201202');
  assert.equal(normalize('2012年02月'), '201202');
  assert.equal(normalize(''), '');
});

test('換算說明不會出現 NaN', () => {
  const today = new Date(2026, 10, 6);
  assert.equal(evaluate('201202', today).text, '2012 年 2 月・民國 101 年');
  const odd = evaluate('2012-0', today);
  assert.equal(odd.state, 'error');
  assert.doesNotMatch(odd.text, /NaN/);
});
