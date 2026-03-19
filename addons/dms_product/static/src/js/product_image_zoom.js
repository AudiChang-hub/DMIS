/** @odoo-module **/

/**
 * DMS 產品圖片點擊放大
 *
 * 使用委派事件監聽，點擊 [data-dms-expand-img] 元素時
 * 用 Odoo 16 Dialog 顯示大圖。
 */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, xml } from "@odoo/owl";

// ── 大圖對話框元件 ─────────────────────────────────────────────
class ProductImageDialog extends Component {
    static template = xml`
        <div class="dms-product-zoom-dialog">
            <img t-att-src="props.src"
                 t-att-alt="props.name"
                 class="dms-product-zoom-img"/>
            <p class="dms-product-zoom-title text-center mt8 text-muted">
                <t t-esc="props.name"/>
            </p>
        </div>
    `;
    static props = {
        src: String,
        name: { type: String, optional: true },
        close: { type: Function, optional: true },
    };
}

// ── Systray / 頁面層級的事件委派處理 ──────────────────────────────
registry.category("services").add("dms_product_image_zoom", {
    start(env) {
        /**
         * 委派到 document，捕捉任何出現在 DOM 中的
         * [data-dms-expand-img] 圖片點擊，開啟 Dialog。
         */
        document.addEventListener("click", async (ev) => {
            const target = ev.target.closest("[data-dms-expand-img]");
            if (!target) return;

            ev.stopPropagation();
            ev.preventDefault();

            const productId = parseInt(target.dataset.productId, 10);
            const productName = target.dataset.productName || "";

            if (!productId) return;

            // 組合大圖 URL（使用 Odoo image 路由，取 image_1920）
            const imgSrc =
                `/web/image/dms.product/${productId}/image_1920?unique=${Date.now()}`;

            env.services.dialog.add(ProductImageDialog, {
                src: imgSrc,
                name: productName,
            }, {
                title: productName || "產品圖片",
            });
        });
    },
});
