/** @odoo-module **/

/**
 * DMS 產品圖片 Gallery Widget
 *
 * 使用方式（form view XML）：
 *   <widget name="dms_product_gallery"/>
 *
 * 讀取 record.data.color_ids，展示 Shopee 風格的主圖 + 縮圖列 + 左右切換。
 * 主圖採用 image_1920（原始尺寸，無壓縮）。
 */

import { registry } from "@web/core/registry";
import { Component, useState, xml } from "@odoo/owl";

class DmsProductGallery extends Component {
    static template = xml`
<div class="dms-gallery">
    <t t-if="records.length">

        <!-- 主圖區 -->
        <div class="dms-gallery-stage">
            <button t-if="records.length > 1"
                    class="dms-gallery-nav dms-gallery-prev"
                    t-on-click="prev">
                <i class="fa fa-angle-left"/>
            </button>

            <div class="dms-gallery-main">
                <img t-att-src="mainSrc"
                     t-att-alt="currentName"
                     class="dms-gallery-main-img"/>
            </div>

            <button t-if="records.length > 1"
                    class="dms-gallery-nav dms-gallery-next"
                    t-on-click="next">
                <i class="fa fa-angle-right"/>
            </button>
        </div>

        <!-- 顏色名稱 -->
        <div class="dms-gallery-caption" t-if="currentName">
            <t t-esc="currentName"/>
        </div>

        <!-- 縮圖列 -->
        <div t-if="records.length > 1" class="dms-gallery-thumbs">
            <t t-foreach="records" t-as="rec" t-key="rec_index">
                <div t-att-class="thumbClass(rec_index)"
                     t-on-click="() => this.select(rec_index)">
                    <img t-att-src="thumbSrc(rec)"
                         t-att-alt="rec.data.name || ''"/>
                </div>
            </t>
        </div>

    </t>
    <t t-else="">
        <div class="dms-gallery-empty">
            <i class="fa fa-image"/>
            <p>尚未新增圖片，請切換到「圖片集」頁籤上傳後儲存。</p>
        </div>
    </t>
</div>
    `;

    setup() {
        this.state = useState({ idx: 0 });
    }

    get records() {
        const colorIds = this.props.record?.data?.color_ids;
        if (!colorIds) return [];
        return (colorIds.records || []).filter(r => r.data.active !== false);
    }

    get current() {
        return this.records[this.state.idx] || this.records[0] || null;
    }

    get mainSrc() {
        const rec = this.current;
        if (!rec) return '/web/static/img/placeholder.png';
        if (rec.resId) {
            return `/web/image/dms.product.color/${rec.resId}/image_1920`;
        }
        // 未儲存的新記錄：嘗試讀取 binary data
        const b64 = rec.data.image_1920 || rec.data.image_512 || rec.data.image_128;
        return b64 ? `data:image/*;base64,${b64}` : '/web/static/img/placeholder.png';
    }

    get currentName() {
        return this.current?.data?.name || '';
    }

    thumbSrc(rec) {
        if (rec.resId) {
            return `/web/image/dms.product.color/${rec.resId}/image_128`;
        }
        const b64 = rec.data.image_128;
        return b64 ? `data:image/*;base64,${b64}` : '/web/static/img/placeholder.png';
    }

    thumbClass(idx) {
        return 'dms-gallery-thumb' + (idx === this.state.idx ? ' active' : '');
    }

    select(idx) {
        this.state.idx = idx;
    }

    prev() {
        const len = this.records.length;
        if (!len) return;
        this.state.idx = (this.state.idx - 1 + len) % len;
    }

    next() {
        const len = this.records.length;
        if (!len) return;
        this.state.idx = (this.state.idx + 1) % len;
    }
}

registry.category("view_widgets").add("dms_product_gallery", {
    component: DmsProductGallery,
});
