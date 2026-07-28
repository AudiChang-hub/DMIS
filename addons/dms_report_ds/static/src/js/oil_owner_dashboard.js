/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const { Component, useState, onWillStart } = owl;

const GENDER_COLORS = ["#6f3bd9", "#b89af4", "#9aa3af"];
const AGE_COLORS = ["#ede7ff", "#6f3bd9", "#7141d8", "#7648d7", "#7b51d6", "#8461d7", "#9274de"];

function percent(count, total) {
    if (!total) {
        return 0;
    }
    return Math.round((count * 1000) / total) / 10;
}

function formatPercent(value) {
    return `${value.toFixed(1)}%`;
}

export class OilOwnerDashboard extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.state = useState({
            loading: true,
            openDropdown: "",
            total: 0,
            genders: [],
            ages: [],
            options: { license_yms: [], models: [], regions: [], age_buckets: [] },
            filters: { license_yms: [], models: [], regions: [], age_buckets: [] },
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.loading = true;
        const result = await this.rpc("/dms_report_ds/oil_owner_dashboard_data", {
            license_yms: this.state.filters.license_yms,
            models: this.state.filters.models,
            regions: this.state.filters.regions,
            age_buckets: this.state.filters.age_buckets,
        });
        this.state.total = result.total || 0;
        this.state.genders = result.genders || [];
        this.state.ages = result.ages || [];
        this.state.options = result.options || {
            license_yms: [],
            models: [],
            regions: [],
            age_buckets: [],
        };
        this.state.loading = false;
    }

    toggleDropdown(ev) {
        const name = ev.currentTarget.dataset.name;
        this.state.openDropdown = this.state.openDropdown === name ? "" : name;
    }

    isDropdownOpen(name) {
        return this.state.openDropdown === name;
    }

    async onCheckboxChange(ev) {
        const kind = ev.currentTarget.dataset.kind;
        const value = ev.currentTarget.value;
        const values = new Set(this.state.filters[kind]);
        if (ev.currentTarget.checked) {
            values.add(value);
        } else {
            values.delete(value);
        }
        this.state.filters[kind] = Array.from(values);
        await this.loadData();
    }

    async resetFilters() {
        this.state.filters.license_yms = [];
        this.state.filters.models = [];
        this.state.filters.regions = [];
        this.state.filters.age_buckets = [];
        this.state.openDropdown = "";
        await this.loadData();
    }

    get genderRows() {
        return this.state.genders.map((item, index) => ({
            ...item,
            color: GENDER_COLORS[index] || GENDER_COLORS[0],
            percent: percent(item.count, this.state.total),
        }));
    }

    get ageRows() {
        const maxCount = Math.max(...this.state.ages.map((item) => item.count), 0);
        return this.state.ages.map((item, index) => ({
            ...item,
            color: AGE_COLORS[index] || AGE_COLORS[1],
            percent: percent(item.count, this.state.total),
            width: maxCount ? Math.max(4, Math.round((item.count * 100) / maxCount)) : 0,
            top: maxCount > 0 && item.count === maxCount,
        }));
    }

    get dominantGender() {
        return this.genderRows.reduce(
            (best, item) => (item.count > best.count ? item : best),
            { label: "無資料", count: 0, percent: 0 }
        );
    }

    get dominantAge() {
        return this.ageRows.reduce(
            (best, item) => (item.count > best.count ? item : best),
            { label: "無資料", count: 0, percent: 0 }
        );
    }

    get genderGradient() {
        if (!this.state.total) {
            return "conic-gradient(#e5e7eb 0 100%)";
        }
        let start = 0;
        const parts = this.genderRows.map((item) => {
            const end = start + item.percent;
            const part = `${item.color} ${start}% ${end}%`;
            start = end;
            return part;
        });
        return `conic-gradient(${parts.join(", ")})`;
    }

    optionSelected(kind, value) {
        return this.state.filters[kind].includes(value);
    }

    filterSummary(kind, fallback) {
        const count = this.state.filters[kind].length;
        if (!count) {
            return fallback;
        }
        if (count === 1) {
            return this.state.filters[kind][0];
        }
        return `已選 ${count} 項`;
    }

    formatPercent(value) {
        return value ? formatPercent(value) : "0%";
    }
}

OilOwnerDashboard.template = "dms_report_ds.OilOwnerDashboard";

registry.category("actions").add("oil_owner_dashboard", OilOwnerDashboard);
