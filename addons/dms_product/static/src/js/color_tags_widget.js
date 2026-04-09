/** @odoo-module **/

import { xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { CharField } from "@web/views/fields/char/char_field";

/**
 * 車色 Tags Widget
 *
 * 唯讀模式：將逗號/頓號分隔的車色字串拆成 chips 並排（自動換行）。
 * 編輯模式：顯示標準文字輸入框，可直接編輯「頓號分隔向色文字」。
 * 繼承 CharField 以取得 onChange / onInput / props.update 機制。
 */
class ColorTagsField extends CharField {
    static template = xml`
        <t t-if="props.readonly">
            <div class="o_dms_color_tags">
                <span
                    t-foreach="tags"
                    t-as="tag"
                    t-key="tag"
                    class="o_dms_color_tag"
                    t-esc="tag"
                />
            </div>
        </t>
        <t t-else="">
            <input
                class="o_input"
                t-att-id="props.id"
                type="text"
                t-att-value="props.value || ''"
                t-on-input="onInput"
                t-on-change="onChange"
            />
        </t>
    `;
    static props = { "*": { optional: true } };

    get tags() {
        const value = this.props.value || "";
        return value
            .split(/[、,，\/]+/)
            .map((s) => s.trim())
            .filter(Boolean);
    }
}

registry.category("fields").add("color_tags", ColorTagsField);
