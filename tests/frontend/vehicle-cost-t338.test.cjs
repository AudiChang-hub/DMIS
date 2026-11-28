// T-338：成本卡下方的黃色提示、收支的「改回依規則計算」跟著自動儲存換新（沿用 T-331 的 swapVehicleCostCard）。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const workspace = require('../../static/js/order-workspace.js');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/order-workspace.js'), 'utf8');
const finance = fs.readFileSync(path.join(__dirname, '../../static/js/order-finance.js'), 'utf8');

const fakeScope = nodes => ({
  queried: [],
  querySelectorAll(selector) { this.queried.push(selector); return nodes; },
});
const node = html => ({outerHTML: html});

test('黃色提示：找不到規則時換入提示，填了成本後換回空位', () => {
  const placeholder = node('<template data-vehicle-cost-warning></template>');
  const warning = '<div class="message warning" data-vehicle-cost-warning>目前找不到符合此車型與領牌日期的成本規則，補建前無法完成領牌。</div>';
  const scope = fakeScope([placeholder]);
  workspace.swapVehicleCostCard(scope, warning, '[data-vehicle-cost-warning]');
  assert.deepEqual(scope.queried, ['[data-vehicle-cost-warning]']);
  assert.equal(placeholder.outerHTML, warning);
  const shown = node(warning);
  workspace.swapVehicleCostCard(fakeScope([shown]), '<template data-vehicle-cost-warning></template>', '[data-vehicle-cost-warning]');
  assert.equal(shown.outerHTML, '<template data-vehicle-cost-warning></template>');
});

test('改回依規則計算：人工輸入後出現按鈕，改回後換回空位；回應沒有 HTML 時不動', () => {
  const slot = node('<template data-vehicle-cost-reset></template>');
  const button = '<p class="ledger-row__reset" data-vehicle-cost-reset><button type="submit" form="vehicle-cost-reset-form">改回依規則計算</button></p>';
  workspace.swapVehicleCostCard(fakeScope([slot]), button, '[data-vehicle-cost-reset]');
  assert.equal(slot.outerHTML, button);
  workspace.swapVehicleCostCard(fakeScope([slot]), undefined, '[data-vehicle-cost-reset]');
  assert.equal(slot.outerHTML, button);
});

test('沒帶 selector 時照舊只換成本卡（T-331 行為不變）', () => {
  const scope = fakeScope([node('<template data-vehicle-cost-card></template>')]);
  workspace.swapVehicleCostCard(scope, '<section data-vehicle-cost-card></section>');
  assert.deepEqual(scope.queried, ['[data-vehicle-cost-card]']);
});

test('自動儲存成功的流程套用三份 HTML，位置在成本卡同一處', () => {
  const success = source.slice(source.indexOf('if (payload.registration_html)'), source.indexOf("form.dispatchEvent(new CustomEvent('workspace-saved'"));
  assert.match(success, /swapVehicleCostCard\(root, payload\.vehicle_cost_card_html\)/);
  assert.match(success, /swapVehicleCostCard\(root, payload\.vehicle_cost_warning_html, '\[data-vehicle-cost-warning\]'\)/);
  assert.match(success, /swapVehicleCostCard\(root, payload\.vehicle_cost_reset_html, '\[data-vehicle-cost-reset\]'\)/);
});

test('改回存好後，收支成本列的來源標籤改回系統帶入', () => {
  const handler = finance.slice(finance.indexOf("getElementById('vehicle-cost-reset-form')"), finance.indexOf("document.addEventListener('inplace:updated'"));
  assert.match(handler, /addEventListener\('workspace-saved'/);
  assert.match(handler, /ledgerSource = 'system'/);
  assert.match(handler, /'系統帶入'/);
});
