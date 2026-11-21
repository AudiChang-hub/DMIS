// T-267：手機（860px 以下）下拉選單與單行欄位放不下的內容不藏起來。
// 下拉、可搜尋下拉與文字欄位只能顯示一行；選到的內容比欄位寬時，在欄位下方補一行完整文字（會自然換行）。
// 只在手機寬度生效，電腦版不插入任何元素；輸入中（欄位有焦點）不顯示，離開欄位後才補上。
(() => {
  const phone = window.matchMedia("(max-width: 860px)");
  const SELECTOR = "select:not([multiple]), input.searchable-select__input, input[type=text], input[type=search], input:not([type])";
  const captions = new Map();

  const shownText = (control) => {
    if (control.tagName === "SELECT") return (control.selectedOptions[0]?.textContent || "").replace(/\s+/g, " ").trim();
    return control.value.trim();
  };
  const innerWidth = (control) => {
    const style = getComputedStyle(control);
    return control.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  };
  // 用頁面上的隱藏文字量寬度（和實際排版同一套字型與後援字型，比 canvas 準）。
  let ruler = null;
  const textWidth = (control, text, pseudo) => {
    const style = getComputedStyle(control, pseudo);
    if (!ruler) {
      ruler = document.createElement("span");
      ruler.className = "phone-full-text-ruler";
      ruler.setAttribute("aria-hidden", "true");
      ruler.style.cssText = "position:absolute;top:-9999px;left:-9999px;visibility:hidden;white-space:pre;pointer-events:none";
    }
    if (!ruler.isConnected) document.body.append(ruler);
    ruler.style.fontFamily = style.fontFamily;
    ruler.style.fontSize = style.fontSize;
    ruler.style.fontWeight = style.fontWeight;
    ruler.style.letterSpacing = style.letterSpacing;
    ruler.style.fontVariantNumeric = style.fontVariantNumeric;
    ruler.textContent = text;
    return ruler.getBoundingClientRect().width;
  };
  const overflows = (control, text) => {
    if (!text) return false;
    const inner = innerWidth(control);
    return inner > 0 && textWidth(control, text) > inner + 1;
  };
  // 提示文字縮小到最小 12px 放得下就縮（留在欄位裡最自然），放不下才移到欄位下方。
  const MIN_HINT = 12;
  const placeholderFits = (control) => {
    control.style.removeProperty("--phone-placeholder-size");
    const base = parseFloat(getComputedStyle(control, "::placeholder").fontSize) || 14;
    // 留餘裕：搜尋欄位右側保留清除鈕的位置（沒字時也佔寬），各瀏覽器字寬也略有差異。
    const inner = innerWidth(control) - (control.type === "search" ? 22 : 0) - 4;
    const width = textWidth(control, control.placeholder, "::placeholder");
    if (inner <= 0 || width <= inner) return true;
    const size = Math.floor(base * inner / width * 10) / 10;
    if (size < MIN_HINT) { control.style.removeProperty("--phone-placeholder-size"); return false; }
    control.style.setProperty("--phone-placeholder-size", `${size}px`);
    return true;
  };
  // 已經佔滿一列的欄位：拿掉整列樣式時是否原本就放得下（放得下就還原，不必佔滿）。
  const overflowsAt = (control, text) => {
    control.classList.remove("is-phone-wide");
    const tooWide = overflows(control, text);
    control.classList.add("is-phone-wide");
    return tooWide;
  };
  // 可搜尋下拉的輸入框包在 .searchable-select 裡，說明接在整組後面，不插進元件中間。
  // 搜尋框這類「外框包著圖示與欄位」的元件也一樣，接在外框後面。
  const BOXES = ".searchable-select, .help-search__row, .inventory-search-box, .order-overview__search, .photo-board__search, .form-print__search, .model-index__search, .model-nav__search, .price-distribution-search-field";
  const anchorOf = (control) => control.closest(BOXES) || control;

  const update = (control) => {
    const anchor = anchorOf(control);
    const value = shownText(control);
    const visible = control.getClientRects().length > 0 && !control.disabled;
    // 空欄位的提示文字（placeholder）放不下：整句移到欄位下方，欄位裡的提示改透明，不留半句被切掉的字。
    const shown = value || (control.tagName === "SELECT" ? "" : control.placeholder) || "";
    // 和按鈕併排時先讓欄位自己佔滿一整列；佔滿後放得下就不用另補一行。
    const boxed = anchor !== control && !anchor.matches(".searchable-select");  // 搜尋外框裡的欄位不另外拉寬
    const wide = !boxed && phone.matches && visible && (control.classList.contains("is-phone-wide") ? shown && overflowsAt(control, shown, true) : overflows(control, shown));
    control.classList.toggle("is-phone-wide", Boolean(wide));
    const hint = control.tagName !== "SELECT" && !value && control.placeholder && phone.matches && visible && !placeholderFits(control);
    // 已選或已填的內容放不下：離開欄位後在下方補一行完整內容（輸入中不顯示，免得重複）。
    const full = !hint && phone.matches && visible && document.activeElement !== control && overflows(control, value);
    control.classList.toggle("has-phone-hint", Boolean(hint));
    let caption = captions.get(control);
    if (!hint && !full) {
      if (caption) { caption.remove(); captions.delete(control); }
      return;
    }
    if (!caption || !caption.isConnected) {
      caption = document.createElement("small");
      caption.setAttribute("aria-hidden", "true");  // 讀屏已會讀出欄位本身的值與提示
      captions.set(control, caption);
    }
    caption.className = hint ? "phone-full-text phone-full-text--hint" : "phone-full-text";
    if (caption.previousElementSibling !== anchor) anchor.after(caption);
    caption.parentElement?.classList.add("has-phone-caption");  // 橫排的父層要能換行，補充的一行才會排到欄位下方
    caption.textContent = hint ? control.placeholder : value;
  };

  const scan = () => {
    if (!phone.matches) {
      captions.forEach((caption) => caption.remove());
      captions.clear();
      document.querySelectorAll(".has-phone-hint, .is-phone-wide").forEach((control) => control.classList.remove("has-phone-hint", "is-phone-wide"));
      return;
    }
    document.querySelectorAll(SELECTOR).forEach(update);
    captions.forEach((caption, control) => { if (!control.isConnected) { caption.remove(); captions.delete(control); } });
  };

  let pending = 0;
  const schedule = () => {
    if (pending) return;
    pending = window.requestAnimationFrame(() => { pending = 0; scan(); });
  };
  const onControl = (event) => {
    const control = event.target.closest?.(SELECTOR);
    if (control && phone.matches) update(control);
  };

  document.addEventListener("change", onControl, true);
  document.addEventListener("input", (event) => {  // 開始輸入就收起提示、清空後再放回
    const control = event.target.closest?.(SELECTOR);
    if (control && phone.matches && (control.classList.contains("has-phone-hint") || !control.value)) update(control);
  }, true);
  document.addEventListener("focusin", onControl, true);
  document.addEventListener("focusout", (event) => {
    const control = event.target.closest?.(SELECTOR);
    if (control && phone.matches) window.setTimeout(() => update(control), 0);
  }, true);
  window.addEventListener("resize", schedule);
  phone.addEventListener?.("change", schedule);
  document.addEventListener("htmx:afterSettle", schedule);
  document.addEventListener("click", schedule);  // 切換分頁、展開區塊後，原本藏著的欄位才量得到寬度
  // 之後才載入的內容（例如訂單總覽面板）：DOM 有新增節點時，停 300ms 再整頁量一次。
  let settle = 0;
  new MutationObserver((records) => {
    if (!phone.matches || !records.some((record) => [...record.addedNodes].some((node) => node.nodeType === 1 && !String(node.className).startsWith("phone-full-text")))) return;
    window.clearTimeout(settle);
    settle = window.setTimeout(schedule, 300);
  }).observe(document.documentElement, { childList: true, subtree: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", schedule);
  else schedule();
  window.addEventListener("load", schedule);
})();
