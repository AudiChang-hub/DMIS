/** @odoo-module **/

/**
 * DMS 行事曆假日標色
 * - 週日 + 國定假日／節日 → 紅色底色＋紅色數字
 * - 週六 → 綠色底色＋綠色數字
 * - 標籤：節日名稱 / 例假日（週日）/ 休假日（週六）
 *
 * 資料來源：dms.public.holiday（由台灣假日同步精靈匯入）
 */

import { patch } from "@web/core/utils/patch";
import { CalendarCommonRenderer } from "@web/views/calendar/calendar_common/calendar_common_renderer";
import { useService } from "@web/core/utils/hooks";
import { onWillStart } from "@odoo/owl";

// ── 模組層級快取（跨元件實例共用，頁面重新整理才清除） ─────────
/** @type {Map<string, string>}  key = 'YYYY-MM-DD', value = 假日名稱 */
const _cache = new Map();
/** @type {Set<number>} 已載入的年份 */
const _loadedYears = new Set();

/**
 * 從後端取得指定年份範圍的假日資料，存入模組快取。
 * @param {Function} rpc - Odoo rpc service
 * @param {number} fromYear
 * @param {number} toYear
 */
async function _loadHolidayRange(rpc, fromYear, toYear) {
    const missing = [];
    for (let y = fromYear; y <= toYear; y++) {
        if (!_loadedYears.has(y)) {
            missing.push(y);
        }
    }
    if (missing.length === 0) return;

    const minY = Math.min(...missing);
    const maxY = Math.max(...missing);
    try {
        const records = await rpc("/web/dataset/call_kw", {
            model: "dms.public.holiday",
            method: "search_read",
            args: [
                [
                    ["date", ">=", `${minY}-01-01`],
                    ["date", "<=", `${maxY}-12-31`],
                ],
            ],
            kwargs: { fields: ["date", "name"], limit: 2000 },
        });
        for (const rec of records) {
            _cache.set(rec.date, rec.name || "例假日");
        }
        for (const y of missing) {
            _loadedYears.add(y);
        }
    } catch (err) {
        console.error("[DMS] 假日資料載入失敗：", err);
    }
}

// ── 取得假日名稱分類 ─────────────────────────────────────────
/**
 * 回傳當日的 { label, colorClass }
 * @param {string} dateStr  'YYYY-MM-DD'
 * @param {number} weekday  luxon weekday (1=Mon...6=Sat, 7=Sun)
 */
function _getDayInfo(dateStr, weekday) {
    const isSat = weekday === 6;
    const isSun = weekday === 7;
    const inDb = _cache.has(dateStr);
    const dbName = inDb ? _cache.get(dateStr) : "";
    // 有命名節日（非純例假日標記）
    const isNamedHoliday = inDb && dbName !== "例假日";

    let colorClass = "";
    let label = "";

    if (isNamedHoliday || isSun) {
        colorClass = "dms-cal-red";
    } else if (isSat) {
        colorClass = "dms-cal-green";
    }

    if (isNamedHoliday) {
        label = dbName;           // 例：春節、國慶日、補假
    } else if (isSun) {
        label = "例假日";
    } else if (isSat) {
        label = "休假日";
    }

    return { colorClass, label };
}

// ── Patch CalendarCommonRenderer ──────────────────────────────
patch(CalendarCommonRenderer.prototype, "dms_visit.calendar_holiday_colors", {
    setup() {
        this._super(...arguments);

        const rpc = useService("rpc");

        onWillStart(async () => {
            const now = luxon.DateTime.now();
            // 預載前一年到後兩年（涵蓋大部分使用情境）
            await _loadHolidayRange(rpc, now.year - 1, now.year + 2);
        });
    },

    onDayRender(info) {
        // 先呼叫原始邏輯（處理 o_calendar_disabled 等）
        this._super(info);

        const el = info.el;
        const date = luxon.DateTime.fromJSDate(info.date);
        const dateStr = date.toISODate();           // 'YYYY-MM-DD'
        const weekday = date.weekday;               // 1=Mon … 6=Sat, 7=Sun

        const { colorClass, label } = _getDayInfo(dateStr, weekday);

        if (colorClass) {
            el.classList.add(colorClass);
        }

        if (label) {
            // 插入到 .fc-day-top 讓標籤緊貼日期數字
            const topEl = el.querySelector(".fc-day-top") || el;
            const span = document.createElement("span");
            span.className = "dms-cal-holiday-label";
            span.textContent = label;
            topEl.appendChild(span);
        }
    },
});
