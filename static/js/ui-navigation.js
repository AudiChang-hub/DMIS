(() => {
  if ("scrollRestoration" in window.history) {
    window.history.scrollRestoration = "auto";
  }

  const parseSameOriginUrl = value => {
    if (!value) return null;
    try {
      const url = new URL(value, window.location.href);
      return url.origin === window.location.origin ? url : null;
    } catch {
      return null;
    }
  };

  // 頁面返回列的目的地固定（上一層），不用瀏覽器上一頁；改由這裡記住每個列表最後的篩選與捲動位置，
  // 從明細回列表時帶回去。只存在本分頁（sessionStorage），編輯中、剛存檔等一次性參數不記。
  const RETURN_KEY = "dmis:return:";
  const RETURN_PENDING_KEY = "dmis:return-pending";
  const TRANSIENT_PARAMS = ["edit", "new", "new_reward", "saved", "focus", "next", "download", "sign", "inline"];
  const storage = {
    get(key) { try { return JSON.parse(window.sessionStorage.getItem(key)); } catch { return null; } },
    set(key, value) { try { window.sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* 無痕或停用儲存時照常運作 */ } },
    remove(key) { try { window.sessionStorage.removeItem(key); } catch { /* 同上 */ } },
  };
  const listQuery = url => {
    const params = new URLSearchParams(url.search);
    TRANSIENT_PARAMS.forEach(name => params.delete(name));
    const query = params.toString();
    return query ? `?${query}` : "";
  };
  const rememberListState = () => {
    const query = listQuery(window.location);
    const key = RETURN_KEY + window.location.pathname;
    const previous = storage.get(key);
    storage.set(key, {query, y: previous && previous.query === query ? previous.y : 0});
  };
  const rememberScroll = () => {
    const key = RETURN_KEY + window.location.pathname;
    storage.set(key, {query: listQuery(window.location), y: Math.round(window.scrollY)});
  };
  // 分頁籤、換頁等以 pushState／replaceState 改網址的頁面，網址一變就更新記住的篩選。
  ["pushState", "replaceState"].forEach(method => {
    const original = window.history[method];
    window.history[method] = function (...args) {
      const result = original.apply(this, args);
      rememberListState();
      return result;
    };
  });
  window.addEventListener("popstate", rememberListState);
  window.addEventListener("pagehide", rememberScroll);
  rememberListState();

  document.querySelectorAll("a[data-return-to]").forEach(link => {
    const target = parseSameOriginUrl(link.getAttribute("href"));
    if (!target || target.pathname === window.location.pathname) return;
    const saved = storage.get(RETURN_KEY + target.pathname);
    if (!target.search && saved && saved.query) {
      link.href = target.pathname + saved.query + target.hash;
    }
    link.addEventListener("click", () => {
      const destination = parseSameOriginUrl(link.href);
      if (destination) storage.set(RETURN_PENDING_KEY, destination.pathname + destination.search);
    });
  });

  // 經由返回列回到列表：回到離開時的捲動位置（一般進入列表維持在頁首）。
  const pending = storage.get(RETURN_PENDING_KEY);
  if (pending) {
    storage.remove(RETURN_PENDING_KEY);
    const here = window.location.pathname + window.location.search;
    const saved = storage.get(RETURN_KEY + window.location.pathname);
    if (pending === here && saved && saved.y > 0 && !window.location.hash) {
      // 畫面一出來就定位；圖片載完版面變高時再校正一次，使用者已自行捲動就不再搶。
      let userMoved = false;
      ["wheel", "touchstart", "keydown"].forEach(type => window.addEventListener(type, () => { userMoved = true; }, {once: true, passive: true}));
      const restore = () => { if (!userMoved) window.scrollTo({top: saved.y, behavior: "instant"}); };
      restore();
      window.requestAnimationFrame(restore);
      if (document.readyState !== "complete") window.addEventListener("load", () => window.requestAnimationFrame(restore), {once: true});
    }
  }

  // 錯誤頁的「返回上一頁」才使用瀏覽器上一頁；沒有本站上一頁時回首頁。
  document.querySelectorAll("[data-history-back]").forEach(control => {
    control.addEventListener("click", () => {
      const referrer = parseSameOriginUrl(document.referrer);
      if (referrer && referrer.href !== window.location.href && window.history.length > 1) {
        window.history.back();
        return;
      }
      const fallbackUrl = parseSameOriginUrl(control.dataset.fallbackUrl);
      if (fallbackUrl) window.location.assign(fallbackUrl.href);
    });
  });

  document.querySelectorAll("[data-current-page-label]").forEach(label => {
    if (label.textContent.trim()) {
      label.hidden = false;
      return;
    }
    const heading = document.querySelector("main h1");
    if (!heading) return;
    label.textContent = heading.textContent.trim();
    label.hidden = !label.textContent;
  });

  const mobileMenu = document.querySelector(".mobile-data-menu");
  if (mobileMenu) {
    document.addEventListener("click", event => {
      if (mobileMenu.open && !mobileMenu.contains(event.target)) {
        mobileMenu.open = false;
      }
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && mobileMenu.open) {
        mobileMenu.open = false;
        mobileMenu.querySelector("summary")?.focus();
      }
    });
  }

  // SUZUKI 查零件：連結照常另開官方網站，同時把號碼放進剪貼簿，到官方搜尋列直接貼上。
  document.querySelectorAll("[data-parts-lookup]").forEach(link => {
    link.addEventListener("click", () => {
      const number = link.dataset.partsLookup;
      if (!number || !navigator.clipboard) return;
      navigator.clipboard.writeText(number).then(() => {
        const original = link.innerHTML;
        link.textContent = `已複製 ${number}`;
        window.setTimeout(() => { link.innerHTML = original; }, 4000);
      }).catch(() => {});
    });
  });

  const accountMenu = document.querySelector("[data-account-menu]");
  if (accountMenu) {
    document.addEventListener("click", event => {
      if (accountMenu.open && !accountMenu.contains(event.target)) accountMenu.open = false;
    });
    accountMenu.addEventListener("keydown", event => {
      if (event.key === "Escape" && accountMenu.open) {
        accountMenu.open = false;
        accountMenu.querySelector("summary")?.focus();
      }
    });
    accountMenu.querySelectorAll("[data-theme-open], [data-check-update]").forEach(item => {
      item.addEventListener("click", () => { accountMenu.open = false; });
    });
  }

  const shortcutDialog = document.querySelector("[data-mobile-shortcuts-dialog]");
  if (shortcutDialog) {
    const shortcutForm = shortcutDialog.querySelector("form");
    const shortcutSelects = [...shortcutDialog.querySelectorAll('select[name="shortcut"]')];
    document.querySelectorAll("[data-mobile-shortcuts-open]").forEach(button => {
      button.addEventListener("click", () => {
        if (mobileMenu) mobileMenu.open = false;
        shortcutDialog.showModal();
      });
    });
    shortcutDialog.querySelectorAll("[data-mobile-shortcuts-close]").forEach(button => {
      button.addEventListener("click", () => shortcutDialog.close());
    });
    shortcutDialog.addEventListener("click", event => {
      if (event.target === shortcutDialog) shortcutDialog.close();
    });
    shortcutSelects.forEach(select => {
      select.addEventListener("change", () => {
        shortcutSelects.forEach(item => item.setCustomValidity(""));
      });
    });
    shortcutForm?.addEventListener("submit", event => {
      shortcutSelects.forEach(select => select.setCustomValidity(""));
      const selected = shortcutSelects.filter(select => select.value);
      if (!selected.length) {
        event.preventDefault();
        shortcutSelects[0].setCustomValidity("請至少保留一個快速前往功能。");
        shortcutSelects[0].reportValidity();
        return;
      }
      const duplicate = selected.find((select, index) => (
        selected.findIndex(item => item.value === select.value) !== index
      ));
      if (duplicate) {
        event.preventDefault();
        duplicate.setCustomValidity("同一個功能不能重複設定。");
        duplicate.reportValidity();
      }
    });
  }
})();
