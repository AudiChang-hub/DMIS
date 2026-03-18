/** @odoo-module */
/**
 * iOS PWA 下拉重新整理（Pull-to-Refresh）
 * 僅在 iOS 桌面捷徑（standalone mode）下啟用，避免影響桌面瀏覽器體驗。
 */
(function () {
    "use strict";

    // 只在 iOS PWA standalone 模式下啟用
    if (!window.navigator.standalone) return;

    const THRESHOLD = 72;   // 觸發所需下拉距離（px）
    const MAX_SHOW  = 96;   // 視覺指示器最大高度（px）

    let startY    = null;
    let pullDist  = 0;
    let indicator = null;
    let rafId     = null;

    // ── 建立指示器 DOM ───────────────────────────────────────────
    function createIndicator() {
        const el = document.createElement("div");
        el.id = "dms-ptr-indicator";
        el.innerHTML =
            '<span class="dms-ptr-arrow">↓</span>' +
            '<span class="dms-ptr-label">下拉以重新整理</span>';
        document.body.appendChild(el);
        return el;
    }

    function getScrollEl() {
        return document.querySelector(".o_content") || document.documentElement;
    }

    // ── 渲染指示器狀態 ───────────────────────────────────────────
    function renderIndicator(dist) {
        if (!indicator) indicator = createIndicator();

        const capped = Math.min(dist, MAX_SHOW);
        const ratio  = Math.min(dist / THRESHOLD, 1);
        const ready  = dist >= THRESHOLD;

        indicator.style.height  = capped + "px";
        indicator.style.opacity = ratio.toFixed(2);

        const arrowEl = indicator.querySelector(".dms-ptr-arrow");
        const labelEl = indicator.querySelector(".dms-ptr-label");

        arrowEl.style.transform = ready ? "rotate(180deg)" : "rotate(0deg)";
        labelEl.textContent = ready ? "放開以重新整理" : "下拉以重新整理";
    }

    function hideIndicator() {
        if (indicator) {
            indicator.remove();
            indicator = null;
        }
    }

    // ── Touch 事件處理 ───────────────────────────────────────────
    document.addEventListener("touchstart", function (e) {
        const el = getScrollEl();
        // 只在內容頂端才啟動下拉偵測
        if (el.scrollTop <= 0) {
            startY   = e.touches[0].clientY;
            pullDist = 0;
        }
    }, { passive: true });

    document.addEventListener("touchmove", function (e) {
        if (startY === null) return;
        const diff = e.touches[0].clientY - startY;
        if (diff > 4) {
            pullDist = diff;
            if (rafId) cancelAnimationFrame(rafId);
            rafId = requestAnimationFrame(function () {
                renderIndicator(pullDist);
            });
        }
    }, { passive: true });

    document.addEventListener("touchend", function () {
        if (rafId) cancelAnimationFrame(rafId);
        rafId = null;

        if (pullDist >= THRESHOLD && indicator) {
            // 已拉到閾值 → 重新整理
            indicator.querySelector(".dms-ptr-arrow").textContent = "↻";
            indicator.querySelector(".dms-ptr-label").textContent = "重新整理中…";
            setTimeout(function () {
                window.location.reload();
            }, 350);
        } else {
            hideIndicator();
        }

        startY   = null;
        pullDist = 0;
    }, { passive: true });
})();
