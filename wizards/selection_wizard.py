# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


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
    selected_qty = fields.Float(string='Selected Quantity')
    negotiated_price = fields.Float(string='Negotiated Purchase Price')
    selection_notes = fields.Text(string='Selection Note')

    def _compute_submission_count(self):
        for wizard in self:
            wizard.submission_count = len(wizard.submission_ids)

    def action_confirm(self):
        self.ensure_one()
        # action_select() re-checks the Purchase Manager group server-side.
        self.submission_ids.action_select(
            qty=self.selected_qty or None,
            price=self.negotiated_price or None,
            notes=self.selection_notes or None)
        return {'type': 'ir.actions.act_window_close'}
