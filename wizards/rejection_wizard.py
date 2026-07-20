# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class OtmVendorRejectionWizard(models.TransientModel):
    """Shared wizard for rejecting or requesting changes (with a reason),
    including from bulk list-view actions."""
    _name = 'otm.vendor.rejection.wizard'
    _description = 'Reject Vendor Products / Request Changes'

    submission_ids = fields.Many2many(
        'otm.vendor.product.submission', string='Submissions', required=True,
        default=lambda self: self.env.context.get('active_ids'))
    submission_count = fields.Integer(compute='_compute_submission_count')
    mode = fields.Selection([
        ('reject', 'Reject'),
        ('request_changes', 'Request Changes'),
    ], required=True, default=lambda self: self.env.context.get(
        'default_mode', 'reject'))
    reason = fields.Text(string='Reason / Comments', required=True)

    def _compute_submission_count(self):
        for wizard in self:
            wizard.submission_count = len(wizard.submission_ids)

    def action_confirm(self):
        self.ensure_one()
        if self.mode == 'reject':
            self.submission_ids.action_reject(reason=self.reason)
        else:
            self.submission_ids.action_request_changes(notes=self.reason)
        return {'type': 'ir.actions.act_window_close'}
