/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const { Component, useState, onWillStart } = owl;

export class MetabaseDashboard extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.state = useState({ url: "", loading: true });

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
                baseUrl =
                    window.location.protocol + "//" + window.location.hostname + ":3000";
            }
            this.state.url =
                baseUrl + "/public/dashboard/" + uuid + "#bordered=false&titled=false";
            this.state.loading = false;
        });
    }
}

MetabaseDashboard.template = "dms_report_ds.MetabaseDashboard";

registry.category("actions").add("metabase_dashboard", MetabaseDashboard);
