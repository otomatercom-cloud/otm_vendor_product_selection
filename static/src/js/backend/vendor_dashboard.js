/** @odoo-module **/
// Part of Otomater. See LICENSE file for full copyright and licensing details.

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const STATE_LABELS = {
    draft: "Draft",
    submitted: "New Submissions",
    under_review: "Under Review",
    duplicate_review: "Duplicate Review",
    changes_requested: "Changes Requested",
    selected: "Selected",
    rejected: "Rejected",
    archived: "Archived",
};

const DUP_LABELS = {
    exact_duplicate: "Exact Duplicate",
    possible_duplicate: "Possible Duplicate",
    similar: "Similar Image",
};

const ACTIONABLE_STATES = ["submitted", "under_review", "duplicate_review"];

export class OtmVendorDashboard extends Component {
    static template = "otm_vendor_product_selection.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.tabs = [
            { id: "submitted", label: "New" },
            { id: "under_review", label: "Under Review" },
            { id: "duplicate_review", label: "Duplicate Review" },
            { id: "duplicates", label: "Duplicates Found" },
            { id: "changes_requested", label: "Changes Requested" },
            { id: "selected", label: "Selected" },
            { id: "rejected", label: "Rejected" },
            { id: "draft", label: "Draft" },
            { id: "all", label: "All" },
        ];

        this.state = useState({
            loading: true,
            activeTab: "submitted",
            kpis: {
                draft: 0, submitted: 0, under_review: 0, duplicate_review: 0,
                changes_requested: 0, selected: 0, rejected: 0, duplicates: 0,
            },
            submissions: [],
            duplicates: [],
            vendorMap: {},
        });

        onWillStart(async () => {
            await this.loadKpis();
            await this.loadTab(this.state.activeTab);
        });
    }

    // ------------------------------------------------------------
    // Data loading
    // ------------------------------------------------------------
    async loadKpis() {
        const states = ["draft", "submitted", "under_review", "duplicate_review",
            "changes_requested", "selected", "rejected"];
        const counts = {};
        await Promise.all(states.map(async (s) => {
            counts[s] = await this.orm.searchCount(
                "otm.vendor.product.submission", [["state", "=", s]]);
        }));
        const duplicates = await this.orm.searchCount(
            "otm.vendor.product.image",
            [["duplicate_status", "in",
              ["exact_duplicate", "possible_duplicate", "similar"]]]);
        Object.assign(this.state.kpis, counts, { duplicates });
    }

    async loadTab(tabId) {
        this.state.activeTab = tabId;
        this.state.loading = true;
        try {
            if (tabId === "duplicates") {
                await this.loadDuplicates();
            } else {
                const domain = tabId === "all" ? [] : [["state", "=", tabId]];
                this.state.submissions = await this.orm.searchRead(
                    "otm.vendor.product.submission", domain,
                    ["name", "vendor_id", "vendor_sku", "purchase_price",
                     "currency_id", "state", "has_duplicate_flag",
                     "main_image_id", "primary_category_id"],
                    { order: "create_date desc", limit: 120 });
            }
        } finally {
            this.state.loading = false;
        }
    }

    async loadDuplicates() {
        const images = await this.orm.searchRead(
            "otm.vendor.product.image",
            [["duplicate_status", "in",
              ["exact_duplicate", "possible_duplicate", "similar"]]],
            ["vendor_id", "submission_id", "similarity_score",
             "duplicate_status", "duplicate_image_id", "duplicate_vendor_id",
             "duplicate_submission_id", "duplicate_upload_date", "create_date"],
            { order: "create_date desc", limit: 120 });

        const vendorIds = new Set();
        for (const img of images) {
            if (img.vendor_id) { vendorIds.add(img.vendor_id[0]); }
            if (img.duplicate_vendor_id) { vendorIds.add(img.duplicate_vendor_id[0]); }
        }
        let vendorMap = {};
        if (vendorIds.size) {
            const partners = await this.orm.read(
                "res.partner", [...vendorIds],
                ["name", "email", "phone", "otm_vendor_code"]);
            for (const p of partners) { vendorMap[p.id] = p; }
        }
        this.state.vendorMap = vendorMap;
        this.state.duplicates = images;
    }

    async refreshCurrent() {
        await this.loadKpis();
        await this.loadTab(this.state.activeTab);
    }

    // ------------------------------------------------------------
    // Helpers used by the template
    // ------------------------------------------------------------
    stateLabel(state) {
        return STATE_LABELS[state] || state;
    }

    dupLabel(status) {
        return DUP_LABELS[status] || status;
    }

    isActionable(state) {
        return ACTIONABLE_STATES.includes(state);
    }

    mainImageUrl(rec) {
        return rec.main_image_id
            ? `/web/image/otm.vendor.product.image/${rec.main_image_id[0]}/image_256`
            : false;
    }

    imageUrl(imageId) {
        return `/web/image/otm.vendor.product.image/${imageId}/image_512`;
    }

    vendorInfo(vendorField) {
        if (!vendorField) { return false; }
        return this.state.vendorMap[vendorField[0]] || false;
    }

    // ------------------------------------------------------------
    // Submission actions
    // ------------------------------------------------------------
    async startReview(id) {
        await this.orm.call(
            "otm.vendor.product.submission", "action_start_review", [[id]]);
        this.notification.add("Moved to Under Review.", { type: "success" });
        await this.refreshCurrent();
    }

    openSelectWizard(id) {
        this.action.doAction(
            "otm_vendor_product_selection.action_otm_vendor_selection_wizard",
            {
                additionalContext: { active_ids: [id] },
                onClose: () => this.refreshCurrent(),
            });
    }

    openRejectWizard(id) {
        this.action.doAction(
            "otm_vendor_product_selection.action_otm_vendor_rejection_wizard",
            {
                additionalContext: { active_ids: [id], default_mode: "reject" },
                onClose: () => this.refreshCurrent(),
            });
    }

    openProduct(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "otm.vendor.product.submission",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ------------------------------------------------------------
    // Duplicate image actions
    // ------------------------------------------------------------
    async confirmDuplicate(imageId) {
        await this.orm.call(
            "otm.vendor.product.image", "action_confirm_duplicate", [[imageId]]);
        this.notification.add("Marked as duplicate.", { type: "success" });
        await this.refreshCurrent();
    }

    async notDuplicate(imageId) {
        await this.orm.call(
            "otm.vendor.product.image", "action_not_duplicate", [[imageId]]);
        this.notification.add("Cleared duplicate flag.", { type: "success" });
        await this.refreshCurrent();
    }

    async keepBoth(imageId) {
        await this.orm.call(
            "otm.vendor.product.image", "action_keep_both", [[imageId]]);
        this.notification.add("Both images kept.", { type: "success" });
        await this.refreshCurrent();
    }

    async linkExisting(imageId) {
        await this.orm.call(
            "otm.vendor.product.image", "action_link_existing_product",
            [[imageId]]);
        this.notification.add("Linked to the existing product.",
            { type: "success" });
        await this.refreshCurrent();
    }
}

registry.category("actions").add(
    "otm_vendor_product_selection.dashboard", OtmVendorDashboard);
