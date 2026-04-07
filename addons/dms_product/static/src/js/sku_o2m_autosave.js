/** @odoo-module **/

import { X2ManyField } from "@web/views/fields/x2many/x2many_field";
import { registry } from "@web/core/registry";

/**
 * 針對「產品模板 → 產品項」O2M 的自訂 Widget。
 *
 * 使用情境：在「尚未儲存的全新產品模板」頁面新增產品項時，
 * Odoo 標準行為下 context 的 default_template_id 會是 False，
 * 導致對話框無法帶入模板。
 *
 * 本 Widget 在 onAdd() 中判斷父記錄是否尚未儲存（isNew），
 * 若是則先自動儲存父記錄，再開啟新增對話框。
 * 若儲存失敗（必填欄位未填），原生紅框提示已顯示，不開啟對話框。
 *
 * 注意：Odoo 16 的 fields registry 登錄的值直接是 class 本身，
 * 不存在 x2ManyField descriptor object，因此不可使用 spread。
 */
export class SkuO2MField extends X2ManyField {
    async onAdd(params) {
        const record = this.props.record;
        if (record && record.isNew) {
            const saved = await record.save();
            if (!saved) {
                // 儲存失敗（例如必填欄位未填）：原生驗證提示已顯示，中止開啟對話框
                return;
            }
        }
        return super.onAdd(params);
    }
}

// Odoo 16：fields registry 的值直接是 class，不是 descriptor object
registry.category("fields").add("sku_o2m", SkuO2MField);
