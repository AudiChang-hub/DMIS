/** @odoo-module **/

/**
 * 價格表凍結：標題列（垂直）＋ 機種欄（水平）
 *
 * 設計原則：
 *  - 不 patch OWL 元件，改用 MutationObserver 監聽 DOM 變化
 *  - 透過 th[data-name="name"] 定位「機種」欄，不依賴固定 nth-child
 *  - getBoundingClientRect() 取得實際渲染寬度，不硬寫死 px 值
 *  - dataset.stickyKey 記錄已處理狀態，避免重複計算
 */

let _rafId = null;

function scheduleApply() {
    if (_rafId) return;
    _rafId = requestAnimationFrame(() => {
        _rafId = null;
        applySticky();
    });
}

function applySticky() {
    const containers = document.querySelectorAll(".dms_pricelist_tree");
    containers.forEach((container) => {
        const table = container.querySelector("table.o_list_table");
        if (!table) return;

        /* 修正 border-collapse（CSS spec：collapse 模式下 sticky 對 td/th 無效） */
        /* table-layout:fixed + width:100% 由 CSS 設定，JS 確保不被覆寫 */
        table.style.borderCollapse = "separate";
        table.style.borderSpacing = "0";
        table.style.tableLayout = "auto";
        table.style.width = "100%";

        const headerRow = table.querySelector("thead tr:first-child");
        if (!headerRow) return;

        const headers = Array.from(headerRow.querySelectorAll("th"));

        /* 凍結標題列（sticky top），每次都重新設定以防重新渲染後遺失 */
        headers.forEach((th) => {
            th.style.top = "0";
            th.style.position = "sticky";
            /* 不設定 backgroundColor，讓 dms_theme.scss 的藍色生效 */
            /* 預設 z-index，水平凍結欄會再往上蓋 */
            if (!th.classList.contains("o_sticky_col")) {
                th.style.zIndex = "4";
            }
        });

        /* 定位「機種」欄（th 有 data-name="name" 屬性） */
        const nameColIdx = headers.findIndex((th) => th.dataset.name === "name");
        if (nameColIdx === -1) return;

        /* 等待元素實際渲染後取得寬度（fixed layout 用 offsetWidth 更準確） */
        const firstColWidth = headers[0].offsetWidth;
        if (firstColWidth === 0) {
            setTimeout(scheduleApply, 150);
            return;
        }

        /* 欄位數量改變（切換可選欄位）時，強制清除 key 觸發重算 */
        const prevColCount = parseInt(container.dataset.stickyColCount || "0", 10);
        if (prevColCount !== headers.length) {
            container.dataset.stickyKey = "";
        }
        container.dataset.stickyColCount = headers.length;

        /* 以各欄寬度生成 key，避免重複計算 */
        const colKey = headers
            .slice(0, nameColIdx + 1)
            .map((th, i) => `${i}:${Math.round(th.offsetWidth)}`)
            .join(",");
        if (container.dataset.stickyKey === colKey) return;
        container.dataset.stickyKey = colKey;

        /* 清除舊的 sticky class */
        container.querySelectorAll(".o_sticky_col,.o_sticky_border").forEach((el) => {
            el.classList.remove("o_sticky_col", "o_sticky_border");
            el.style.removeProperty("left");
            el.style.removeProperty("box-shadow");
        });

        /* 套用水平凍結（checkbox → 機種欄） */
        let cumLeft = 0;
        for (let i = 0; i <= nameColIdx; i++) {
            const isLast = i === nameColIdx;
            const left = cumLeft;
            cumLeft += headers[i].offsetWidth;

            /* 標題欄 */
            const th = headers[i];
            th.classList.add("o_sticky_col");
            th.style.left = left + "px";
            th.style.zIndex = "6";
            if (isLast) th.classList.add("o_sticky_border");

            /* 資料欄（tbody & tfoot） */
            table
                .querySelectorAll(
                    `tbody tr > td:nth-child(${i + 1}), tfoot tr > td:nth-child(${i + 1})`
                )
                .forEach((td) => {
                    td.classList.add("o_sticky_col");
                    td.style.left = left + "px";
                    td.style.position = "sticky";
                    td.style.zIndex = "3";
                    if (isLast) td.classList.add("o_sticky_border");
                });
        }
    });
}

/* MutationObserver：監聽 pricelist 載入與重新渲染 */
const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
        for (const node of m.addedNodes) {
            if (node.nodeType !== 1) continue;
            if (
                node.classList?.contains("dms_pricelist_tree") ||
                node.classList?.contains("o_list_table") ||
                node.querySelector?.(".dms_pricelist_tree")
            ) {
                scheduleApply();
                return;
            }
        }
    }
});

function startObserver() {
    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
        scheduleApply();
    } else {
        document.addEventListener("DOMContentLoaded", () => {
            observer.observe(document.body, { childList: true, subtree: true });
            scheduleApply();
        });
    }
}

startObserver();

