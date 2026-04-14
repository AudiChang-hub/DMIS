/** @odoo-module **/
/**
 * pricelist_create_button.js
 *
 * 針對價格表（dms_pricelist_tree）的 List View：
 * 1. 攔截工具列「新增」按鈕（.o_list_button_add），改為開啟 wizard 彈窗
 * 2. 攔截 editable tree 底部「新增一列」按鈕（.o_field_one2many .o_list_record_add 或 td.o_list_add），
 *    同樣導向 wizard
 * 彈窗關閉後重新整理清單。
 */

const WIZARD_ACTION_XMLID = "dms_product.action_product_create_wizard";

// 儲存已綁定過的按鈕，避免重複綁定
const _bound = new WeakSet();

function getOdooEnv() {
    const webClient = document.querySelector(".o_web_client");
    if (!webClient || !webClient.__owl__) return null;
    // 往上走 component tree 找含有 env 的 node
    let comp = webClient.__owl__;
    while (comp && !comp.component?.env) {
        comp = comp.parent;
    }
    return comp?.component?.env || null;
}

function openWizard() {
    const env = getOdooEnv();
    if (!env) return;
    env.services.action
        .loadAction(WIZARD_ACTION_XMLID)
        .then((action) => {
            return env.services.action.doAction(action, {
                onClose: () => {
                    env.services.action.doAction(
                        { type: "ir.actions.client", tag: "reload" },
                        { clearBreadcrumbs: false }
                    );
                },
            });
        });
}

function makePricelistInterceptor(btn) {
    if (_bound.has(btn)) return;
    _bound.add(btn);
    btn.addEventListener(
        "click",
        (e) => {
            // 確認目前頁面有 dms_pricelist_tree
            if (!document.querySelector(".dms_pricelist_tree")) return;
            e.preventDefault();
            e.stopPropagation();
            openWizard();
        },
        true
    );
}

function attachCreateInterceptor() {
    if (!document.querySelector(".dms_pricelist_tree")) return;

    // 1. 工具列「新增」按鈕
    document.querySelectorAll(".o_list_button_add").forEach(makePricelistInterceptor);

    // 2. editable tree 底部「新增一列」— Odoo 16 渲染為 <tr class="o_list_add_optional ..."> 內的 <td>
    //    或 <a class="o_list_record_add">
    document.querySelectorAll(
        ".dms_pricelist_tree .o_list_record_add, " +
        ".dms_pricelist_tree td.o_list_add_optional"
    ).forEach(makePricelistInterceptor);
}

// MutationObserver 監聽 DOM 變化
const observer = new MutationObserver(() => {
    attachCreateInterceptor();
});

observer.observe(document.body, { childList: true, subtree: true });

// 初始執行
attachCreateInterceptor();

