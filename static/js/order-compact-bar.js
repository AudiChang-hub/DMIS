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
  let observer = null;
  const observe = () => {
    observer?.disconnect();
    const offset = Math.round(headerHeight());
    observer = new IntersectionObserver(([entry]) => {
      setShown(!entry.isIntersecting && entry.boundingClientRect.bottom <= offset + 1);
    }, {rootMargin: `-${offset}px 0px 0px 0px`});
    observer.observe(hero);
  };
  observe();
  window.addEventListener('resize', () => observe(), {passive: true});
  // 「變更車行／變更來源」回到頁首，直接打開小卡的浮層。
  bar.querySelector('[data-compact-change]')?.addEventListener('click', () => {
    window.scrollTo({top: 0, behavior: 'instant'});
    const editor = document.querySelector('#commission-attribution .commission-attribution__editor');
    if (!editor) return;
    editor.open = true;
    editor.querySelector('summary')?.focus({preventScroll: true});
  });
})();
