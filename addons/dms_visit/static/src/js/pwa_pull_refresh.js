/** @odoo-module */
/**
 * iOS PWA 下拉重新整理 + 回頂按鈕
 *
 * 行為設計：
 * - 「回頂按鈕」：向下滑超過 120px 後出現，點擊平滑回到頂端
 * - 「下拉重新整理」：必須真的在頂端（scrollTop === 0）才能觸發，
 *   且初始觸碰方向必須是向下，避免向上滑動時誤觸
 * - 僅在 iOS PWA standalone 模式（加到桌面）下啟用
 */
(function () {
    "use strict";

    if (!window.navigator.standalone) return;

    const THRESHOLD      = 72;   // PTR 觸發閾值（px）
    const MAX_SHOW       = 96;   // PTR 指示器最大高度（px）
    const SCROLL_TOP_BTN = 120;  // 顯示回頂按鈕的滾動距離（px）

    let startY     = null;
    let startST    = null;  // touchstart 當下的 scrollTop
    let pullDist   = 0;
    let indicator  = null;
    let topBtn     = null;
    let rafId      = null;
    let scrollEl   = null;

    // ── 取得正確的滾動容器（動態找，因為 Odoo route 切換後 DOM 會重建）──
    function getScrollEl() {
        // 優先找 Kanban / List 的內容容器（真正在滾動的那個）
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
        // fallback：找 scrollTop > 0 的任何可滾元素
        const all = document.querySelectorAll(".o_content *");
        for (const el of all) {
            if (el.scrollTop > 0) return el;
        }
        return document.querySelector(".o_content") || document.documentElement;
    }

    // ── 建立 PTR 指示器 ────────────────────────────────────────
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

    // ── 建立「回頂按鈕」────────────────────────────────────────
    function createTopBtn() {
        const btn = document.createElement("button");
        btn.id = "dms-to-top-btn";
        btn.setAttribute("aria-label", "回到頂端");
        btn.innerHTML = '<i class="fa fa-arrow-up"></i>';
        btn.addEventListener("click", function () {
            const el = getScrollEl();
            el.scrollTo({ top: 0, behavior: "smooth" });
        });
        document.body.appendChild(btn);
        return btn;
    }

    // ── 監聽滾動，控制回頂按鈕顯示/隱藏 ──────────────────────
    function onScroll() {
        const el = scrollEl || getScrollEl();
        if (!topBtn) topBtn = createTopBtn();
        if (el.scrollTop > SCROLL_TOP_BTN) {
            topBtn.classList.add("visible");
        } else {
            topBtn.classList.remove("visible");
        }
    }

    // ── Touch 事件處理 ──────────────────────────────────────────
    document.addEventListener("touchstart", function (e) {
        scrollEl = getScrollEl();
        // 記錄當下 scrollTop，用於判斷是否真的在頂端
        startST = scrollEl.scrollTop;
        startY  = e.touches[0].clientY;
        pullDist = 0;
    }, { passive: true });

    document.addEventListener("touchmove", function (e) {
        if (startY === null || startST === null) return;

        const diff = e.touches[0].clientY - startY;

        // 條件：1) 初始在頂端  2) 向下拉（diff > 0）
        if (startST <= 0 && diff > 4) {
            pullDist = diff;
            if (rafId) cancelAnimationFrame(rafId);
            rafId = requestAnimationFrame(function () {
                renderIndicator(pullDist);
            });
        } else if (diff < 0 || startST > 0) {
            // 向上滑或不在頂端 → 確保不顯示 PTR
            if (indicator) hideIndicator();
            pullDist = 0;
        }
    }, { passive: true });

    document.addEventListener("touchend", function () {
        if (rafId) cancelAnimationFrame(rafId);
        rafId = null;

        if (pullDist >= THRESHOLD && indicator) {
            indicator.querySelector(".dms-ptr-arrow").textContent = "↻";
            indicator.querySelector(".dms-ptr-label").textContent = "重新整理中…";
            setTimeout(function () { window.location.reload(); }, 350);
        } else {
            hideIndicator();
        }

        startY   = null;
        startST  = null;
        pullDist = 0;
    }, { passive: true });

    // ── 滾動監聽（用 capture 確保抓到正確容器）──────────────────
    // 用 document 層捕捉，因為 Odoo 路由切換後容器會換
    document.addEventListener("scroll", function () {
        scrollEl = getScrollEl();
        onScroll();
    }, { capture: true, passive: true });

    // 路由切換後重設滾動容器
    window.addEventListener("hashchange", function () {
        scrollEl = null;
        if (topBtn) { topBtn.classList.remove("visible"); }
    });
    window.addEventListener("popstate", function () {
        scrollEl = null;
        if (topBtn) { topBtn.classList.remove("visible"); }
    });

})();
