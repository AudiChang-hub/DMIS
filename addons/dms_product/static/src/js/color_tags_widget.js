/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

/**
 * 車色 Tags Widget
 *
 * 將逗號/頓號分隔的車色字串拆成獨立 chip 並排顯示。
 * 使用於 sku_ids tree 的 color 欄位，超過欄寬時自動換行。
 *
 * Odoo 16 fields registry 直接存 class，不接受 descriptor object。
 */
class ColorTagsField extends Component {
    static template = "dms_product.ColorTagsField";
    // Odoo 16：以萬用 props 避免 prop validation 錯誤
    static props = {
        value: { optional: true },
        "*": { optional: true },
    };

    get tags() {
        const value = this.props.value || "";
        return value
            .split(/[、,，\/]+/)
            .map((s) => s.trim())
            .filter(Boolean);
    }
}

// Odoo 16：直接傳 class，不要傳 descriptor object
registry.category("fields").add("color_tags", ColorTagsField);
