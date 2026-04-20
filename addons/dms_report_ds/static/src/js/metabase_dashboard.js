/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const { Component, useState, onWillStart, useRef } = owl;

export class MetabaseDashboard extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.state = useState({ url: "", loading: true });
        this.iframeRef = useRef("metabaseIframe");

        onWillStart(async () => {
            const uuid = this.props.action.params && this.props.action.params.dashboard_uuid;
            if (!uuid) {
                this.state.loading = false;
                return;
            }
            let baseUrl = "";
            try {
                const result = await this.rpc("/dms_report_ds/metabase_config", {});
                baseUrl = (result && result.base_url) || "";
            } catch (_e) {
                // ignore – use fallback
            }
            if (!baseUrl) {
                // 預設：使用 Odoo 反向代理，避免暴露 Metabase 公開 URL
                baseUrl = "/metabase";
            }
            this.state.url =
                baseUrl + "/public/dashboard/" + uuid + "#bordered=false&titled=true";
            this.state.loading = false;
        });
    }

    resetDashboard() {
        const iframe = this.iframeRef.el;
        if (iframe) {
            iframe.src = this.state.url;
        }
    }
}

MetabaseDashboard.template = "dms_report_ds.MetabaseDashboard";

registry.category("actions").add("metabase_dashboard", MetabaseDashboard);
