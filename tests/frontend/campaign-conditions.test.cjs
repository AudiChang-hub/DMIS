const test = require('node:test');
const assert = require('node:assert/strict');
const {matches} = require('../../static/js/campaign-conditions.js');

// T-149 獎勵活動條件預覽：與伺服器 campaign_conditions.vehicle_matches 相同語意。
const suzukiGas = {id: '1', brand: 'suzuki', energy: 'gas'};
const ereadyElectric = {id: '2', brand: 'eready', energy: 'electric'};
const gogoroLight = {id: '3', brand: 'gogoro', energy: 'light_electric'};

test('same condition is any-of, different conditions must all match', () => {
  assert.equal(matches(suzukiGas, ['suzuki'], ['gas'], []), true);
  assert.equal(matches(suzukiGas, ['suzuki', 'eready'], [], []), true);
  assert.equal(matches(ereadyElectric, ['suzuki'], ['electric'], []), false);
  assert.equal(matches(gogoroLight, [], ['electric', 'light_electric', 'micro_electric'], []), true);
});

test('specified models narrow the result and empty lists do not restrict', () => {
  assert.equal(matches(suzukiGas, [], [], ['1']), true);
  assert.equal(matches(ereadyElectric, [], [], ['1']), false);
  assert.equal(matches(ereadyElectric, [], [], []), true);
});
