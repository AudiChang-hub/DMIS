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
  // 從哪來回哪去（T-291）：白名單頁（<main data-link-source>）點往其他頁的本站連結時補 back_to＝目前路徑與篩選，
  // 目的頁的返回列由伺服器驗證後回到來源。目的頁網址帶 back_to 時，同頁的篩選表單、分頁／排序連結與
  // pushState 一路帶著，點一次篩選不會丟失來源。網址沒有 back_to 的頁面只有來源端會補參數，其餘不變。
  const BACK_PARAM = "back_to";
  const BACK_MAX = 2000;
  const initialBackTo = new URLSearchParams(window.location.search).get(BACK_PARAM) || "";
  const ownSource = parseSameOriginUrl(initialBackTo);
  const sourceMain = document.querySelector("main[data-link-source]");
  const pageMain = sourceMain || document.querySelector("main");
  const carryBackTo = url => {
    if (!initialBackTo || url === undefined || url === null || url === "") return url;
    const next = parseSameOriginUrl(String(url));
    if (!next || next.pathname !== window.location.pathname || next.searchParams.has(BACK_PARAM)) return url;
    next.searchParams.set(BACK_PARAM, initialBackTo);
    return next.pathname + next.search + next.hash;
  };
  const prepareLink = link => {
    const href = link.getAttribute("href");
    if (!href || href.startsWith("#") || link.hasAttribute("download") || link.hasAttribute("data-return-to") || link.hasAttribute("data-no-back-to")) return;
    if (!pageMain || !pageMain.contains(link)) return;
    const target = parseSameOriginUrl(href);
    if (!target || !/^https?:$/.test(target.protocol) || target.searchParams.has(BACK_PARAM)) return;
    if (target.pathname === window.location.pathname) {
      if (!initialBackTo) return;
      target.searchParams.set(BACK_PARAM, initialBackTo);
    } else {
      if (!sourceMain || /^\/(static|media)\//.test(target.pathname)) return;
      if (ownSource && ownSource.pathname === target.pathname) return;  // 回自己的來源，不再疊一層
      const value = window.location.pathname + listQuery(window.location);
      if (value.length > BACK_MAX) return;
      target.searchParams.set(BACK_PARAM, value);
    }
    link.setAttribute("href", target.pathname + target.search + target.hash);
  };
  // 點下（含中鍵、右鍵另開分頁、鍵盤 Enter）當下才補，動態插入的連結與 pushState 後的篩選都用最新網址。
  ["mousedown", "click", "contextmenu"].forEach(type => window.addEventListener(type, event => {
    const link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
    if (link) prepareLink(link);
  }, true));
  const carryForm = form => {
    if ((form.getAttribute("method") || "get").toLowerCase() !== "get") return;
    const action = parseSameOriginUrl(form.getAttribute("action") || window.location.href);
    if (!action || action.pathname !== window.location.pathname) return;
    if ([...form.elements].some(field => field.name === BACK_PARAM)) return;
    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = BACK_PARAM;
    hidden.value = initialBackTo;
    form.appendChild(hidden);
  };
  if (initialBackTo) {
    document.querySelectorAll("main form").forEach(carryForm);
    window.addEventListener("submit", event => {
      if (event.target && event.target.tagName === "FORM" && pageMain && pageMain.contains(event.target)) carryForm(event.target);
    }, true);
  }

  // 分頁籤、換頁等以 pushState／replaceState 改網址的頁面，網址一變就更新記住的篩選。
  ["pushState", "replaceState"].forEach(method => {
    const original = window.history[method];
    window.history[method] = function (...args) {
      if (args.length > 2) args[2] = carryBackTo(args[2]);
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
