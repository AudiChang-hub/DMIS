/** @odoo-module **/

import { xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { CharField } from "@web/views/fields/char/char_field";

/**
 * 車色 Tags Widget
 *
 * 唯讀模式：chips 並排換行。
 * 編輯模式：標準文字輸入框（t-ref="input" 讓 useInputField hook 自動
 *   處理所有事件，不需手動定義 onInput / onChange）。
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
                t-att-placeholder="props.placeholder"
                t-ref="input"
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
