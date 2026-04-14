/** @odoo-module **/
/**
 * RocDateField：繼承 Odoo DateField，唯讀模式顯示民國年格式。
 * 編輯模式維持原生日期選擇器（西元年），選完後唯讀顯示自動轉換為民國年。
 */
import { DateField } from "@web/views/fields/date/date_field";
import { registry } from "@web/core/registry";

export class RocDateField extends DateField {
    /** 覆寫唯讀顯示：將西元年轉為民國年 */
    get formattedValue() {
        const val = this.props.value;
        if (!val) return "";
        const rocYear = val.year - 1911;
        const m = String(val.month).padStart(2, "0");
        const d = String(val.day).padStart(2, "0");
        return `民國${rocYear}年${m}月${d}日`;
    }
}

registry.category("fields").add("roc_date", RocDateField);
