/** @odoo-module **/

/**
 * DMS 產品圖片點擊放大
 *
 * 使用委派事件監聽，點擊 [data-dms-expand-img] 元素時
 * 用 Odoo 16 Dialog 顯示大圖。
 *
 * 支援的 data 屬性：
 *   data-model       — Odoo model 名稱（如 dms.product 或 dms.product.color）
 *   data-record-id   — 記錄 ID
 *   data-product-name — 顯示用名稱
 *
 * 舊版相容：
 *   data-product-id  — 等同 data-record-id（model 預設為 dms.product）
 */

import { registry } from "@web/core/registry";
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
        document.addEventListener("click", async (ev) => {
            const target = ev.target.closest("[data-dms-expand-img]");
            if (!target) return;

            ev.stopPropagation();
            ev.preventDefault();

            // 支援 data-model + data-record-id（新格式）
            // 也支援舊的 data-product-id（當 model 為 dms.product 時）
            const model = target.dataset.model || "dms.product";
            const recordId = parseInt(
                target.dataset.recordId || target.dataset.productId, 10
            );
            const displayName = target.dataset.productName || "";

            if (!recordId) return;

            const imgSrc =
                `/web/image/${model}/${recordId}/image_1920?unique=${Date.now()}`;

            env.services.dialog.add(ProductImageDialog, {
                src: imgSrc,
                name: displayName,
            }, {
                title: displayName || "產品圖片",
            });
        });
    },
});
