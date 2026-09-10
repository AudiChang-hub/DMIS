/* 長條提示使用安全 DOM 與實際圖例顏色；不解析資料為 HTML。 */
function reportBarTooltip(data, segments, metric, scopeTotal, scopeLabel) {
  const total = Number(data.pointValue);
  const stacked = Array.isArray(segments);
  const entries = (stacked ? segments : [{label:data.pointLabel, value:data.pointValue,
    display:data.pointDisplay, color:data.pointColor}]).filter(item => item.value !== '' && Number.isFinite(Number(item.value)) && (!stacked || Number(item.value) !== 0)).map(item => ({...item, value:Number(item.value)}));
  const sum = entries.reduce((value, item) => value + item.value, 0);
  if (stacked && Number.isFinite(total) && total - sum > 0.000001) entries.push({label:'未顯示系列', value:total-sum, display:(total-sum).toLocaleString('zh-TW', {maximumFractionDigits:2}), color:'var(--line)'});
  const denominator = stacked ? total : Number(scopeTotal);
  const additive = !['平均車價', '分析試算'].includes(metric) && (metric === '訂單台數' || metric === '訂單車價合計');
  const percentage = additive && denominator > 0 && entries.every(item => item.value >= 0);
  return {title:data.pointLabel, metric, total:data.pointDisplay, totalLabel:additive ? '總計' : metric,
    percentageLabel:stacked ? '占此長條' : `占${scopeLabel}`,
    note:scopeLabel === '候選分類範圍' ? '此圖保留候選分類；其他圖與明細依完整選取。' : '',
    entries:entries.map(item => ({...item, percentage:percentage ? `${(item.value/denominator*100).toFixed(1)}%` : '—'}))};
}
function reportBarTooltipText(model, active) {
  return [model.title, active ? `目前指向：${active}` : '',
    ...model.entries.map(item => `${item.label}：${item.display}${item.percentage === '—' ? '' : `（${model.percentageLabel} ${item.percentage}）`}`),
    `${model.totalLabel}：${model.total}`, model.note].filter(Boolean).join('\n');
}
function renderReportBarTooltip(tip, model, active) {
  tip.replaceChildren(); tip.classList.add('report-tooltip-rich');
  const make = (tag, className, text) => { const el = tip.ownerDocument.createElement(tag); el.className = className; if(text !== undefined) el.textContent = text; return el; };
  tip.append(make('strong', 'report-tooltip-title', model.title));
  const heading = make('div', 'report-tooltip-row report-tooltip-heading');
  heading.append(make('span','','分類'), make('span','',model.metric), make('span','',model.percentageLabel)); tip.append(heading);
  const list = make('div', 'report-tooltip-items');
  for (const item of model.entries) {
    const row = make('div', 'report-tooltip-row' + (item.label === active ? ' is-active' : ''));
    const label = make('span', 'report-tooltip-label');
    const swatch = make('i', 'report-tooltip-swatch'); swatch.style.backgroundColor = item.color; swatch.setAttribute('aria-hidden','true');
    label.append(swatch, make('span','',item.label));
    row.append(label, make('span','report-tooltip-value',item.display), make('span','report-tooltip-value',item.percentage)); list.append(row);
  }
  tip.append(list);
  const total = make('div','report-tooltip-total'); total.append(make('strong','',model.totalLabel),make('strong','',model.total)); tip.append(total);
  if(model.note) tip.append(make('p','report-tooltip-note',model.note));
}
if(typeof module !== 'undefined' && module.exports) module.exports = {reportBarTooltip,reportBarTooltipText,renderReportBarTooltip};
