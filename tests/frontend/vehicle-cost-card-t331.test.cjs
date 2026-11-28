// T-331：收支改了車輛成本、自動儲存成功後，領牌步驟的「車輛結算成本」卡換成伺服器回傳的新版，不必重新整理。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const workspace = require('../../static/js/order-workspace.js');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/order-workspace.js'), 'utf8');

const fakeScope = nodes => ({
  queried: [],
  querySelectorAll(selector) { this.queried.push(selector); return nodes; },
});
const card = html => ({outerHTML: html});

test('自動儲存回傳新卡片：畫面上的車輛結算成本卡換成新金額、標籤與說明', () => {
  const old = card('<section class="figure-card" data-vehicle-cost-card><dd>$60,000</dd></section>');
  const scope = fakeScope([old]);
  const fresh = '<section class="figure-card" data-vehicle-cost-card><span class="ledger-tag ledger-tag--manual">人工輸入</span><dd>$59,980</dd></section>';
  assert.equal(typeof workspace.swapVehicleCostCard, 'function');
  workspace.swapVehicleCostCard(scope, fresh);
  assert.deepEqual(scope.queried, ['[data-vehicle-cost-card]']);
  assert.equal(old.outerHTML, fresh);
});

test('回應沒有卡片（儲存失敗或其他回應）時，卡片維持原值', () => {
  const original = '<section class="figure-card" data-vehicle-cost-card><dd>$60,000</dd></section>';
  const old = card(original);
  assert.equal(typeof workspace.swapVehicleCostCard, 'function');
  workspace.swapVehicleCostCard(fakeScope([old]), undefined);
  workspace.swapVehicleCostCard(fakeScope([old]), null);
  assert.equal(old.outerHTML, original);
});

test('改回依規則時換成規則的顯示；尚未出現的卡片（空位）也能換入', () => {
  const placeholder = card('<template data-vehicle-cost-card></template>');
  const ruled = '<section class="figure-card" data-vehicle-cost-card><span class="ledger-tag ledger-tag--estimate">預估</span><dd>$60,000</dd></section>';
  workspace.swapVehicleCostCard(fakeScope([placeholder]), ruled);
  assert.equal(placeholder.outerHTML, ruled);
});

test('自動儲存成功的流程會套用 vehicle_cost_card_html（與其他卡片同一處換新）', () => {
  const success = source.slice(source.indexOf('if (payload.registration_html)'), source.indexOf("form.dispatchEvent(new CustomEvent('workspace-saved'"));
  assert.match(success, /swapVehicleCostCard\(root, payload\.vehicle_cost_card_html\)/);
});
