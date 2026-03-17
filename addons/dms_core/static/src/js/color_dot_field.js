/** @odoo-module **/
/**
 * color_dot_field.js
 * 自訂 OWL 欄位 widget：彩色圓點標色
 *
 * 用途：dms.dealer 的 color_tag 欄位
 * - 列表視圖（readonly）：顯示單一彩色圓點 + tooltip
 * - 表單視圖（editable）：顯示調色盤，點選即可換色
 *
 * 色碼規則（與 LINE 群組管理慣例對齊）：
 *   yellow → 黃・三陽專賣（自家三陽專賣）
 *   blue   → 藍・台鈴（自家台鈴專賣 / 只發台鈴價格表）
 *   pink   → 粉・三陽（只發三陽價格表）
 *   gray   → 灰・其他
 */

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

const OPTIONS = [
    { value: "yellow", label: "黃・三陽專賣" },
    { value: "blue",   label: "藍・台鈴" },
    { value: "pink",   label: "粉・三陽" },
    { value: "gray",   label: "灰・其他" },
];

const LABEL_MAP = Object.fromEntries(OPTIONS.map((o) => [o.value, o.label]));

export class ColorDotField extends Component {
    static template = "dms_core.ColorDotField";
    static props = {
        ...standardFieldProps,
    };

    /** 目前值對應的中文說明（用於 tooltip） */
    get colorLabel() {
        return LABEL_MAP[this.props.value] || "灰・其他";
    }

    /** 調色盤選項 */
    get options() {
        return OPTIONS;
    }

    /** 使用者點選新顏色時更新欄位 */
    onChange(ev) {
        this.props.update(ev.target.value);
    }
}

registry.category("fields").add("dms_color_dot", ColorDotField);
