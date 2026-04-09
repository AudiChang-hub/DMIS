/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";
import { X2ManyField } from "@web/views/fields/x2many/x2many_field";
import { registry } from "@web/core/registry";

/**
 * 自訂 ListRenderer：攔截 Enter 鍵在最後一列時的「自動新增列」行為。
 * 使用者需明確點選「Add a line」才能新增產品項。
 */
class SkuListRenderer extends ListRenderer {
    onCellKeydownEditMode(hotkey, cell, group, record) {
        if (hotkey === "enter") {
            const { list } = this.props;
            const index = list.records.indexOf(record);
            const nextRecord = list.records[index + 1];
            if (!nextRecord) {
                // 最後一列：循環回第一列，不觸發新增
                const firstRecord = list.records.at(0);
                if (firstRecord && firstRecord !== record) {
                    this.cellToFocus = { forward: true, record: firstRecord };
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
 * 使用情境 1：在「尚未儲存的全新產品模板」頁面新增產品項時，
 * Odoo 標準行為下 context 的 default_template_id 會是 False，
 * 導致對話框無法帶入模板。本 Widget 在 onAdd() 中先自動儲存父記錄。
 *
 * 使用情境 2：dialog 按下「Save & Close / Save & New」後，
 * Odoo 只把子記錄加進父表單的記憶體暫存；真正的 server create()
 * 要等父頁面存檔才觸發，因此 internal_code 不會即時產生。
 * 本 Widget 在 dialog 關閉後自動幫使用者存父頁面，
 * 讓 server create() 立即執行並產生 internal_code。
 *
 * 使用情境 3：Enter 鍵不在最後一列自動新增列，
 * 使用者須明確點選「Add a line」才能新增。
 */
export class SkuO2MField extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        ListRenderer: SkuListRenderer,
    };

    async onAdd(params) {
        const record = this.props.record;

        // ── 情境 1：全新模板尚未存檔，先存父記錄確保 template_id 有真實 ID ──
        if (record && record.isNew) {
            const saved = await record.save();
            if (!saved) {
                // 儲存失敗（必填欄位未填）：原生紅框提示已顯示，中止
                return;
            }
        }

        // 開啟 dialog（使用者填完後點 Save & Close 或 Save & New）
        await super.onAdd(params);

        // ── 情境 2：dialog 關閉後自動存父頁面，觸發 server create() ──
        // 如此 internal_code 會立即由後端生成並回填到畫面
        if (record && record.dirty) {
            await record.save();
        }
    }
}

// Odoo 16：fields registry 的值直接是 class，不是 descriptor object
registry.category("fields").add("sku_o2m", SkuO2MField);
