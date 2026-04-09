/** @odoo-module **/

import { FloatField } from "@web/views/fields/float/float_field";
import { registry } from "@web/core/registry";

/**
 * 與標準 FloatField 相同，但讀取模式下值為 0 時顯示空白（不顯示 "0"）。
 * 編輯模式下仍正常顯示 0，使用者可直接輸入新值。
 */
class FloatBlankZero extends FloatField {
    get formattedValue() {
        if (!this.props.value) return "";
        return super.formattedValue;
    }
}

registry.category("fields").add("float_blank_zero", FloatBlankZero);
