// T-267：手機文字健檢（在頁面裡執行）。找出三類問題，回傳 JSON：
//   overflow：整頁水平捲動或元素超出視窗；
//   truncated：文字被 ellipsis／overflow 藏起來（內容寬度大於可見寬度）；
//   narrow：文字欄太窄，平均每行不到 3 個字（「一個字一行」）；
//   split：10 個字以內的短標籤被拆成兩行以上。
// 只看看得見的元素；捲動容器（overflow-x: auto）裡本來就能左右捲的內容不算截斷。
(() => {
  const vw = document.documentElement.clientWidth;
  const out = { url: location.pathname + location.search, vw, scrollW: document.documentElement.scrollWidth, overflow: [], truncated: [], narrow: [], split: [] };
  const visible = (el) => {
    if (!el.getClientRects().length) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none" || +cs.opacity === 0) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) return false;
    // 讀屏專用（視覺隱藏）不算
    if (r.width <= 2 && r.height <= 2) return false;
    if (cs.clip === "rect(0px, 0px, 0px, 0px)" || cs.clipPath === "inset(50%)") return false;
    return true;
  };
  const hiddenByAncestor = (el) => {
    for (let n = el; n && n !== document.body; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === "none" || cs.visibility === "hidden") return true;
      if (n.matches("dialog:not([open]), [hidden], details:not([open]) > :not(summary)")) return true;
      const r = n.getBoundingClientRect();
      if (r.width <= 2 && r.height <= 2 && cs.overflow !== "visible") return true; // visually-hidden
    }
    return false;
  };
  const name = (el) => {
    const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 2).join(".") : "";
    const parent = el.parentElement;
    const pcls = parent && typeof parent.className === "string" ? parent.className.trim().split(/\s+/).filter(Boolean).slice(0, 1).join(".") : "";
    return `${pcls ? "." + pcls + " > " : ""}${el.tagName.toLowerCase()}${cls ? "." + cls : ""}${el.dataset?.label ? `[data-label=${el.dataset.label}]` : ""}`.slice(0, 110);
  };
  const text = (el) => (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  const inScroller = (el) => {
    for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (/(auto|scroll)/.test(cs.overflowX) && n.scrollWidth > n.clientWidth + 1) return n;
    }
    return null;
  };
  // 手機版在欄位下方補上完整文字（phone-full-text.js）的，不算被藏起來。
  const hasFullText = (el) => { const anchor = el.closest(".searchable-select") || el; return anchor.nextElementSibling?.classList.contains("phone-full-text"); };
  const all = [...document.querySelectorAll("body *")].filter((el) => !["SCRIPT", "STYLE", "SVG", "PATH", "svg", "path", "TEMPLATE", "OPTION", "BR"].includes(el.tagName));

  // 1. 水平溢出
  for (const el of all) {
    if (!visible(el) || hiddenByAncestor(el)) continue;
    const cs = getComputedStyle(el);
    if (cs.position === "fixed" && el.closest("dialog:not([open])")) continue;
    const r = el.getBoundingClientRect();
    if ((r.right > vw + 1 || r.left < -1) && !inScroller(el) && !el.closest("[aria-hidden=true]")) {
      out.overflow.push(`${name(el)} L=${Math.round(r.left)} R=${Math.round(r.right)}`);
    }
  }
  out.overflow = out.overflow.slice(0, 10);

  // 2. 被藏起來的文字：自己有字、而且內容比可見寬度寬（ellipsis、overflow hidden、clip、line-clamp）
  for (const el of all) {
    if (!visible(el) || hiddenByAncestor(el)) continue;
    const t = text(el);
    if (!t) continue;
    const cs = getComputedStyle(el);
    const clipsX = cs.overflowX !== "visible" && !/(auto|scroll)/.test(cs.overflowX);
    const clipsY = cs.overflowY !== "visible" && !/(auto|scroll)/.test(cs.overflowY);
    const ownText = [...el.childNodes].some((n) => n.nodeType === 3 && n.nodeValue.trim());
    if (!ownText && cs.textOverflow !== "ellipsis" && el.tagName !== "SELECT") continue;
    if (el.tagName === "TEXTAREA") continue;
    let hidden = false;
    if (clipsX && el.scrollWidth > el.clientWidth + 1) hidden = "x";
    if (clipsY && el.scrollHeight > el.clientHeight + 2 && (cs.webkitLineClamp !== "none" && cs.webkitLineClamp)) hidden = "clamp";
    else if (clipsY && el.scrollHeight > el.clientHeight + 4 && ownText) hidden = "y";
    if (el.tagName === "SELECT" && hasFullText(el)) continue;
    if (el.tagName === "SELECT") {
      // 下拉：選中的文字寬度大於框寬
      const opt = el.selectedOptions?.[0];
      if (opt) {
        const c = document.createElement("canvas").getContext("2d");
        c.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
        const w = c.measureText(opt.textContent.trim()).width;
        const inner = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        if (w > inner + 1) hidden = "select";
        else hidden = false;
      }
    }
    if (hidden) out.truncated.push(`${name(el)} (${hidden}${cs.textOverflow === "ellipsis" ? ",ellipsis" : ""}) 「${(el.tagName === "SELECT" ? el.selectedOptions?.[0]?.textContent || "" : t).trim().slice(0, 30)}」`);
  }
  // 2a. 欄位的提示文字（placeholder）或已填的值比欄位寬：被切掉
  const ctx = document.createElement("canvas").getContext("2d");
  for (const el of document.querySelectorAll("input:not([type=checkbox], [type=radio], [type=file], [type=range], [type=color], [type=hidden], [type=date], [type=month], [type=datetime-local], [type=time])")) {
    if (!visible(el) || hiddenByAncestor(el)) continue;
    const shown = el.value || el.placeholder;
    if (!shown || (el.value && hasFullText(el))) continue;
    if (!el.value && el.classList.contains("has-phone-hint") && hasFullText(el)) continue;  // 提示整句移到欄位下方
    const cs = getComputedStyle(el, el.value ? null : "::placeholder");
    ctx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const box = getComputedStyle(el);
    const inner = el.clientWidth - parseFloat(box.paddingLeft) - parseFloat(box.paddingRight) - (el.type === "search" && !el.value ? 18 : 0);
    if (ctx.measureText(shown).width > inner + 2) out.truncated.push(`${name(el)} (${el.value ? "value" : "placeholder"}) 「${shown.slice(0, 30)}」`);
  }
  // 祖先裁切：文字節點的矩形超出某個 overflow:hidden 祖先
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  const reported = new Set();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const value = node.nodeValue.trim();
    if (!value) continue;
    const el = node.parentElement;
    if (!el || ["SCRIPT", "STYLE", "OPTION", "TEXTAREA", "TITLE", "NOSCRIPT"].includes(el.tagName)) continue;
    if (!visible(el) || hiddenByAncestor(el)) continue;
    range.selectNodeContents(node);
    const rects = [...range.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
    if (!rects.length) continue;
    const box = rects.reduce((a, r) => ({ left: Math.min(a.left, r.left), right: Math.max(a.right, r.right), top: Math.min(a.top, r.top), bottom: Math.max(a.bottom, r.bottom) }), { left: 1e9, right: -1e9, top: 1e9, bottom: -1e9 });
    const cs = getComputedStyle(el);
    const fs = parseFloat(cs.fontSize) || 14;
    // 2b. 祖先裁切
    for (let n = el; n && n !== document.body; n = n.parentElement) {
      const ncs = getComputedStyle(n);
      if (ncs.overflowX === "visible" && ncs.overflowY === "visible") continue;
      if (/(auto|scroll)/.test(ncs.overflowX)) break;
      const nr = n.getBoundingClientRect();
      if (nr.width <= 2 || nr.height <= 2) break;
      if (box.right > nr.right + 2 || box.left < nr.left - 2) {
        const key = name(el) + value.slice(0, 10);
        if (!reported.has(key)) { reported.add(key); out.truncated.push(`${name(el)} (clipped-by ${name(n)}) 「${value.slice(0, 30)}」`); }
        break;
      }
    }
    // 3. 太窄：行數多、每行字很少
    const tops = new Set(rects.map((r) => Math.round(r.top / 2)));
    const lines = tops.size;
    const chars = [...value.replace(/\s+/g, "")].length;
    if (lines >= 3 && chars / lines < 3.2 && chars >= 4) {
      const key = "n" + name(el) + value.slice(0, 10);
      if (!reported.has(key)) { reported.add(key); out.narrow.push(`${name(el)} ${lines}行/${chars}字 寬${Math.round(box.right - box.left)} 「${value.slice(0, 24)}」`); }
    } else if (lines >= 2 && chars <= 10 && chars >= 2 && !/[，。、；：,.]/.test(value)) {
      // 4. 短標籤被拆行（例如「其他收入」拆兩行）
      const key = "s" + name(el) + value.slice(0, 10);
      const parentText = text(el);
      // 段落裡的行內連結／粗體跨行是一般的文字換行（寬度接近整行），不算怪斷行。
      const inlineInProse = cs.display === "inline" && (box.right - box.left) > vw * 0.5;
      if (!reported.has(key) && parentText.length <= 14 && !inlineInProse) { reported.add(key); out.split.push(`${name(el)} ${lines}行 寬${Math.round(box.right - box.left)} 「${value}」`); }
    }
  }
  out.truncated = out.truncated.slice(0, 40);
  out.narrow = out.narrow.slice(0, 40);
  out.split = out.split.slice(0, 40);
  return out;
})()
