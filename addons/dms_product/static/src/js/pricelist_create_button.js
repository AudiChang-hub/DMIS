/** @odoo-module **/
/**
 * pricelist_create_button.js
 *
 * Patch ListController.onClickCreate：
 * 當 list view 的 arch class 含有 dms_pricelist_tree 時（即價格表），
 * 攔截「新增」按鈕，改為開啟 wizard 彈窗。
 * 其他 list view 維持原有行為不受影響。
 */

import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";

const WIZARD_XMLID = "dms_product.action_product_create_wizard";

patch(ListController.prototype, "dms_product.pricelist_create_wizard", {
    async onClickCreate() {
        // 方法 1：從 props.archInfo 或 props.info 取 arch className（最可靠）
        const archClass =
            this.props?.archInfo?.className ||
            this.props?.info?.arch?.getAttribute?.("class") ||
            "";
        // 方法 2：備援，從 DOM 找（class 可能在 el 本身或子節點）
        const el = this.el;
        const domHasClass =
            el &&
            (el.classList.contains("dms_pricelist_tree") ||
                !!el.querySelector(".dms_pricelist_tree"));

        const isPricelist =
            archClass.includes("dms_pricelist_tree") || domHasClass;

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

