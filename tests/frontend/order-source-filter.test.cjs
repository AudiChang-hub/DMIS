// T-323：全部訂單「車行／平台」多選的選取規則（打字篩選、多選、整組、清除、摘要文字）。
const test = require('node:test');
const assert = require('node:assert/strict');
const f = require('../../static/js/order-source-filter.js');

const groups = [
  {key: 'store', label: '本店', all: '全部本店', options: [{value: 'house', label: '馭盛'}, {value: '9', label: '合成店員'}]},
  {key: 'dealer', label: '車行', all: '全部車行', options: [
    {value: '1', label: '示範甲車行'}, {value: '2', label: '虛構乙機車'}, {value: '3', label: '示範丙車業', inactive: true}]},
  {key: 'platform', label: '網路平台', all: '全部網路平台', options: [{value: '7', label: '合成網購'}]},
];

test('打字縮小範圍：只留名稱符合的，不分大小寫、忽略空白；整組選項只在沒打字或自己符合時出現', () => {
  const all = f.matchGroups(groups, '');
  assert.deepEqual(all.map((group) => group.all.label), ['全部本店', '全部車行', '全部網路平台']);
  const hit = f.matchGroups(groups, '示範');
  assert.deepEqual(hit.map((group) => group.key), ['dealer']);
  assert.equal(hit[0].all, null);
  assert.deepEqual(hit[0].options.map((option) => option.value), ['1', '3'], '停用的也找得到');
  assert.deepEqual(f.matchGroups(groups, '全部車').map((group) => [group.key, Boolean(group.all), group.options.length]), [['dealer', true, 0]]);
  assert.deepEqual(f.matchGroups(groups, '不存在'), []);
});

test('符合的字切出來標色', () => {
  assert.deepEqual(f.highlight('示範甲車行', '甲'), [{text: '示範', match: false}, {text: '甲', match: true}, {text: '車行', match: false}]);
  assert.deepEqual(f.highlight('示範甲車行', ''), [{text: '示範甲車行', match: false}]);
  assert.deepEqual(f.highlight('示範甲車行', '乙'), [{text: '示範甲車行', match: false}]);
});

test('多選：勾、再勾取消；值依選項順序排好', () => {
  let tokens = f.toggle([], '2', groups);
  tokens = f.toggle(tokens, '1', groups);
  assert.deepEqual(tokens, ['1', '2']);
  assert.equal(f.summarize(tokens, groups), '示範甲車行、虛構乙機車');
  tokens = f.toggle(tokens, '7', groups);
  assert.equal(f.summarize(tokens, groups), '示範甲車行 等 3 家');
  tokens = f.toggle(tokens, '1', groups);
  assert.deepEqual(tokens, ['2', '7']);
});

test('整組：選了整組就只留整組；整組下取消一家改成其餘各家；再點整組取消', () => {
  let tokens = f.toggle(['1', '7'], 'dealer', groups);
  assert.deepEqual(tokens, ['dealer', '7']);
  assert.equal(f.isSelected(tokens, '3', groups), true, '整組選了，組內每家都顯示勾選');
  assert.equal(f.summarize(tokens, groups), '全部車行、合成網購');
  assert.equal(f.summarize(f.toggle(tokens, 'store', groups), groups), '全部本店 等 3 項');
  tokens = f.toggle(tokens, '2', groups);
  assert.deepEqual(tokens, ['1', '3', '7']);
  assert.deepEqual(f.toggle(f.toggle([], 'dealer', groups), 'dealer', groups), []);
});

test('清除與網址值：空值、未知值、重複值都整理掉', () => {
  assert.deepEqual(f.parse('', groups), []);
  assert.deepEqual(f.parse('7, 1,1,bogus,dealer', groups), ['dealer', '7']);
  assert.equal(f.summarize([], groups), '');
  assert.deepEqual(f.labelsOf(['house'], groups), [{value: 'house', label: '馭盛'}]);
});
