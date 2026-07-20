# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.
"""Create/reset a vendor's portal login directly, without relying on the
standard portal-access wizard's invitation e-mail. Useful for local/dev
setups with no outgoing mail server configured, or when an admin simply
wants to hand a vendor a login on the spot.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError


class OtmVendorPortalUserWizard(models.TransientModel):
    _name = 'otm.vendor.portal.user.wizard'
    _description = 'Create / Reset Vendor Portal Login'

    partner_id = fields.Many2one(
        'res.partner', string='Vendor', required=True,
        domain=[('is_otm_vendor', '=', True)])
    login = fields.Char(string='Login (Email)', required=True)
    password = fields.Char(string='Password', required=True)
    confirm_password = fields.Char(string='Confirm Password', required=True)
    existing_user_id = fields.Many2one(
        'res.users', string='Existing Portal User',
        compute='_compute_existing_user')

    @api.depends('login')
    def _compute_existing_user(self):
        for wiz in self:
            wiz.existing_user_id = (
                self.env['res.users'].sudo().with_context(active_test=False)
                .search([('login', '=', wiz.login)], limit=1)
                if wiz.login else False)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        partner_id = self.env.context.get('active_id')
        if partner_id:
            partner = self.env['res.partner'].browse(partner_id)
            if 'partner_id' in fields_list:
                res['partner_id'] = partner.id
            if 'login' in fields_list:
                res['login'] = partner.email or ''
        return res

    def action_create_or_reset_user(self):
        self.ensure_one()
        if not self.partner_id.is_otm_vendor:
            raise UserError(self.env._(
                'This contact is not marked as a Fashion Vendor.'))
        if not self.login or '@' not in self.login:
            raise UserError(self.env._('Enter a valid e-mail as the login.'))
        if not self.password or len(self.password) < 4:
            raise UserError(self.env._(
                'Password must be at least 4 characters.'))
        if self.password != self.confirm_password:
            raise UserError(self.env._(
                'Password and confirmation do not match.'))

        portal_group = self.env.ref('base.group_portal')
        User = self.env['res.users'].sudo().with_context(active_test=False)
        user = User.search([('login', '=', self.login)], limit=1)

        if user:
            if user.partner_id != self.partner_id:
                raise UserError(self.env._(
                    'A user with this login already exists, linked to a '
                    'different contact (%(name)s). Use a different '
                    'login/e-mail for this vendor.',
                    name=user.partner_id.display_name))
            user.write({
                'password': self.password,
                'active': True,
                'group_ids': [(4, portal_group.id)],
            })
        else:
            user = User.create({
                'name': self.partner_id.name,
                'login': self.login,
                'email': self.login,
                'partner_id': self.partner_id.id,
                'password': self.password,
                'group_ids': [(6, 0, [portal_group.id])],
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': self.env._('Portal Login Ready'),
                'message': self.env._(
                    'Login: %(login)s — the vendor can now sign in and '
                    'visit /my/vendor.', login=self.login),
                'type': 'success',
                'sticky': True,
            },
        }
