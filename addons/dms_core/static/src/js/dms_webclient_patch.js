/** @odoo-module **/
/**
 * dms_webclient_patch.js
 *
 * 目的：覆寫 Odoo 16 WebClient 的 zopenerp title 部分，
 *       將瀏覽器分頁標題前綴從 "Odoo" 改為 "DMIS-經營管理系統"。
 *
 * 根本原因：webclient.js:36 硬編碼 this.title.setParts({ zopenerp: "Odoo" })
 */

import { patch } from "@web/core/utils/patch";
import { WebClient } from "@web/webclient/webclient";

patch(WebClient.prototype, "dms_core.WebClientTitlePatch", {
    setup() {
        this._super(...arguments);
        this.title.setParts({ zopenerp: "DMIS-經營管理系統" });
    },
});
