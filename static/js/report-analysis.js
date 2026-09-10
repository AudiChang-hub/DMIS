/* 人口分析的直條圖；只使用已授權模板資料與既有交叉篩選連結。 */
function reportAnalysisColor(label, fallback) {
  return {'男性':'#737373','女性':'#f15a60','公司或其他':'#7ac36a','生日未填':'#5a9bd4',
    '灰':'#5a9bd4','白':'#faa75a','藍':'#7ac36a','帕瑪森白':'#7dd3ef','黑':'#f15a60',
    '魔綠幻紫':'#737373','黃':'#9e67ab','海神藍':'#ce7058'}[label] || fallback;
}
function renderReportAnalysis(chart, attach) {
  const rows = [...chart.querySelectorAll('.report-results tr[data-point-value]')];
  if (!rows.length) return;
  const stacked = chart.dataset.chart === 'stacked';
  const groups = [...chart.querySelectorAll('.report-stack-row')];
  const ns = 'http://www.w3.org/2000/svg';
  const width = Math.max(740, rows.length * 90 + 80), height = 500, left = 55, top = 26, bottom = 390;
  const maximum = reportAxisMaximum(rows.map(row => Number(row.dataset.pointValue)));
  const step = (width-left-20)/rows.length, barWidth = Math.min(72, step*.65);
  const svg = document.createElementNS(ns,'svg');
  svg.classList.add('report-analysis-plot'); svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
  // 分類增加時只在卡片內捲動，不把 20px 文字縮成不可讀的小字。
  svg.style.minWidth = `${Math.max(640, Math.ceil(width * .8))}px`;
  svg.setAttribute('aria-label',chart.querySelector('h2').textContent+' 垂直長條圖');
  const make = (tag, attrs, text) => { const el=document.createElementNS(ns,tag); Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v)); if(text!==undefined) el.textContent=text; svg.append(el); return el; };
  for(let i=0;i<=4;i++) {
    const y=bottom-(bottom-top)*i/4;
    make('line',{x1:left,x2:width-20,y1:y,y2:y,stroke:'var(--line)'});
    make('text',{x:left-8,y:y+6,'text-anchor':'end',fill:'currentColor','font-size':20},String(maximum*i/4));
  }
  rows.forEach((row,index)=>{
    const x=left+step*(index+.5)-barWidth/2;
    const segments=stacked ? [...groups[index].querySelectorAll('[data-stack-segment]')] : [row];
    let offset=0;
    segments.forEach(segment=>{
      const value=Number(segment.dataset.pointValue), h=value/maximum*(bottom-top);
      if(!h) return;
      const label=stacked ? segment.dataset.seriesLabel : row.dataset.pointLabel;
      const rect=make('rect',{x,y:bottom-offset-h,width:barWidth,height:h,fill:reportAnalysisColor(label,segment.dataset.pointColor||segment.style.backgroundColor||'#737373')});
      attach(rect,segment);
      offset+=h;
    });
    const totalHeight = Math.max(0,Number(row.dataset.pointValue))/maximum*(bottom-top);
    make('text',{x:x+barWidth/2,y:bottom-totalHeight-8,'text-anchor':'middle',fill:'currentColor','font-size':20,'class':'report-bar-total-label'},row.dataset.pointDisplay);
    const label=make('text',{x:x+barWidth/2,y:bottom+28,'text-anchor':'middle',fill:'currentColor','font-size':20},row.dataset.pointLabel);
    attach(label,row);
    if(row.dataset.pointLabel.length>6) label.setAttribute('transform',`rotate(-25 ${x+barWidth/2} ${bottom+28})`);
  });
  const table=chart.querySelector('.report-table-wrap'); table.before(svg); table.hidden=true;
  const stacks=chart.querySelector('.report-stacks'); if(stacks) stacks.hidden=true;
}
if(typeof module!=='undefined' && module.exports) module.exports={reportAnalysisColor};
