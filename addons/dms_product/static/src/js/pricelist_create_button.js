/** @odoo-module **/
/**
 * pricelist_create_button.js
 *
 * Patch ListController.onClickCreate：
 * 當目前 list view 的 resModel 為 dms.product 時，
 * 攔截「新增」按鈕，改為開啟 wizard 彈窗。
 * 其他 list view 維持原有行為不受影響。
 */

import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";

const WIZARD_XMLID = "dms_product.action_product_create_wizard";
const TARGET_MODEL = "dms.product";

patch(ListController.prototype, "dms_product.pricelist_create_wizard", {
    async onClickCreate() {
        // 最可靠：直接判斷 model 名稱
        const resModel =
            this.model?.root?.resModel ||
            this.props?.resModel ||
            this.props?.model?.root?.resModel;

        if (resModel !== TARGET_MODEL) {
            return this._super(...arguments);
        }

        await this.env.services.action.doAction(WIZARD_XMLID, {
            onClose: async () => {
                await this.model.load();
                this.render(true);
            },
        });
    },
});

