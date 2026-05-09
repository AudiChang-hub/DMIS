/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const { Component, useState, useRef, onMounted, onWillUnmount } = owl;

const DEFAULT_METABASE_BASE_URL = "/metabase";

let cachedMetabaseBaseUrl = null;
let pendingMetabaseBaseUrlRequest = null;


function buildDashboardUrl(baseUrl, uuid) {
    return `${baseUrl}/public/dashboard/${uuid}#bordered=false&titled=true`;
}


async function resolveMetabaseBaseUrl(rpc) {
    if (cachedMetabaseBaseUrl) {
        return cachedMetabaseBaseUrl;
    }
    if (!pendingMetabaseBaseUrlRequest) {
        pendingMetabaseBaseUrlRequest = rpc("/dms_report_ds/metabase_config", {})
            .then((result) => (result && result.base_url) || DEFAULT_METABASE_BASE_URL)
            .catch(() => DEFAULT_METABASE_BASE_URL)
            .then((baseUrl) => {
                cachedMetabaseBaseUrl = baseUrl || DEFAULT_METABASE_BASE_URL;
                return cachedMetabaseBaseUrl;
            })
            .finally(() => {
                pendingMetabaseBaseUrlRequest = null;
            });
    }
    return pendingMetabaseBaseUrlRequest;
}

export class MetabaseDashboard extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.state = useState({ url: "", loading: true });
        this.iframeRef = useRef("metabaseIframe");
        this.actionManagerEl = null;

        const uuid = this.props.action.params && this.props.action.params.dashboard_uuid;
        if (!uuid) {
            this.state.loading = false;
            return;
        }

        // 先用預設代理路徑立即啟動 iframe，避免每次都被設定 RPC 阻塞。
        this.state.url = buildDashboardUrl(DEFAULT_METABASE_BASE_URL, uuid);
        this.state.loading = false;

        this.refreshConfiguredUrl(uuid);

        onMounted(() => {
            const actionManager = this.el && this.el.closest(".o_action_manager");
            if (actionManager) {
                this.actionManagerEl = actionManager;
                this.actionManagerEl.classList.add("o_metabase_action_manager");
            }
        });

        onWillUnmount(() => {
            if (this.actionManagerEl) {
                this.actionManagerEl.classList.remove("o_metabase_action_manager");
                this.actionManagerEl = null;
            }
        });
    }

    async refreshConfiguredUrl(uuid) {
        const baseUrl = await resolveMetabaseBaseUrl(this.rpc);
        const resolvedUrl = buildDashboardUrl(baseUrl, uuid);
        if (resolvedUrl !== this.state.url) {
            this.state.url = resolvedUrl;
        }
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
