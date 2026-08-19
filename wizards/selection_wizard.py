# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class OtmVendorSelectionWizard(models.TransientModel):
    """Confirmation step when selecting one or several submissions.

    Works for a single record (quantity/price/notes applied to it) and for
    bulk selection from the list view (values applied to every record)."""
    _name = 'otm.vendor.selection.wizard'
    _description = 'Select Vendor Products'

    submission_ids = fields.Many2many(
        'otm.vendor.product.submission', string='Submissions', required=True,
        default=lambda self: self.env.context.get('active_ids'))
    submission_count = fields.Integer(
        compute='_compute_submission_count')
    currency_id = fields.Many2one(
        'res.currency', compute='_compute_currency_id')
    # Defaults to the number of images grouped into the product at upload
    # time (see otm.vendor.product.submission.available_qty) — a vendor
    # grouping 5 photos into one product is treated as 5 available
    # designs/units of that product, so that's the natural starting
    # quantity for a Purchase Manager to select against.
    selected_qty = fields.Float(string='Selected Quantity')
    negotiated_price = fields.Float(string='Negotiated Purchase Price')
    total_amount = fields.Monetary(
        string='Total Amount', compute='_compute_total_amount',
        currency_field='currency_id',
        help='Selected Quantity x Negotiated Price, summed across every '
             'product in this selection — the amount you are committing '
             'to by confirming.')
    selection_notes = fields.Text(string='Selection Note')

    def _compute_submission_count(self):
        for wizard in self:
            wizard.submission_count = len(wizard.submission_ids)

    def _compute_currency_id(self):
        for wizard in self:
            wizard.currency_id = (wizard.submission_ids[:1].currency_id
                                   or self.env.company.currency_id)

    @api.depends('selected_qty', 'negotiated_price', 'submission_ids')
    def _compute_total_amount(self):
        for wizard in self:
            qty = wizard.selected_qty or 0.0
            if wizard.negotiated_price:
                price = wizard.negotiated_price
            else:
                price = wizard.submission_ids[:1].purchase_price or 0.0
            # The same qty/price is applied to every submission on confirm
            # (see action_confirm below), so the total scales with count.
            wizard.total_amount = qty * price * (len(wizard.submission_ids) or 1)

    @api.onchange('submission_ids')
    def _onchange_submission_ids(self):
        if len(self.submission_ids) == 1:
            submission = self.submission_ids[0]
            if not self.selected_qty:
                self.selected_qty = (submission.available_qty
                                      or submission.min_order_qty or 1)
            if not self.negotiated_price:
                self.negotiated_price = submission.purchase_price

    def action_confirm(self):
        self.ensure_one()
        # action_select() re-checks the Purchase Manager group server-side.
        self.submission_ids.action_select(
            qty=self.selected_qty or None,
            price=self.negotiated_price or None,
            notes=self.selection_notes or None)
        return {'type': 'ir.actions.act_window_close'}
