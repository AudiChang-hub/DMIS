(() => {
  // 解鎖（淨利、被遮罩資料共用）：閒置到期才鎖；畫面偵測到真人操作時通知伺服器延長。
  const body = document.body;
  let until = Number(body.dataset.unlockUntil || body.dataset.profitUntil || 0);
  if (!until) return;
  const touchUrl = body.dataset.unlockTouchUrl || '';
  const csrf = body.dataset.unlockCsrf || '';
  const online = typeof fetch === 'function' && !!touchUrl;
  const PING_MS = 60 * 1000;  // 同一頁最多每分鐘通知一次，避免每次捲動都送出
  let timer = null, lastPing = 0, locked = false;

  const applyLock = () => {
    locked = true;
    document.querySelectorAll('[data-profit-value]').forEach(el => el.replaceChildren(document.createTextNode('已鎖定')));
    document.querySelectorAll('[data-order-sort-key="profit"]').forEach(el => {
      el.removeAttribute('href'); el.removeAttribute('data-order-sort-key'); el.textContent = '淨利 · 解鎖後可排序';
    });
    document.querySelectorAll('.profit-control[data-profit-until]').forEach(el => {
      const message = document.createElement('span'); message.textContent = '淨利已到期鎖定；未儲存的表單內容仍保留。';
      const link = document.createElement('a'); link.textContent = '重新解鎖'; link.className = 'button ghost small';
      link.href = '/account/profit/unlock/?next=' + encodeURIComponent(location.pathname + location.search);
      el.replaceChildren(message, link);
    });
    // 已顯示的完整匯款帳戶等被遮罩資料也要重新遮住（由各自的程式處理）。
    if (typeof CustomEvent === 'function' && typeof document.dispatchEvent === 'function') {
      document.dispatchEvent(new CustomEvent('dmis:unlock-expired'));
    }
  };

  const arm = () => {
    if (timer && typeof clearTimeout === 'function') clearTimeout(timer);
    timer = setTimeout(mask, Math.max(0, until - Date.now()));
  };

  const setUntil = value => {
    until = value;
    body.dataset.profitUntil = String(value);
    body.dataset.unlockUntil = String(value);
    document.querySelectorAll('.profit-control[data-profit-until]').forEach(el => { el.dataset.profitUntil = String(value); });
    arm();
  };

  function mask() {
    if (Date.now() < until) return;
    if (!online || locked) { applyLock(); return; }
    // 其他分頁可能已經延長：先問伺服器，真的過期才遮蔽。
    fetch(touchUrl, {credentials: 'same-origin', headers: {Accept: 'application/json'}})
      .then(response => response.json())
      .then(data => { if (data && data.ok && Number(data.until) > Date.now()) setUntil(Number(data.until)); else applyLock(); })
      .catch(applyLock);
  }

  const activity = () => {
    const now = Date.now();
    if (!online || locked || now >= until || now - lastPing < PING_MS) return;
    lastPing = now;
    fetch(touchUrl, {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf, Accept: 'application/json'}})
      .then(response => response.json())
      .then(data => {
        if (data && data.ok) setUntil(Number(data.until));
        else if (data && data.locked) { until = Date.now(); mask(); }
      })
      .catch(() => {});
  };

  arm();
  if (online) {
    // 只算真人操作；背景輪詢、心跳不算，人離開後頁面開著也會照時間鎖上。
    ['pointerdown', 'keydown', 'touchstart', 'scroll'].forEach(name =>
      document.addEventListener(name, activity, {capture: true, passive: true}));
  }
  document.addEventListener('visibilitychange', mask);
  window.addEventListener('pageshow', mask);
})();
