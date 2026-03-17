/** @odoo-module **/
/**
 * color_dot_field.js
 * 自訂 OWL 欄位 widget：彩色圓點（LINE 群組大頭貼顏色）
 *
 * - 列表視圖（readonly）：顯示單一彩色圓點 + tooltip
 * - 表單視圖（editable）：圓點預覽 + 下拉式選單
 */

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

const OPTIONS = [
    { value: "yellow", label: "黃" },
    { value: "blue",   label: "藍" },
    { value: "pink",   label: "粉" },
    { value: "gray",   label: "灰" },
];

const LABEL_MAP = Object.fromEntries(OPTIONS.map((o) => [o.value, o.label]));

export class ColorDotField extends Component {
    static template = "dms_core.ColorDotField";
    static props = {
        ...standardFieldProps,
    };

    /** 目前值對應的顏色名稱（用於 tooltip） */
    get colorLabel() {
        return LABEL_MAP[this.props.value] || "灰";
    }

    /** 下拉選單選項 */
    get options() {
        return OPTIONS;
    }

    /** 使用者選擇新顏色時更新欄位 */
    onChange(ev) {
        this.props.update(ev.target.value);
    }
}

registry.category("fields").add("dms_color_dot", ColorDotField);
