/** @odoo-module **/
/**
 * pricelist_create_button.js
 *
 * Patch ListController.onClickCreate：
 * 當 list view 含有 dms_pricelist_tree class（即價格表）時，
 * 攔截「新增」按鈕，改為開啟 wizard 彈窗。
 * 其他 list view 維持原有行為不受影響。
 */

import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";

const WIZARD_XMLID = "dms_product.action_product_create_wizard";

patch(ListController.prototype, "dms_product.pricelist_create_wizard", {
    async onClickCreate() {
        // 只在含有 dms_pricelist_tree 的 list view 攔截
        const isPricelist = this.el && this.el.querySelector(".dms_pricelist_tree");
        if (!isPricelist) {
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

