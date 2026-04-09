/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";
import { X2ManyField } from "@web/views/fields/x2many/x2many_field";
import { registry } from "@web/core/registry";

/**
 * 自訂 ListRenderer：在最後一列按下 Enter 時不新增列，
 * 改為跳回第一列。使用者須點選「Add a line」才能新增產品項。
 */
class SkuListRenderer extends ListRenderer {
    onCellKeydownEditMode(hotkey, cell, group, record) {
        if (hotkey === "enter") {
            const { list } = this.props;
            const index = list.records.indexOf(record);
            if (index === list.records.length - 1) {
                // 最後一列：跳回第一列而不新增
                const firstRecord = list.records[0];
                if (firstRecord && firstRecord !== record) {
                    firstRecord.switchMode("edit", { checkValidity: true });
                }
                return true;
            }
        }
        return super.onCellKeydownEditMode(...arguments);
    }
}

/**
 * 針對「產品模板 → 產品項」O2M 的自訂 Widget。
 *
 * 使用 SkuListRenderer 讓 Enter 鍵在最後一列時不自動新增列。
 * 產品項現為 inline editable，不再需要 dialog auto-save 邏輯。
 */
export class SkuO2MField extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        ListRenderer: SkuListRenderer,
    };

    async onAdd(params) {
        await super.onAdd(params);
    }
}

registry.category("fields").add("sku_o2m", SkuO2MField);
