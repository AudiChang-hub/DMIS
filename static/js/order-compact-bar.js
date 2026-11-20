// 訂單頁精簡列（使用者 2026-10-21）：完整頁首照常捲走；頁首整個離開畫面後，精簡列從頂端淡入。
// 精簡列放在高度為 0 的 sticky 定位點上、以絕對定位疊在內容上，出現與消失都不改變版面高度，
// 不需要墊高補位，往下捲時不會出現空白，也不會因捲動錨定在兩種狀態間來回切換。
(() => {
  const hero = document.querySelector('[data-order-hero]');
  const bar = document.querySelector('[data-order-compact-bar]');
  if (!hero || !bar) return;
  const headerHeight = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--app-header-height')) || 72;
  // 狀態與歸屬可能已在頁面上原地更新，顯示前從頁首同步最新文字。
  const sync = () => {
    const status = document.getElementById('order-status-pill');
    const target = bar.querySelector('[data-compact-status]');
    if (status && target) {
      target.textContent = status.textContent.trim();
      target.className = [...status.classList].filter(name => name !== 'large').join(' ');
      target.dataset.compactStatus = '';
    }
    const recipient = document.querySelector('#commission-attribution .commission-attribution__recipient');
    const compactRecipient = bar.querySelector('[data-compact-recipient]');
    if (recipient && compactRecipient) compactRecipient.textContent = recipient.textContent.trim();
  };
  const setShown = (shown) => {
    if (shown === bar.classList.contains('is-shown')) return;
    if (shown) sync();
    bar.classList.toggle('is-shown', shown);
    bar.toggleAttribute('inert', !shown);
    bar.setAttribute('aria-hidden', String(!shown));
  };
  // T-250 B 案（使用者 2026-11-19）：手機版（≤860px）精簡列常駐在頂端、捲動時不縮小，下面一行是換步驟與總覽；
  // 頁首裡的狀態與車行原地更新時，跟著同步。電腦版維持頁首捲走後才浮出。
  const pinnedQuery = window.matchMedia('(max-width: 860px)');
  let observer = null;
  const observe = () => {
    observer?.disconnect();
    if (pinnedQuery.matches) { setShown(true); return; }
    setShown(false);
    const offset = Math.round(headerHeight());
    observer = new IntersectionObserver(([entry]) => {
      setShown(!entry.isIntersecting && entry.boundingClientRect.bottom <= offset + 1);
    }, {rootMargin: `-${offset}px 0px 0px 0px`});
    observer.observe(hero);
  };
  observe();
  window.addEventListener('resize', () => observe(), {passive: true});
  new MutationObserver(() => { if (bar.classList.contains('is-shown')) sync(); })
    .observe(hero, {childList: true, characterData: true, subtree: true});
  // 跳到某一步時，標題停在精簡列下方（scroll-margin 用這個高度）。
  const root = document.documentElement;
  const publishHeight = () => root.style.setProperty('--order-compact-height', `${pinnedQuery.matches ? bar.offsetHeight : 0}px`);
  if (window.ResizeObserver) new ResizeObserver(publishHeight).observe(bar);
  publishHeight();
  window.addEventListener('resize', publishHeight, {passive: true});
  // 「變更車行／變更來源」回到頁首，直接打開小卡的浮層。
  bar.querySelector('[data-compact-change]')?.addEventListener('click', () => {
    window.scrollTo({top: 0, behavior: 'instant'});
    const editor = document.querySelector('#commission-attribution .commission-attribution__editor');
    if (!editor) return;
    editor.open = true;
    // 手機版小卡上的「變更車行」收起來了（T-254）：焦點直接進浮層的第一個欄位，並讓浮層在畫面內。
    const summary = editor.querySelector('summary');
    const panel = editor.querySelector('.commission-attribution__panel');
    const target = summary?.getClientRects().length ? summary
      : panel?.querySelector('select, input:not([type=hidden]), textarea, button:not([hidden])');
    target?.focus({preventScroll: true});
    panel?.scrollIntoView({block: 'nearest', behavior: 'instant'});
  });
})();
