const test = require('node:test');
const assert = require('node:assert/strict');
const {matchesModel, initModelFilters} = require('../../static/js/dealer-bonus-model-filter.js');

class Node extends EventTarget {
  constructor(properties = {}) { super(); Object.assign(this, {hidden: false, textContent: '', value: ''}, properties); }
  focus() { this.focused = true; }
  scrollIntoView() {}
}
function fixture({locked = false, invalid = false} = {}) {
  const brand = value => ({value, selected: value === 'SUZUKI', dataset: {bonusBrand: value.toLowerCase()}});
  const model = (value, brand, energy, selected = false) => ({value, selected, hidden: false, textContent: value, dataset: {bonusBrand: brand, bonusEnergy: energy}});
  const brands = new Node({options: [brand('SUZUKI'), brand('SYM')]});
  const energy = new Node({value: invalid ? 'electric' : 'gas'});
  const models = new Node({options: [model('S 油車', 'suzuki', 'gas', true), model('S 電車', 'suzuki', 'electric'), model('SYM 油車', 'sym', 'gas')]});
  const notice = new Node(); const detail = new Node(); const confirm = new Node(); const restore = new Node(); const status = new Node();
  const nodes = {'[name="brands"]': brands, '[name="energy_type"]': energy, '[name="vehicle_models"]': models, '[data-model-conflict]': notice,
    '[data-model-conflict-detail]': detail, '[data-model-conflict-confirm]': confirm, '[data-model-conflict-restore]': restore, '[data-model-filter-status]': status};
  const form = new Node({hasAttribute: () => locked, querySelector: selector => nodes[selector]});
  initModelFilters(form);
  const change = field => field.dispatchEvent(new Event('change'));
  const submit = () => form.dispatchEvent(new Event('submit', {cancelable: true}));
  const visible = () => models.options.filter(option => !option.hidden).map(option => option.value);
  return {brands, energy, models, notice, detail, confirm, restore, status, form, change, submit, visible};
}

test('條件採品牌聯集與能源交集；未選不限且不擴大到其他能源', () => {
  assert.equal(matchesModel({brand:'sym', energy:'gas'}, ['suzuki','sym'], 'gas'), true);
  assert.equal(matchesModel({brand:'sym', energy:'electric'}, ['suzuki','sym'], 'gas'), false);
  assert.equal(matchesModel({brand:'sym', energy:'gas'}, ['suzuki'], ''), false);
  assert.equal(matchesModel({brand:'sym', energy:'gas'}, [], ''), true);
  assert.equal(matchesModel({brand:'sym-child', energy:'gas'}, ['sym'], ''), false);
});
test('初始化與多品牌變更立刻篩選，不清除相符選取', () => {
  const f = fixture(); assert.deepEqual(f.visible(), ['S 油車']);
  f.brands.options[1].selected = true; f.change(f.brands);
  assert.deepEqual(f.visible(), ['S 油車', 'SYM 油車']);
  assert.equal(f.models.options[0].selected, true); assert.equal(f.notice.hidden, true); assert.equal(f.submit(), true);
});
test('切換能源保留不符選取並阻擋儲存；取消還原條件', () => {
  const f = fixture(); f.energy.value = 'electric'; f.change(f.energy);
  assert.deepEqual(f.visible(), ['S 電車']); assert.equal(f.models.options[0].selected, true);
  assert.equal(f.notice.hidden, false); assert.equal(f.submit(), false); assert.equal(f.notice.focused, true);
  assert.match(f.detail.textContent, /不限車型/); assert.equal(f.confirm.textContent, '移除並設為不限車型');
  f.restore.dispatchEvent(new Event('click'));
  assert.equal(f.energy.value, 'gas'); assert.deepEqual(f.visible(), ['S 油車']); assert.equal(f.submit(), true);
});
test('確認僅移除不符車型，保留使用者另外選入的相符車型', () => {
  const f = fixture(); f.energy.value = 'electric'; f.change(f.energy);
  f.models.options[1].selected = true; f.change(f.models);
  assert.equal(f.confirm.textContent, '移除不符車型');
  f.confirm.dispatchEvent(new Event('click'));
  assert.equal(f.models.options[0].selected, false); assert.equal(f.models.options[1].selected, true);
  assert.equal(f.notice.hidden, true); assert.equal(f.submit(), true);
});
test('品牌取消選取可還原，零符合結果不顯示全部', () => {
  const f = fixture(); f.brands.options[0].selected = false; f.brands.options[1].selected = true; f.change(f.brands);
  assert.deepEqual(f.visible(), ['SYM 油車']); f.restore.dispatchEvent(new Event('click'));
  assert.equal(f.brands.options[0].selected, true); assert.equal(f.brands.options[1].selected, false);
  f.energy.value = 'micro_electric'; f.change(f.energy); assert.deepEqual(f.visible(), []); assert.match(f.status.textContent, /沒有符合條件的車型/);
  f.confirm.dispatchEvent(new Event('click')); assert.equal(f.models.options.some(option => option.selected), false);
});
test('驗證失敗回填的不符車型保留，沒有可還原快照時不提供還原', () => {
  const f = fixture({invalid:true}); assert.equal(f.notice.hidden, false); assert.equal(f.restore.hidden, true);
  assert.equal(f.submit(), false); assert.equal(f.models.options[0].selected, true);
});
test('已結算條件不初始化互動或改動選取', () => {
  const f = fixture({locked:true}); assert.equal(f.models.options[0].selected, true); assert.equal(f.status.textContent, '');
});
