/** @odoo-module **/
/**
 * dms_customer_column_limit.js
 * 客戶列表欄位顯示上限（15 欄硬限制）
 *
 * 說明：
 *  - Patch ListRenderer.prototype.toggleOptionalField
 *  - 僅對 dms_customer 模組所使用的 res.partner list view 生效
 *  - 當使用者嘗試勾選第 16 個欄位時：阻止切換並顯示 warning notification
 *  - 取消勾選（隱藏欄位）永遠允許，不受限制
 */

import { ListRenderer } from "@web/views/list/list_renderer";
import { patch } from "@web/core/utils/patch";

const DMS_CUSTOMER_MODEL = "res.partner";
const MAX_VISIBLE_COLUMNS = 15;

patch(ListRenderer.prototype, "dms_customer.partnerColumnLimit", {
    async toggleOptionalField(fieldName) {
        // 僅限 res.partner list view
        if (this.props?.list?.resModel !== DMS_CUSTOMER_MODEL) {
            return this._super(fieldName);
        }

        // turningOn = true 代表此次操作是「要顯示該欄位」
        const turningOn = !this.optionalActiveFields[fieldName];

        if (turningOn) {
            // 計算目前已顯示的 optional 欄位數
            const visibleCount = Object.values(this.optionalActiveFields).filter(
                Boolean
            ).length;

            if (visibleCount >= MAX_VISIBLE_COLUMNS) {
                this.env.services.notification.add(
                    "列表最多只能顯示 15 個欄位，請先取消勾選其他欄位再新增。",
                    {
                        title: "欄位顯示上限",
                        type: "warning",
                        sticky: false,
                    }
                );
                // 強制觸發 OWL 重新渲染，確保 dropdown checkbox 回復未勾選狀態
                this.state.columns = [...this.state.columns];
                // 阻止切換：不呼叫 _super，optionalActiveFields 維持不變
                return;
            }
        }

        // 未超過上限（或是取消勾選）：正常執行原始邏輯
        return this._super(fieldName);
    },
});
