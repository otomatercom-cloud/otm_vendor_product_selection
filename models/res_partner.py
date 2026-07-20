# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_otm_vendor = fields.Boolean(
        string='Is Fashion Vendor', index=True,
        help='Check to register this partner as a vendor for the '
             'Otomater Vendor Product Selection platform.')
    otm_vendor_code = fields.Char(
        string='Vendor Code', copy=False, readonly=True, index=True)
    otm_vendor_contact_person = fields.Char(string='Contact Person')
    otm_vendor_whatsapp = fields.Char(string='WhatsApp Number')
    otm_vendor_type = fields.Selection([
        ('manufacturer', 'Manufacturer'),
        ('wholesaler', 'Wholesaler'),
        ('distributor', 'Distributor'),
        ('boutique', 'Boutique / Designer'),
        ('agent', 'Agent'),
    ], string='Vendor Type')
    otm_vendor_registration_date = fields.Date(
        string='Registration Date', default=fields.Date.context_today)
    otm_vendor_notes = fields.Text(string='Vendor Notes')
    otm_vendor_active = fields.Boolean(string='Vendor Active', default=True)
    otm_portal_user_ids = fields.One2many(
        'res.users', compute='_compute_otm_portal_user_ids',
        string='Portal Users')
    otm_submission_ids = fields.One2many(
        'otm.vendor.product.submission', 'vendor_id', string='Product Submissions')
    otm_submission_count = fields.Integer(
        compute='_compute_otm_submission_count', string='Submission Count')

    _sql_constraints = [
        ('otm_vendor_code_uniq', 'unique(otm_vendor_code)',
         'The vendor code must be unique.'),
    ]

    def _compute_otm_portal_user_ids(self):
        portal_group = self.env.ref('base.group_portal', raise_if_not_found=False)
        for partner in self:
            users = partner.with_context(active_test=False).user_ids
            if portal_group:
                users = users.filtered(
                    lambda u: portal_group in u.group_ids)
            partner.otm_portal_user_ids = users

    def _compute_otm_submission_count(self):
        counts = dict(self.env['otm.vendor.product.submission']._read_group(
            domain=[('vendor_id', 'in', self.ids)],
            groupby=['vendor_id'],
            aggregates=['__count'],
        ))
        for partner in self:
            partner.otm_submission_count = counts.get(partner, 0)

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners.filtered('is_otm_vendor')._otm_assign_vendor_code()
        return partners

    def write(self, vals):
        res = super().write(vals)
        if vals.get('is_otm_vendor'):
            self._otm_assign_vendor_code()
        return res

    def _otm_assign_vendor_code(self):
        for partner in self.filtered(
                lambda p: p.is_otm_vendor and not p.otm_vendor_code):
            partner.otm_vendor_code = self.env['ir.sequence'].sudo(
                ).next_by_code('otm.vendor.code') or '/'
            if not partner.supplier_rank:
                partner.supplier_rank = 1

    def action_otm_grant_portal_access(self):
        """Open the standard portal-access wizard pre-filtered on this vendor
        so an administrator can create/enable the portal login."""
        self.ensure_one()
        if not self.email:
            raise UserError(self.env._(
                'Set an e-mail address on the vendor before granting '
                'portal access.'))
        action = self.env['ir.actions.act_window']._for_xml_id(
            'portal.partner_wizard_action')
        action['context'] = {'active_ids': self.ids, 'active_model': 'res.partner'}
        return action

    def action_otm_view_submissions(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'otm_vendor_product_selection.action_otm_vendor_product_submission')
        action['domain'] = [('vendor_id', 'child_of', self.id)]
        action['context'] = {'default_vendor_id': self.id}
        return action

    @api.model
    def _otm_get_vendor_for_user(self, user):
        """Return the vendor partner a portal user acts for (the user's own
        partner if flagged as vendor, else its commercial parent)."""
        partner = user.partner_id
        if partner.is_otm_vendor:
            return partner
        commercial = partner.commercial_partner_id
        if commercial.is_otm_vendor:
            return commercial
        return self.browse()
