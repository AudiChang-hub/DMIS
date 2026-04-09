/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * 車色 Tags Widget
 *
 * 將逗號/頓號分隔的車色字串拆成獨立 chip 並排顯示。
 * 使用於 sku_ids tree 的 color 欄位，超過欄寬時自動換行。
 */
class ColorTagsField extends Component {
    static template = "dms_product.ColorTagsField";
    static props = { ...standardFieldProps };

    get tags() {
        const value = this.props.value || "";
        return value
            .split(/[、,，\/]+/)
            .map((s) => s.trim())
            .filter(Boolean);
    }
}

registry.category("fields").add("color_tags", {
    component: ColorTagsField,
    supportedTypes: ["char"],
});
