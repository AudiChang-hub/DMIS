"""截圖標註工具：替要點的元件加橘色框線與編號，只截那一塊。橘色只出現在截圖裡，不進網站樣式。"""

ANNOTATE = r"""(items)=>{
  if (document.activeElement) document.activeElement.blur();
  document.querySelectorAll('.help-shot-mark').forEach(e=>e.remove());
  const boxes=[];
  for (const it of items) {
    const el=document.querySelector(it.sel); if(!el){ throw new Error('找不到要標註的元件：'+it.sel); }
    const r=el.getBoundingClientRect(); const pad=it.pad??6;
    const host=el.closest('dialog[open]'); const fixed=!!host;  // 對話框在最上層，框線要放進同一個對話框
    const b=document.createElement('div'); b.className='help-shot-mark';
    Object.assign(b.style,{position:fixed?'fixed':'absolute',left:(r.left+(fixed?0:scrollX)-pad)+'px',top:(r.top+(fixed?0:scrollY)-pad)+'px',
      width:(r.width+pad*2)+'px',height:(r.height+pad*2)+'px',border:'3px solid #e8590c',borderRadius:'10px',zIndex:2147483000,
      pointerEvents:'none',boxShadow:'0 0 0 4px rgba(232,89,12,.18)'});
    const n=document.createElement('span'); n.textContent=it.n;
    Object.assign(n.style,{position:'absolute',left:'-15px',top:'-15px',width:'28px',height:'28px',borderRadius:'50%',background:'#e8590c',
      color:'#fff',font:'800 15px/28px Inter, sans-serif',textAlign:'center',boxShadow:'0 2px 6px rgba(0,0,0,.25)'});
    b.appendChild(n); (host||document.body).appendChild(b);
    boxes.push({top:r.top+scrollY-pad,bottom:r.bottom+scrollY+pad});
  }
  return boxes;
}"""
CLEAR = "()=>document.querySelectorAll('.help-shot-mark').forEach(e=>e.remove())"
TEXT = r"(s)=>document.querySelector(s).innerText.replace(/\s+/g,' ')"


def mark(page, selector, tag, up=None):
    """替元件（或往上找到的容器）加 data-help-shot 標記並回傳選擇器；找不到就報錯。"""
    page.locator(selector).first.evaluate(
        "(e,[t,u])=>{const x=u?(e.closest(u)||e):e; x.setAttribute('data-help-shot',t)}", [tag, up])
    return f"[data-help-shot={tag}]"


def common_parent(page, first, last, tag):
    """標記同時包住兩個元件的最小容器。"""
    page.evaluate("([a,z,t])=>{let x=document.querySelector(a); const y=document.querySelector(z); while(!x.contains(y)) x=x.parentElement; x.setAttribute('data-help-shot',t)}",
                  [first, last, tag])
    return f"[data-help-shot={tag}]"


def leaf_text(page, text, tag, left_of=None):
    """標記文字完全等於 text 的最內層元素（可限制在畫面左側 left_of px 內）。"""
    page.evaluate("""([t,g,l])=>{const e=[...document.querySelectorAll('body *')].find(x=>x.children.length==0&&x.textContent.trim()==t&&(!l||x.getBoundingClientRect().left<l));
        if(!e) throw new Error('找不到文字：'+t); e.setAttribute('data-help-shot',g)}""", [text, tag, left_of])
    return f"[data-help-shot={tag}]"


def shot(page, path, items, margin=40, max_height=None):
    """把第一個標註捲到畫面上方，截出包含所有標註的那一段。"""
    first = page.query_selector(items[0]["sel"])
    page.evaluate("(el)=>{const r=el.getBoundingClientRect(); window.scrollTo({top:r.top+scrollY-170, behavior:'instant'})}", first)
    page.wait_for_timeout(250)
    boxes = page.evaluate(ANNOTATE, items)
    scroll = page.evaluate("scrollY")
    width, height = page.viewport_size["width"], page.viewport_size["height"]
    top = max(0, min(b["top"] for b in boxes) - scroll - margin - 60)
    bottom = min(height, max(b["bottom"] for b in boxes) - scroll + margin)
    if max_height:
        bottom = min(bottom, top + max_height)
    page.screenshot(path=str(path), type="jpeg", quality=82, clip={"x": 0, "y": top, "width": width, "height": max(200, bottom - top)})
    page.evaluate(CLEAR)


def region(page, path, selector, items, top_gap=96, pad=16):
    """把 selector 那一塊捲到頁首下方，只截這一塊。"""
    page.evaluate("([s,g])=>{const r=document.querySelector(s).getBoundingClientRect(); window.scrollTo({top:r.top+scrollY-g-16, behavior:'instant'})}",
                  [selector, top_gap])
    page.wait_for_timeout(300)
    page.evaluate(ANNOTATE, items)
    rect = page.evaluate("(s)=>{const r=document.querySelector(s).getBoundingClientRect(); return {t:r.top,b:r.bottom,l:r.left,r:r.right}}", selector)
    width, height = page.viewport_size["width"], page.viewport_size["height"]
    top, bottom = max(0, rect["t"] - pad - 20), min(height, rect["b"] + pad)
    left, right = max(0, rect["l"] - pad - 20), min(width, rect["r"] + pad)
    page.screenshot(path=str(path), type="jpeg", quality=82, clip={"x": left, "y": top, "width": right - left, "height": bottom - top})
    page.evaluate(CLEAR)


def viewport(page, path, items, height=None):
    """不捲動，直接截目前畫面（可只取上方 height px）。"""
    page.evaluate(ANNOTATE, items)
    clip = {"x": 0, "y": 0, "width": page.viewport_size["width"], "height": height or page.viewport_size["height"]}
    page.screenshot(path=str(path), type="jpeg", quality=82, clip=clip)
    page.evaluate(CLEAR)
