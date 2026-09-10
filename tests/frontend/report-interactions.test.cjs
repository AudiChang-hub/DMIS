const test = require('node:test');
const assert = require('node:assert/strict');
const {reportPointText, reportFraction, reportScopeCount, reportPageRange} = require('../../static/js/report-interactions.js');
const {reportToggleSelection} = require('../../static/js/report-interactions.js');
const {reportAxisMaximum} = require('../../static/js/report-interactions.js');
const {reportDebounce} = require('../../static/js/report-interactions.js');
const {reportUpdateError} = require('../../static/js/report-interactions.js');
const {reportOverviewColor, reportMonthSummary} = require('../../static/js/report-interactions.js');
const {reportElectricColor} = require('../../static/js/report-interactions.js');
const {reportAnalysisColor} = require('../../static/js/report-analysis.js');
const {reportBarTooltip,reportBarTooltipText,renderReportBarTooltip} = require('../../static/js/report-tooltip.js');

test('長條彩色明細保留微小數字、原圖顏色並以該長條總數計算占比', () => {
  const data={pointLabel:'2026/09',pointValue:'101',pointDisplay:'101'};
  const items=[{label:'車行',value:100,display:'100',color:'#123456'},{label:'平台',value:1,display:'1',color:'#abcdef'}];
  const tip=reportBarTooltip(data,items,'訂單台數',1000,'完整篩選範圍');
  assert.deepEqual(tip.entries.map(x=>[x.label,x.color,x.percentage]),[['車行','#123456','99.0%'],['平台','#abcdef','1.0%']]);
  assert.equal(tip.total,'101');
  assert.match(reportBarTooltipText(tip,'平台'),/目前指向：平台/);
  assert.match(reportBarTooltipText(tip),/總計：101/);
});
test('未顯示系列獨立列出，不把已顯示分類重新正規化為百分之百', () => {
  const tip=reportBarTooltip({pointLabel:'月份',pointValue:'10',pointDisplay:'10'},[{label:'A',value:4,display:'4',color:'#123'}],'訂單台數',100,'候選分類範圍');
  assert.deepEqual(tip.entries.map(x=>[x.label,x.value,x.percentage]),[['A',4,'40.0%'],['未顯示系列',6,'60.0%']]);
  assert.match(tip.note,/候選分類/);
});
test('基本長條以整圖為分母；平均、零總數與負數不捏造占比', () => {
  const data={pointLabel:'車型',pointValue:'20',pointDisplay:'20',pointColor:'#456'};
  assert.equal(reportBarTooltip(data,null,'訂單台數',80,'完整篩選範圍').entries[0].percentage,'25.0%');
  for(const [value,metric,total] of [['0','訂單台數',0],['-1','訂單車價合計',10],['20','平均車價',80],['20','分析試算',80]]) {
    const tip=reportBarTooltip({...data,pointValue:value},null,metric,total,'完整篩選範圍');
    assert.equal(tip.entries[0].percentage,'—');
  }
});
test('彩色提示只使用文字節點，名稱不作 HTML；長清單不截斷', () => {
  const doc={createElement:()=>({ownerDocument:doc,children:[],style:{},setAttribute(){},append(...children){this.children.push(...children);},set innerHTML(value){throw new Error('不可插入 HTML');}})};
  const tip=doc.createElement(); tip.classList={add(){}}; tip.replaceChildren=()=>{tip.children=[];};
  const entries=Array.from({length:25},(_,i)=>({label:i===0?'<img src=x onerror=alert(1)>':String(i),value:1,display:'1',color:'#123456'}));
  renderReportBarTooltip(tip,reportBarTooltip({pointLabel:'月份',pointValue:'25',pointDisplay:'25'},entries,'訂單台數',25,'完整篩選範圍'));
  const list=tip.children.find(x=>x.className==='report-tooltip-items');
  assert.equal(list.children.length,25);
  assert.equal(list.children[0].children[0].children[1].textContent,entries[0].label);
  assert.equal(list.children[0].children[0].children[0].style.backgroundColor,'#123456');
});

test('人口分類顏色不隨篩選排序漂移且未知分類保留', () => {
  assert.equal(reportAnalysisColor('男性','#000'),'#737373');
  assert.equal(reportAnalysisColor('女性','#000'),'#f15a60');
  assert.equal(reportAnalysisColor('公司或其他','#000'),'#7ac36a');
  assert.equal(reportAnalysisColor('灰','#000'),'#5a9bd4');
  assert.equal(reportAnalysisColor('未列顏色','#123456'),'#123456');
});

test('電動車來源配色獨立，型號兩圖同色且不受排序影響', () => {
  assert.equal(reportElectricColor('車行','#000'), '#f15a60');
  assert.equal(reportElectricColor('網路平台','#000'), '#7ac36a');
  assert.equal(reportOverviewColor('車行','#000'), '#7ac36a');
  assert.equal(reportElectricColor('EV060L','#000'), '#737373');
  assert.equal(reportElectricColor('EV076S','#000'), '#7ac36a');
  assert.equal(reportElectricColor('M02','#000'), '#7dd3ef');
  assert.equal(reportElectricColor('未列型號','#123456'), '#123456');
});

test('原報表整月提示包含全部非零系列及合計，不把月份縮成單一通路', () => {
  const summary = reportMonthSummary('2026/08', [{label:'馭盛',value:29,display:'29'},{label:'車行',value:5,display:'5'},{label:'展場',value:0,display:'0'}], '34');
  assert.equal(summary, '2026/08\n馭盛：29\n車行：5\n總計：34');
  assert.equal(reportPointText({pointSummary:summary}, '訂單台數'), summary);
});
test('來源與機種原色固定，不因排序或篩選改變', () => {
  assert.equal(reportOverviewColor('車行','#000'), '#7ac36a');
  assert.equal(reportOverviewColor('速克達','#000'), '#f15a60');
  assert.equal(reportOverviewColor('其他','#123456'), '#123456');
});

test('離線與逾時提示中文復原方式，保留權限及版本等具體錯誤', () => {
  assert.match(reportUpdateError(new TypeError('Failed to fetch')), /無法連線.*重試/);
  assert.match(reportUpdateError({name:'AbortError'}), /逾時.*重試/);
  assert.equal(reportUpdateError(new Error('報表版本已更新')), '報表版本已更新');
});

test('連續複選只送最後完整條件，取消待送查詢不留下舊操作', () => {
  const jobs = new Map(); let id = 0; const received = [];
  const timers = {setTimeout(fn) { jobs.set(++id, fn); return id; }, clearTimeout(key) { jobs.delete(key); }};
  const queue = reportDebounce(value => received.push(value), 300, timers);
  let selected = [];
  for (const group of ['A', 'B', 'C']) {
    selected = reportToggleSelection(selected, 0, group, '', true);
    queue.schedule(selected);
  }
  assert.equal(jobs.size, 1);
  [...jobs.values()][0]();
  assert.deepEqual(received[0][0].group, ['A', 'B', 'C']);
  queue.schedule('過時條件'); queue.cancel();
  assert.equal(jobs.size, 0);
});

test('候選圖提示明確標示占比基準，不冒充套用所有篩選', () => {
  assert.match(reportPointText({pointLabel:'車行',pointDisplay:'20',pointCount:'20',pointPercentage:25,pointScope:'候選分類範圍'},'訂單台數'), /占候選分類範圍：25.0%/);
});

test('銷售座標軸涵蓋最大值，空資料與非數值安全且台數刻度為整數', () => {
  for (const values of [[], [0], [1,7], [NaN, 25], [255], [1,9999]]) {
    const maximum=reportAxisMaximum(values);
    assert.ok(Number.isFinite(maximum) && maximum > 0);
    assert.equal(maximum % 4, 0);
    assert.ok(maximum >= Math.max(0,...values.filter(Number.isFinite)));
  }
});

test('圖表單選、重點取消、複選聯集與移除保留其他圖條件', () => {
  const other = {card:1, group:'B', grain:''};
  let chosen = reportToggleSelection([other], 0, 'A', '', false);
  assert.deepEqual(reportToggleSelection(chosen, 0, 'A', '', false), [other]);
  chosen = reportToggleSelection(chosen, 0, 'C', '', true);
  assert.deepEqual(chosen[1].group, ['A','C']);
  assert.equal(reportToggleSelection(chosen, 0, 'A', '', true)[1].group, 'C');
  assert.equal(reportToggleSelection(chosen, 0, 'D', 'year', true)[1].group, 'D');
  assert.throws(() => reportToggleSelection([{card:0,group:Array.from({length:200},(_,i)=>String(i)),grain:''}],0,'extra','',true), /200/);
});

test('彙總分頁不遺漏尾頁，切換筆數及非法頁碼有界限', () => {
  assert.deepEqual(reportPageRange(51, 25, 3), {page:3, pages:3, start:50, end:51});
  assert.deepEqual(reportPageRange(51, 100, 3), {page:1, pages:1, start:0, end:51});
  assert.deepEqual(reportPageRange(0, 0, -1), {page:1, pages:1, start:0, end:0});
});

test('圖表固定條件數量包含文字條件並排除空行及重複值', () => {
  assert.equal(reportScopeCount(2, ['EV076\r\nEV070\r\nEV076', ' \n']), 4);
  assert.equal(reportScopeCount(0, ['', 'EV060L']), 1);
});
test('提示保留分類、指標、台數與完整範圍占比', () => {
  const text = reportPointText({pointLabel:'2026/09 · 車行', pointDisplay:'60,000', pointCount:'3', pointPercentage:'25.55'}, '訂單車價合計');
  assert.match(text, /2026\/09 · 車行/); assert.match(text, /訂單車價合計：60,000/);
  assert.match(text, /訂單台數：3/); assert.match(text, /25.6%/);
});
test('平均與試算不冒充占比；標籤保持純文字', () => {
  const text = reportPointText({pointLabel:'<script>測試</script>',pointDisplay:'無法計算',pointCount:'0',pointPercentage:''},'試算');
  assert.doesNotMatch(text, /%/); assert.match(text, /<script>測試<\/script>/);
});
test('圓環 Top N 不重新正規化為百分之百', () => {
  assert.equal(reportFraction('20','100'),20);
  assert.equal(reportFraction('30','100'),30);
  assert.equal(reportFraction('20','100') + reportFraction('30','100'),50);
});
test('空值、負值及零總數不產生 NaN 幾何', () => {
  for (const [value,total] of [[0,0],['x',10],[10,'x'],[-1,10],[10,Infinity]]) assert.equal(reportFraction(value,total),0);
  assert.equal(reportFraction(200,100),100);
});
