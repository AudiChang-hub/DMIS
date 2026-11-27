/* T-311 車行／平台銷售（#6 #8 #11 #12，dealer_overview／platform_overview）：排行＋每月熱度格。
   每列一家車行（平台）：台數橫條與占比，右邊每格是當月台數（越深越多、格內寫數字），最下面一列是每月合計。
   資料全部讀自頁面上原本的堆疊圖（同一份查詢結果），只做重排與加總，數字口徑不變。
   使用者決定（2026-11-24）：點車行名稱可下鑽（沿用原本的連結與連動），不改 report_detail 的 group。
   T-322（2026-11-27）：有數字的格子是按鈕，點了從畫面右側滑出那一格的訂單（手機從底部），不換頁。
   網址就是堆疊圖那一段原本的下鑽連結（同一個 group），只多 inline=1&view=cell；沒有下鑽連結的格子（預覽、
   沒有查看權限、「其他平台」）照舊只顯示數字。方向鍵在格子間移動，整張表只佔一個 Tab 停點。 */
const REPORT_HEAT_LEVELS = 5;

function reportHeatLevel(value, maximum) {
  if (!(value > 0) || !(maximum > 0)) return 0;
  return Math.max(1, Math.min(REPORT_HEAT_LEVELS, Math.ceil(value / maximum * REPORT_HEAT_LEVELS)));
}
function reportHeatMonths(labels) {
  // 補齊成連續月份，沒有訂單的月份也留一格（空格）。
  const months = [...new Set(labels)].filter(label => /^\d{4}\/\d{2}$/.test(label)).sort();
  if (!months.length) return [];
  const all = [];
  let [year, month] = months[0].split('/').map(Number);
  const [endYear, endMonth] = months[months.length - 1].split('/').map(Number);
  while (year < endYear || (year === endYear && month <= endMonth)) {
    all.push(`${year}/${String(month).padStart(2, '0')}`);
    month += 1; if (month > 12) { month = 1; year += 1; }
  }
  return all;
}
/* 從原本的堆疊圖 DOM 整理成「列＝車行／平台、欄＝月份」。 */
function reportHeatData(chart) {
  const caption = group => group.querySelector('.report-stack-caption strong').textContent.trim();
  const groups = [...chart.querySelectorAll('.report-stack-row')];
  const rows = [...chart.querySelectorAll('.report-results tr[data-point-value]')];
  const isMonth = label => /^\d{4}\/\d{2}$/.test(label);
  const segments = group => [...group.querySelectorAll('[data-stack-segment]')].map(segment => ({
    label: segment.dataset.seriesLabel, value: Number(segment.dataset.pointValue) || 0,
    href: segment.querySelector('a[data-report-drill]')?.getAttribute('href') || ''}));
  // 一格只對應一段時才帶下鑽連結；兩段併成一格的話，單一連結的筆數會和格子對不上，就不給點。
  const keep = (links, month, href) => { links[month] = month in links ? '' : href; };
  const entities = []; const labels = []; let undated = 0; let other = null;
  if (chart.dataset.dimension !== 'month') {
    // 車行版：每列是車行、細分是月份。
    groups.forEach((group, index) => {
      const cells = {}, links = {}; let shown = 0;
      segments(group).forEach(segment => {
        if (isMonth(segment.label)) { cells[segment.label] = (cells[segment.label] || 0) + segment.value; keep(links, segment.label, segment.href); labels.push(segment.label); }
        else undated += segment.value;
        shown += segment.value;
      });
      const row = rows[index];
      entities.push({label: caption(group), total: Number(row?.dataset.pointValue) || shown, cells, links, row});
    });
  } else {
    // 平台版：每列是月份、細分是平台；原報表只列前 N 個平台，其餘算進「其他平台」。
    const byName = new Map(); const rest = {}; let restTotal = 0;
    groups.forEach((group, index) => {
      const month = caption(group), monthTotal = Number(rows[index]?.dataset.pointValue) || 0;
      let shown = 0;
      segments(group).forEach(segment => {
        shown += segment.value;
        if (!isMonth(month)) { undated += segment.value; }
        const entity = byName.get(segment.label) || {label: segment.label, total: 0, cells: {}, links: {}, row: null};
        entity.total += segment.value;
        if (isMonth(month)) { entity.cells[month] = (entity.cells[month] || 0) + segment.value; keep(entity.links, month, segment.href); }
        byName.set(segment.label, entity);
      });
      if (isMonth(month)) labels.push(month);
      const missing = Math.max(0, monthTotal - shown);
      if (missing) { restTotal += missing; if (isMonth(month)) rest[month] = (rest[month] || 0) + missing; else undated += missing; }
    });
    entities.push(...[...byName.values()].sort((a, b) => b.total - a.total));
    if (restTotal > 0) other = {label: '其他平台', total: restTotal, cells: rest, row: null, other: true};
  }
  return {entities, other, months: reportHeatMonths(labels), undated, total: Number(chart.dataset.total) || 0};
}

function renderReportHeat(chart, {currentMonth = ''} = {}) {
  const doc = chart.ownerDocument;
  if (chart.dataset.dimension !== 'month' && chart.dataset.series !== 'month') return false;
  const data = reportHeatData(chart);
  if (!data.entities.length) return false;
  const dealer = chart.dataset.dimension !== 'month';
  const unit = chart.dataset.metricLabel === '訂單台數' ? ' 張' : '';
  const all = data.other ? [...data.entities, data.other] : data.entities;
  const maxCell = Math.max(REPORT_HEAT_LEVELS, ...all.flatMap(entity => data.months.map(month => entity.cells[month] || 0)));
  const maxTotal = Math.max(...all.map(entity => entity.total), 1);
  const share = value => `${data.total > 0 ? (value / data.total * 100).toFixed(1) : '0.0'}%`;
  const make = (tag, className, text) => { const node = doc.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };

  const box = make('div', 'report-heat');
  box.style.setProperty('--report-heat-months', String(data.months.length));
  box.setAttribute('role', 'table');
  box.setAttribute('aria-label', `${chart.querySelector('h2').textContent}：每列一${dealer ? '家車行' : '個平台'}，每欄一個月的台數`);
  const head = make('div', 'report-heat__row report-heat__head'); head.setAttribute('role', 'row');
  const nameHead = make('span', 'report-heat__name', dealer ? '車行' : '平台'); nameHead.setAttribute('role', 'columnheader');
  const totalHead = make('span', 'report-heat__total', '台數 · 占比'); totalHead.setAttribute('role', 'columnheader');
  const monthHead = make('span', 'report-heat__months');
  let lastYear = '';
  data.months.forEach(month => {
    const [year, number] = month.split('/');
    const cell = make('span', 'report-heat__month'); cell.setAttribute('role', 'columnheader');
    const partial = month === currentMonth;
    const label = make('b', '', String(Number(number))); label.append(make('i', '', '月')); cell.append(label);
    if (partial) { cell.classList.add('is-partial'); cell.append(make('em', '', '進行中')); }
    cell.append(make('small', '', year !== lastYear ? year : ''));
    cell.setAttribute('aria-label', `${year}年${Number(number)}月${partial ? '（進行中）' : ''}`);
    lastYear = year; monthHead.append(cell);
  });
  head.append(nameHead, totalHead, monthHead); box.append(head);

  const line = (entity, rowIndex) => {
    const row = make('div', `report-heat__row${entity.other ? ' is-other' : ''}`); row.setAttribute('role', 'row');
    const link = entity.row?.querySelector('[data-report-drill]');
    const name = make(link ? 'a' : 'span', 'report-heat__name', entity.label);
    if (link) { for (const attr of link.attributes) name.setAttribute(attr.name, attr.value); name.textContent = entity.label; }
    name.title = entity.label; name.setAttribute('role', 'rowheader');
    const total = make('span', 'report-heat__total'); total.setAttribute('role', 'cell');
    const bar = make('span', 'report-heat__bar'); bar.setAttribute('aria-hidden', 'true');
    const fill = make('b'); fill.style.width = `${(entity.total / maxTotal * 100).toFixed(2)}%`; bar.append(fill);
    const number = make('strong', '', entity.total.toLocaleString('zh-TW')); number.append(make('small', '', share(entity.total)));
    total.append(bar, number);
    const months = make('span', 'report-heat__months');
    data.months.forEach((month, column) => {
      const value = entity.cells[month] || 0;
      const text = value ? value.toLocaleString('zh-TW') : '';
      const href = value > 0 ? (entity.links?.[month] || '') : '';
      const title = `${entity.label} · ${month}：${value.toLocaleString('zh-TW')}${unit}`;
      const cell = make('span', `report-heat__cell h${reportHeatLevel(value, maxCell)}`, href ? undefined : text);
      cell.setAttribute('role', 'cell');
      if (href) {
        const button = make('button', 'report-heat__open', text);
        button.type = 'button'; button.tabIndex = -1;
        Object.assign(button.dataset, {heatCell: href, heatLabel: entity.label, heatMonth: month, heatValue: String(value), heatUnit: unit,
          heatRow: String(rowIndex), heatCol: String(column), heatChart: chart.querySelector('h2').textContent.trim()});
        button.title = `${title}，點一下看明細`;
        button.setAttribute('aria-label', reportHeatCellLabel(entity.label, month, text, unit));
        button.setAttribute('aria-haspopup', 'dialog'); button.setAttribute('aria-expanded', 'false');
        cell.classList.add('has-orders'); cell.append(button);
      } else { cell.title = title; cell.setAttribute('aria-label', title); }
      if (month === currentMonth) cell.classList.add('is-partial');
      months.append(cell);
    });
    row.append(name, total, months); return row;
  };
  all.forEach((entity, index) => box.append(line(entity, index)));
  // 整張表只佔一個 Tab 停點（第一個有數字的格子），其餘用方向鍵、Home／End 移動。
  const openers = () => [...box.querySelectorAll('[data-heat-cell]')];
  if (openers().length) {
    openers()[0].tabIndex = 0;
    box.addEventListener('keydown', event => {
      const current = event.target.closest?.('[data-heat-cell]');
      if (!current || event.altKey || event.ctrlKey || event.metaKey) return;
      const buttons = openers();
      const next = reportHeatNeighbor(buttons.map(button => ({row: Number(button.dataset.heatRow), col: Number(button.dataset.heatCol)})), buttons.indexOf(current), event.key);
      if (next < 0) return;
      event.preventDefault(); buttons[next].focus();
    });
    box.addEventListener('focusin', event => {
      const current = event.target.closest?.('[data-heat-cell]');
      if (!current) return;
      openers().forEach(button => { button.tabIndex = button === current ? 0 : -1; });
    });
  }

  const foot = make('div', 'report-heat__row report-heat__foot'); foot.setAttribute('role', 'row');
  const footName = make('span', 'report-heat__name', '每月合計'); footName.setAttribute('role', 'rowheader');
  const footTotal = make('span', 'report-heat__total'); footTotal.setAttribute('role', 'cell');
  footTotal.append(make('strong', '', data.total.toLocaleString('zh-TW')));
  const footMonths = make('span', 'report-heat__months');
  data.months.forEach(month => {
    const value = all.reduce((sum, entity) => sum + (entity.cells[month] || 0), 0);
    const cell = make('span', 'report-heat__sum', value.toLocaleString('zh-TW')); cell.setAttribute('role', 'cell'); footMonths.append(cell);
  });
  foot.append(footName, footTotal, footMonths); box.append(foot);

  const scale = make('p', 'report-heat__scale');
  scale.append('格子越深＝當月台數越多');
  for (let level = 0; level <= REPORT_HEAT_LEVELS; level += 1) {
    const swatch = make('i', `h${level}`); swatch.setAttribute('aria-hidden', 'true'); scale.append(swatch);
    if (level === 0) scale.append('0');
  }
  scale.append(`${maxCell.toLocaleString('zh-TW')} 以上`);

  const notes = [];
  const current = data.months.includes(currentMonth) ? Number(currentMonth.split('/')[1]) : 0;
  if (data.months.length) notes.push(`${data.months[0]}–${data.months[data.months.length - 1]}`);
  if (current) notes.push(`${current}月統計到今天，尚未滿月（框線格）`);
  if (data.other) notes.push(`「其他平台」是原報表只列前 ${data.entities.length} 名以外的平台，共 ${data.other.total.toLocaleString('zh-TW')}${unit}，合計本來就有算進去`);
  if (data.undated > 0) notes.push(`另有 ${data.undated.toLocaleString('zh-TW')}${unit}日期未填寫，不在每月格子裡，仍算在台數`);

  const wrap = make('div', 'report-heat-wrap');
  const scroll = make('div', 'report-heat-scroll'); scroll.append(box);
  wrap.append(scroll, scale);
  if (notes.length) wrap.append(make('p', 'report-heat__note', `${notes.join('；')}。`));
  const stacks = chart.querySelector('.report-stacks');
  stacks.before(wrap); stacks.hidden = true;
  // 原本「只顯示前 N 個系列、背景空白為未顯示部分」的說明是給堆疊圖的；熱度格已把未列出的併成「其他平台」並另寫註記。
  chart.querySelectorAll(':scope > .report-notice').forEach(note => { if (note.textContent.includes('依系列排序顯示前')) note.hidden = true; });
  chart.querySelector('.report-series-legend')?.setAttribute('hidden', '');
  const table = chart.querySelector('.report-table-wrap'); if (table) table.hidden = true;
  chart.classList.add('report-chart--heat');
  return true;
}

/* ── T-322 點格子看訂單 ───────────────────────────────────────────── */
function reportHeatMonthText(month) {
  const [year, number] = String(month).split('/');
  return `${year} 年 ${Number(number)} 月`;
}
/* 例：「示範車行甲 2026 年 11 月 3 張，看明細」。 */
function reportHeatCellLabel(label, month, value, unit = '') {
  return `${label} ${reportHeatMonthText(month)} ${value}${unit}，看明細`;
}
/* 格子的下鑽網址＝原本那一段的連結再加 inline=1&view=cell；其他條件（篩選、revision、group）原樣帶著。 */
function reportHeatCellUrl(href, base) {
  const url = new URL(href, base);
  url.searchParams.set('inline', '1'); url.searchParams.set('view', 'cell');
  return url.href;
}
/* 方向鍵要去的格子：左右留在同一列，上下到最近一列裡最靠近的欄；沒有就回 -1。 */
function reportHeatNeighbor(cells, index, key) {
  const from = cells[index];
  if (!from) return -1;
  const nearest = (accept, distance) => {
    let best = -1, bestDistance = Infinity;
    cells.forEach((cell, position) => {
      if (position === index || !accept(cell)) return;
      const far = distance(cell);
      if (far < bestDistance) { best = position; bestDistance = far; }
    });
    return best;
  };
  const sameRow = cell => cell.row === from.row;
  const across = cell => Math.abs(cell.row - from.row) * 10000 + Math.abs(cell.col - from.col);
  if (key === 'ArrowRight') return nearest(cell => sameRow(cell) && cell.col > from.col, cell => cell.col - from.col);
  if (key === 'ArrowLeft') return nearest(cell => sameRow(cell) && cell.col < from.col, cell => from.col - cell.col);
  if (key === 'ArrowDown') return nearest(cell => cell.row > from.row, across);
  if (key === 'ArrowUp') return nearest(cell => cell.row < from.row, across);
  if (key === 'Home') return nearest(cell => sameRow(cell) && cell.col < from.col, cell => cell.col);
  if (key === 'End') return nearest(cell => sameRow(cell) && cell.col > from.col, cell => -cell.col);
  return -1;
}
/* 載入不成功時要顯示的畫面：沒有權限、報表已更新、登入逾時、等太久、其他錯誤，各有說法與能做的事。 */
function reportHeatFailure(response, error) {
  if (error?.name === 'AbortError') return {kind: 'timeout', text: '等太久沒有回應，可能是網路不穩。', retry: true};
  if (!response) return {kind: 'error', text: '訂單載入失敗，可能是網路斷線。', retry: true};
  if (response.redirected || response.status === 401) return {kind: 'login', text: '登入已經逾時。重新整理頁面、登入後，再點一次格子。', reload: true};
  if (response.status === 403 || response.status === 404) return {kind: 'denied', text: '這個帳號目前不能查看這份報表的訂單，可能是權限調整過了。需要的話請找 admin 開通。'};
  if (response.status === 409) return {kind: 'stale', text: '報表剛剛更新過。重新整理頁面後，再點一次格子。', reload: true};
  return {kind: 'error', text: '訂單載入失敗。', retry: true};
}

/* 面板從右側蓋住熱度格時，格子區要往左讓多少（px）：最近幾個月都在右邊，不讓的話剛點的格子和旁邊的月份會被蓋住。
   沒蓋到就不動；讓完剩下的寬度不到 minimum（平板等窄畫面）也不動，面板直接蓋在上面。 */
function reportHeatRoom(left, right, drawerLeft, {gap = 16, minimum = 480} = {}) {
  const edge = drawerLeft - gap;
  if (right <= edge || edge - left < minimum) return 0;
  return Math.ceil(right - edge);
}

function createReportHeatDrawer(doc, win) {
  const make = (tag, className, text) => { const node = doc.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };
  const scrim = make('div', 'report-cell-drawer-scrim'); scrim.hidden = true;
  const drawer = make('aside', 'report-cell-drawer');
  drawer.setAttribute('role', 'dialog'); drawer.setAttribute('aria-modal', 'false'); drawer.setAttribute('aria-labelledby', 'report-cell-drawer-title');
  drawer.setAttribute('inert', '');
  const head = make('header', 'report-cell-drawer__head');
  const heading = make('div', 'report-cell-drawer__heading');
  const source = make('p', 'report-cell-drawer__source');
  const title = make('h2', 'report-cell-drawer__title'); title.id = 'report-cell-drawer-title'; title.tabIndex = -1;
  const meta = make('p', 'report-cell-drawer__meta');
  const period = make('span', 'report-cell-drawer__period');
  const count = make('strong', 'report-cell-drawer__count');
  meta.append(period, count);
  heading.append(source, title, meta);
  const closeButton = make('button', 'report-cell-drawer__close'); closeButton.type = 'button'; closeButton.setAttribute('aria-label', '關閉訂單明細');
  const cross = make('span', '', '×'); cross.setAttribute('aria-hidden', 'true'); closeButton.append(cross);
  head.append(heading, closeButton);
  const body = make('div', 'report-cell-drawer__body');
  const status = make('p', 'visually-hidden'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  drawer.append(head, status, body);
  doc.body.append(scrim, drawer);

  let trigger = null, controller = null, ticket = 0, opened = false, squeezed = null;
  // 桌機：面板開著時，把被蓋住的格子區往左讓（只縮每月格子的欄寬，列高不變，上下內容不位移），關閉後還原。
  const release = () => { if (squeezed) { squeezed.style.marginRight = ''; squeezed = null; } };
  function makeRoom(button) {
    const scroll = button.closest?.('.report-heat-scroll');
    if (squeezed !== scroll) release();
    if (!scroll?.getBoundingClientRect || !win.matchMedia || win.matchMedia('(max-width: 760px)').matches) return;
    const given = parseFloat(scroll.style.marginRight) || 0;
    const rect = scroll.getBoundingClientRect();
    const margin = reportHeatRoom(rect.left, rect.right + given, doc.documentElement.clientWidth - drawer.offsetWidth);
    scroll.style.marginRight = margin ? `${margin}px` : '';
    squeezed = margin ? scroll : null;
    if (!margin) return;
    // 欄寬已到下限、格子區自己出現橫向捲動時，把剛點的格子捲回看得到的地方。
    const cell = button.getBoundingClientRect(), box = scroll.getBoundingClientRect();
    if (cell.right > box.right) scroll.scrollLeft += cell.right - box.right + 4;
    else if (cell.left < box.left) scroll.scrollLeft -= box.left - cell.left + 4;
  }
  win.addEventListener?.('resize', () => { if (opened && trigger?.isConnected) makeRoom(trigger); });
  const amount = (value, unit) => `${Number(value).toLocaleString('zh-TW')}${unit || ' 張'}`;
  const mark = (button, on) => { if (button?.isConnected) button.setAttribute('aria-expanded', String(on)); };

  function showLoading(rows) {
    drawer.dataset.state = 'loading'; drawer.setAttribute('aria-busy', 'true');
    status.textContent = '正在載入訂單…';
    const list = make('ul', 'report-cell-drawer__skeleton'); list.setAttribute('aria-hidden', 'true');
    for (let index = 0; index < Math.max(1, Math.min(rows, 6)); index += 1) { const item = make('li'); item.append(make('span'), make('span')); list.append(item); }
    body.replaceChildren(list);
  }
  function showFailure(failure, button) {
    drawer.dataset.state = failure.kind; drawer.removeAttribute('aria-busy');
    status.textContent = '';
    const box = make('div', 'report-cell-drawer__notice'); box.setAttribute('role', 'alert');
    box.append(make('p', '', failure.text));
    const actions = [];
    if (failure.retry) {
      const retry = make('button', 'button ghost', '再試一次'); retry.type = 'button';
      retry.addEventListener('click', () => { load(button); title.focus({preventScroll: true}); });
      const full = make('a', '', '改開完整明細 →'); full.href = button.dataset.heatCell;
      actions.push(retry, full);
    }
    if (failure.reload) {
      const reload = make('button', 'button ghost', '重新整理頁面'); reload.type = 'button';
      reload.addEventListener('click', () => win.location.reload());
      actions.push(reload);
    }
    if (actions.length) { const row = make('p', 'report-cell-drawer__actions'); row.append(...actions); box.append(row); }
    body.replaceChildren(box);
  }
  async function load(button) {
    controller?.abort(); controller = new win.AbortController();
    const own = controller, mine = ++ticket;
    const shown = Number(button.dataset.heatValue) || 0, unit = button.dataset.heatUnit;
    count.textContent = `共 ${amount(shown, unit)}`; showLoading(shown);
    const timer = win.setTimeout(() => own.abort(), 15000);
    let response = null;
    try {
      const url = reportHeatCellUrl(button.dataset.heatCell, win.reportPreviewLocation || win.location.href);
      response = await (win.reportPreviewFetch || win.fetch)(url, {signal: own.signal, credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}});
      if (!response.ok || response.redirected) throw new Error(String(response.status));
      const content = new win.DOMParser().parseFromString(await response.text(), 'text/html').querySelector('[data-cell-orders]');
      if (!content) throw new Error('empty');
      if (mine !== ticket) return;
      const total = Number(content.dataset.cellCount) || 0;
      count.textContent = `共 ${amount(total, unit)}`;
      const nodes = [doc.importNode(content, true)];
      // 格子是打開報表時算的；之後訂單有異動，筆數以這裡剛查到的為準，並說明原因。
      if (total !== shown) nodes.unshift(make('p', 'report-cell-drawer__drift', `格子上寫 ${amount(shown, unit)}，是打開報表時的數字；訂單之後有異動，現在是 ${amount(total, unit)}。重新整理報表可以同步。`));
      body.replaceChildren(...nodes);
      drawer.dataset.state = 'ready'; drawer.removeAttribute('aria-busy');
      status.textContent = `已載入 ${amount(total, unit)}訂單`;
    } catch (error) {
      // 被新的點選或關閉取代時 ticket 已經不同，不畫任何東西；走到這裡的 AbortError 只會是逾時。
      if (mine !== ticket) return;
      showFailure(reportHeatFailure(response, error), button);
    } finally { win.clearTimeout(timer); }
  }
  function open(button) {
    if (trigger !== button) mark(trigger, false);
    trigger = button; mark(button, true);
    source.textContent = button.dataset.heatChart || '';
    title.textContent = button.dataset.heatLabel;
    period.textContent = reportHeatMonthText(button.dataset.heatMonth);
    drawer.removeAttribute('inert'); drawer.classList.add('is-open'); scrim.hidden = false;
    opened = true;
    makeRoom(button);
    load(button);
    title.focus({preventScroll: true});
  }
  function close({restoreFocus = true} = {}) {
    if (!opened) return;
    opened = false; ticket += 1; controller?.abort();
    drawer.classList.remove('is-open'); drawer.setAttribute('inert', ''); drawer.removeAttribute('aria-busy'); scrim.hidden = true;
    mark(trigger, false); release();
    if (restoreFocus && trigger?.isConnected) trigger.focus({preventScroll: true});
    trigger = null;
  }
  closeButton.addEventListener('click', () => close());
  return {open, close, isOpen: () => opened, element: drawer, scrim, body, title, count, closeButton};
}

/* 點擊時使用者點到的可聚焦控制項：沿事件路徑找最近一個按鈕、連結、表單欄位或 tabindex≥0 的元素。 */
const REPORT_HEAT_NATIVE_CONTROLS = ['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'SUMMARY', 'IFRAME'];
function reportHeatTabindex(node) {
  const value = node?.getAttribute?.('tabindex');
  return value === null || value === undefined || value === '' || Number.isNaN(Number(value)) ? null : Number(value);
}
// 本身就是控制項（不看 tabindex）：按鈕、表單欄位、有 href 的連結、可編輯區。
function reportHeatNativeControl(node) {
  const tag = node?.tagName;
  if (!tag || node.disabled) return false;
  if (REPORT_HEAT_NATIVE_CONTROLS.includes(tag)) return !(tag === 'INPUT' && String(node.getAttribute?.('type') || '').toLowerCase() === 'hidden');
  if ((tag === 'A' || tag === 'AREA') && node.hasAttribute?.('href')) return true;
  return Boolean(node.isContentEditable);
}
function reportHeatFocusable(node) {
  if (reportHeatNativeControl(node)) return true;
  const tabindex = reportHeatTabindex(node);
  return Boolean(node?.tagName) && !node.disabled && tabindex !== null && tabindex >= 0;
}
function reportHeatClickedControl(event) {
  const path = event.composedPath ? event.composedPath() : [];
  return path.find(reportHeatFocusable) || null;
}
/* 只能被程式聚焦的容器（例如 tabindex="-1" 的 main）：點空白處時瀏覽器會把焦點放在這裡，這不算使用者選了控制項。 */
function reportHeatPassiveFocus(node) {
  const tabindex = reportHeatTabindex(node);
  return tabindex !== null && tabindex < 0 && !reportHeatNativeControl(node);
}

/* 整頁只掛一次：點格子開（或換內容），點面板外、按 Esc 關。格子在連動更新時會整批換新，所以用事件委派。 */
function initReportHeatDrawer(doc, win) {
  if (doc.reportHeatDrawerReady) return null;
  doc.reportHeatDrawerReady = true;
  let drawer = null;
  const cellAt = event => {
    const direct = event.target.closest?.('[data-heat-cell]');
    if (direct || !drawer || event.target !== drawer.scrim) return direct || null;
    // 手機的遮罩蓋在報表上：點到的位置底下如果是另一個格子，就直接換內容。
    drawer.scrim.hidden = true;
    const under = doc.elementFromPoint?.(event.clientX, event.clientY)?.closest?.('[data-heat-cell]') || null;
    drawer.scrim.hidden = false;
    return under;
  };
  // 面板裡的按鈕（例如「再試一次」）按下後會被換掉，所以用事件路徑判斷是不是點在面板內。
  const inside = event => (event.composedPath ? event.composedPath().includes(drawer.element) : drawer.element.contains(event.target));
  doc.addEventListener('click', event => {
    const cell = cellAt(event);
    if (cell) {
      event.preventDefault();
      drawer = drawer || createReportHeatDrawer(doc, win);
      drawer.open(cell);
      return;
    }
    if (!drawer?.isOpen() || inside(event)) return;
    // 點面板外：關閉。使用者點的若是別的控制項，焦點留在（或移到）那個控制項；
    // 其他情況不論焦點落在哪裡（body、tabindex="-1" 的 main 等容器），都把焦點還給原本的格子。
    const control = reportHeatClickedControl(event);
    const active = doc.activeElement;
    const movedToControl = Boolean(active) && active !== doc.body && !drawer.element.contains(active) && !reportHeatPassiveFocus(active);
    drawer.close({restoreFocus: !control && !movedToControl});
    if (control && !movedToControl) control.focus?.({preventScroll: true}); // 有些瀏覽器點按鈕不會給焦點
  });
  doc.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !drawer?.isOpen()) return;
    event.stopPropagation(); // 只關這個面板，不連帶關掉底下的「看訂單」明細或放大的圖
    drawer.close();
  }, true);
  // 上一頁／下一頁會把圖表換成別的篩選結果，原本那一格已經不在，面板跟著收起來。
  win.addEventListener?.('popstate', () => drawer?.close({restoreFocus: false}));
  return {current: () => drawer};
}
if (typeof document !== 'undefined' && typeof window !== 'undefined') initReportHeatDrawer(document, window);
if (typeof module !== 'undefined' && module.exports) module.exports = {reportHeatLevel, reportHeatMonths, renderReportHeat, reportHeatMonthText, reportHeatCellLabel,
  reportHeatCellUrl, reportHeatNeighbor, reportHeatFailure, reportHeatRoom, createReportHeatDrawer, initReportHeatDrawer};
