/** @odoo-module */
/**
 * iOS PWA 下拉重新整理 + 回頂按鈕
 *
 * 三道防護確保不誤觸：
 * 1. trustedScrollEl — 由 scroll 事件的 e.target 直接取得真正在滾的容器，
 *    不再用 CSS selector 猜測（解決 Kanban scrollTop 永遠是 0 的問題）
 * 2. SETTLE_TIME 靜置門檻 — 距上次滾動事件必須超過 350ms，
 *    排除「慣性滾到頂再觸碰」的誤觸場景
 * 3. 首次移動方向判斷 — touchmove 第一下若是向上則立即關閉 PTR
 */
(function () {
    "use strict";

    if (!window.navigator.standalone) return;

    const THRESHOLD      = 72;    // PTR 觸發閾值（px）
    const MAX_SHOW       = 96;    // PTR 指示器最大高度（px）
    const SCROLL_TOP_BTN = 120;   // 顯示回頂按鈕的滾動距離（px）
    const SETTLE_TIME    = 350;   // 滾動停止後須靜置多久才允許 PTR（ms）

    let startY          = null;
    let pullDist        = 0;
    let ptrEnabled      = false;  // 由 touchstart 決定，touchmove 才使用
    let indicator       = null;
    let topBtn          = null;
    let rafId           = null;
    let trustedScrollEl = null;   // 真正在捲動的 DOM 節點（scroll 事件設定）
    let lastScrollTime  = 0;      // 上次 scroll 事件的 timestamp

    // ── scroll 事件：記住真正在滾的容器與時間 ─────────────────────
    // capture: true 確保能捕捉到子元素的 scroll
    document.addEventListener("scroll", function (e) {
        const t = e.target;
        if (t && t !== document && t !== window && t.nodeType === 1) {
            trustedScrollEl = t;
        }
        lastScrollTime = Date.now();
        onScroll();
    }, { capture: true, passive: true });

    function getScrollEl() {
        // 優先用 scroll 事件直接確認的容器
        if (trustedScrollEl && trustedScrollEl.isConnected) {
            return trustedScrollEl;
        }
        // Fallback：依序嘗試常見容器
        const candidates = [
            ".o_kanban_renderer",
            ".o_list_renderer",
            ".o_renderer",
            ".o_content",
        ];
        for (const sel of candidates) {
            const el = document.querySelector(sel);
            if (el && el.scrollHeight > el.clientHeight + 2) return el;
        }
        return document.querySelector(".o_content") || document.documentElement;
    }

    // ── PTR 指示器 ─────────────────────────────────────────────────
    function createIndicator() {
        const el = document.createElement("div");
        el.id = "dms-ptr-indicator";
        el.innerHTML =
            '<span class="dms-ptr-arrow">↓</span>' +
            '<span class="dms-ptr-label">下拉以重新整理</span>';
        document.body.appendChild(el);
        return el;
    }

    function renderIndicator(dist) {
        if (!indicator) indicator = createIndicator();
        const capped = Math.min(dist, MAX_SHOW);
        const ratio  = Math.min(dist / THRESHOLD, 1);
        const ready  = dist >= THRESHOLD;
        indicator.style.height  = capped + "px";
        indicator.style.opacity = ratio.toFixed(2);
        indicator.querySelector(".dms-ptr-arrow").style.transform =
            ready ? "rotate(180deg)" : "rotate(0deg)";
        indicator.querySelector(".dms-ptr-label").textContent =
            ready ? "放開以重新整理" : "下拉以重新整理";
    }

    function hideIndicator() {
        if (indicator) { indicator.remove(); indicator = null; }
    }

    // ── 回頂按鈕 ───────────────────────────────────────────────────
    function createTopBtn() {
        const btn = document.createElement("button");
        btn.id = "dms-to-top-btn";
        btn.setAttribute("aria-label", "回到頂端");
        btn.innerHTML = '<i class="fa fa-arrow-up"></i>';
        btn.addEventListener("click", function () {
            getScrollEl().scrollTo({ top: 0, behavior: "smooth" });
        });
        document.body.appendChild(btn);
        return btn;
    }

    function onScroll() {
        if (!topBtn) topBtn = createTopBtn();
        const scrollTop = trustedScrollEl ? trustedScrollEl.scrollTop
                        : getScrollEl().scrollTop;
        topBtn.classList.toggle("visible", scrollTop > SCROLL_TOP_BTN);
    }

    // ── Touch 事件 ─────────────────────────────────────────────────
    document.addEventListener("touchstart", function (e) {
        const el        = getScrollEl();
        const scrollTop = el.scrollTop;
        const idleMs    = Date.now() - lastScrollTime;

        // PTR 啟用條件（三者同時成立）：
        //   A. 目前在頂端（scrollTop === 0）
        //   B. 距上次滾動已靜置 SETTLE_TIME（排除慣性到頂後立即誤觸）
        ptrEnabled = (scrollTop <= 0 && idleMs >= SETTLE_TIME);

        startY   = e.touches[0].clientY;
        pullDist = 0;
    }, { passive: true });

    document.addEventListener("touchmove", function (e) {
        if (!ptrEnabled || startY === null) return;

        const diff = e.touches[0].clientY - startY;

        if (diff > 4) {
            // 向下拉 → 顯示指示器
            pullDist = diff;
            if (rafId) cancelAnimationFrame(rafId);
            rafId = requestAnimationFrame(function () {
                renderIndicator(pullDist);
            });
        } else if (diff < -4) {
            // 向上滑 → 立即關閉 PTR（第三道防護：首次方向判斷）
            ptrEnabled = false;
            hideIndicator();
            pullDist = 0;
        }
    }, { passive: true });

    document.addEventListener("touchend", function () {
        if (rafId) cancelAnimationFrame(rafId);
        rafId = null;

        if (ptrEnabled && pullDist >= THRESHOLD && indicator) {
            indicator.querySelector(".dms-ptr-arrow").textContent = "↻";
            indicator.querySelector(".dms-ptr-label").textContent = "重新整理中…";
            setTimeout(function () { window.location.reload(); }, 350);
        } else {
            hideIndicator();
        }

        startY     = null;
        pullDist   = 0;
        ptrEnabled = false;
    }, { passive: true });

    // ── 路由切換後重設（Odoo SPA 換頁後 DOM 重建）────────────────
    window.addEventListener("hashchange", function () {
        trustedScrollEl = null;
        lastScrollTime  = 0;
        if (topBtn) topBtn.classList.remove("visible");
    });
    window.addEventListener("popstate", function () {
        trustedScrollEl = null;
        lastScrollTime  = 0;
        if (topBtn) topBtn.classList.remove("visible");
    });

})();
