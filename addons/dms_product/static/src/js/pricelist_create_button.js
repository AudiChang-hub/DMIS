/** @odoo-module **/
/**
 * pricelist_create_button.js
 *
 * 針對價格表（dms_pricelist_tree）的 List View，
 * 攔截工具列「新增」按鈕，改為開啟 wizard 彈窗（target=new）。
 * 彈窗關閉後重新整理清單。
 *
 * 實作方式：MutationObserver 監聽「新增」按鈕出現，套用 click 攔截，
 * 避免 patch OWL 元件而造成全局副作用。
 */

import { registry } from "@web/core/registry";

const WIZARD_ACTION_XMLID = "dms_product.action_product_create_wizard";

// 儲存已綁定過的按鈕，避免重複綁定
const _bound = new WeakSet();

function attachCreateInterceptor() {
    // 只在含有 dms_pricelist_tree 的頁面下作業
    const pricelist = document.querySelector(".dms_pricelist_tree");
    if (!pricelist) return;

    // 找到工具列中的「新增」按鈕（Odoo 16 class: o_list_button_add）
    const btns = document.querySelectorAll(".o_list_button_add");
    btns.forEach((btn) => {
        if (_bound.has(btn)) return;
        _bound.add(btn);

        btn.addEventListener(
            "click",
            (e) => {
                // 只在 dms_pricelist_tree 可見時攔截
                if (!document.querySelector(".dms_pricelist_tree")) return;

                e.preventDefault();
                e.stopPropagation();

                // 取得 Odoo env（透過 __owl__ 或 o_web_client）
                const webClient = document.querySelector(".o_web_client");
                if (!webClient || !webClient.__owl__) return;

                // 往上走 component tree 找含有 env 的 node
                let comp = webClient.__owl__;
                while (comp && !comp.component?.env) {
                    comp = comp.parent;
                }
                const env = comp?.component?.env;
                if (!env) return;

                // 執行 wizard action（target: new = dialog）
                env.services.action
                    .loadAction(WIZARD_ACTION_XMLID)
                    .then((action) => {
                        return env.services.action.doAction(action, {
                            onClose: () => {
                                // 關閉後重整清單
                                env.services.action.doAction(
                                    { type: "ir.actions.client", tag: "reload" },
                                    { clearBreadcrumbs: false }
                                );
                            },
                        });
                    });
            },
            true // capture phase，優先於 Odoo 原生 handler
        );
    });
}

// MutationObserver 監聽工具列按鈕出現
const observer = new MutationObserver(() => {
    attachCreateInterceptor();
});

observer.observe(document.body, { childList: true, subtree: true });

// 初始執行
attachCreateInterceptor();
