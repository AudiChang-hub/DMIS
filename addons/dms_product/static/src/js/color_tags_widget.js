/** @odoo-module **/

import { Component, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";

/**
 * 車色 Tags Widget
 *
 * 將逗號/頓號分隔的車色字串拆成獨立 chip 並排顯示。
 * 使用於 sku_ids tree 的 color 欄位，超過欄寬時自動換行。
 *
 * Template 直接內嵌（xml tagged literal），避免外部 XML 載入時序問題。
 * Odoo 16 fields registry 直接存 class，不接受 descriptor object。
 */
class ColorTagsField extends Component {
    static template = xml`
        <div class="o_dms_color_tags">
            <span
                t-foreach="tags"
                t-as="tag"
                t-key="tag"
                class="o_dms_color_tag"
                t-esc="tag"
            />
        </div>
    `;
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
