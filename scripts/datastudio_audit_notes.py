"""
DataStudio 報表屬性萃取 - 助手筆記

技術小抄（給下次 session 用）：

1. 頁面是 https://datastudio.google.com/reporting/{REPORT_ID}/page/{PAGE_ID}/edit
2. 所有圖表元件在 DOM 中都是 `.lego-component.simple-{TYPE}.cd-{ID}` 形式
   - TYPE: barchart/piechart/table/scorecard/timeseriechart/treemap/geomap/bullet etc
   - ID: 該元件在報表中的唯一 cd id
3. 點擊元件 → 右側彈出「「XXX 圖表」資源」屬性面板

### 重要陷阱：

- DataStudio 常將同一頁面的元件**群組**(Group)起來，點擊只會選到 group
- 解法：先點整個 group 讓 panel 出現「「群組」資源」，然後使用 `dispatchEvent` 直接在目標元件上觸發 pointerdown/mousedown/click 序列，即可選中單一元件
- 元件互相重疊時（例如 table 在 pie chart 後面），直接 `page.mouse.click(x,y)` 會被上層攔截
  - ❌ `page.mouse.click` / `element.click()` 都被 group 攔截
  - ✅ 直接用 `dispatchEvent(new PointerEvent('pointerdown'))` + mousedown + pointerup + mouseup + click 序列

### 擷取一張頁面所有圖表屬性的範本：

```js
// 1. 先取得所有元件清單
const comps = await page.evaluate(() => {
  return Array.from(document.querySelectorAll('.lego-component')).map(el => {
    const m = el.className.match(/cd-(\w+)/);
    const t = el.className.match(/simple-(\w+)/);
    return { id: m?.[1], type: t?.[1] };
  });
});

// 2. 每個元件用 dispatchEvent 方式選中
const results = [];
for (const c of comps) {
  await page.evaluate((id) => {
    const el = document.querySelector('.cd-' + id);
    const r = el.getBoundingClientRect();
    const cx = r.x + r.width/2, cy = r.y + r.height/2;
    const opts = { bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy, button: 0, buttons: 1 };
    el.dispatchEvent(new PointerEvent('pointerdown', { ...opts, pointerId: 1, pointerType: 'mouse' }));
    el.dispatchEvent(new MouseEvent('mousedown', opts));
    el.dispatchEvent(new PointerEvent('pointerup', { ...opts, pointerId: 1, pointerType: 'mouse', buttons: 0 }));
    el.dispatchEvent(new MouseEvent('mouseup', { ...opts, buttons: 0 }));
    el.dispatchEvent(new MouseEvent('click', { ...opts, buttons: 0 }));
  }, c.id);
  await page.waitForTimeout(700);
  const panel = await page.evaluate(() => {
    const h = Array.from(document.querySelectorAll('*')).find(e => {
      const t = e.innerText?.trim();
      return t && t.startsWith('「') && t.includes('」資源') && e.children.length < 5;
    });
    return h?.innerText.trim();
  });
  results.push({ ...c, panel });
}
```

### 翻頁方法：

- 從 `報表頁數` 窗格取得 22 頁名稱 (已記錄於 03-audit-findings.md)
- 直接 `await page.goto('https://datastudio.google.com/reporting/{REPORT_ID}/page/{PAGE_ID}/edit')`
  - 但 page_id 需先在該頁選中頁面後讀 URL 取得（無法一次批次取得）

### 篩選器識別：

屬性面板的 "這張圖表的篩選器" 下方會列出 chip，例如：
- `排除空白資料` → 套用名為「排除空白資料」的已定義篩選器
- 其他常見 chip：汽油車篩選器、電動車篩選器、網路平台篩選器、車行篩選器、基隆公益青年篩選、年齡及車型篩選、各年齡性別組合、FUN/RUN/70B/76B_性別/顏色 系列
"""
