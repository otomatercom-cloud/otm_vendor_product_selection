# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.
"""Load / remove the demo records on an EXISTING database.

Odoo only offers the "Load demonstration data" option when a database is
created, so on a running system the module's demo file is loaded from a
menu button instead (Vendor Products > Configuration > Demo Data).
"""

from odoo import api, models, tools
from odoo.exceptions import UserError

MODULE = 'otm_vendor_product_selection'
DEMO_FILE = 'data/demo_data.xml'
# deletion order matters: children before parents
DEMO_MODELS = ('otm.vendor.design.match', 'otm.vendor.product.image',
               'otm.vendor.product.submission', 'res.partner')


class OtmVendorDemoLoader(models.AbstractModel):
    _name = 'otm.vendor.demo.loader'
    _description = 'Vendor Product Selection Demo Data Loader'

    @api.model
    def _check_admin(self):
        if not self.env.user.has_group(
                'otm_vendor_product_selection.group_otm_vendor_admin'):
            raise UserError(self.env._(
                'Only Vendor Product administrators can manage demo data.'))

    @api.model
    def _demo_xmlids(self):
        return self.env['ir.model.data'].sudo().search([
            ('module', '=', MODULE), '|',
            ('name', '=like', 'demo\\_%'), ('name', '=like', 'img\\_%')])

    @api.model
    def _notify(self, message, reload=False):
        params = {'title': self.env._('Demo data'), 'message': message,
                  'type': 'success', 'sticky': False}
        if reload:
            params['next'] = {'type': 'ir.actions.client', 'tag': 'reload'}
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': params}

    @api.model
    def action_load_demo(self, *args, **kwargs):
        self._check_admin()
        if self._demo_xmlids():
            return self._notify(self.env._('Demo data is already loaded.'))
        tools.convert_file(
            self.sudo().env, MODULE, DEMO_FILE, {}, 'init', False)
        return self._notify(
            self.env._('Demo vendors, products and duplicate matches loaded.'),
            reload=True)

    @api.model
    def action_remove_demo(self, *args, **kwargs):
        self._check_admin()
        xmlids = self._demo_xmlids()
        if not xmlids:
            return self._notify(self.env._('No demo data to remove.'))
        by_model = {}
        for data in xmlids:
            by_model.setdefault(data.model, set()).add(data.res_id)
        for model_name in DEMO_MODELS:
            ids = by_model.get(model_name)
            if ids:
                self.env[model_name].sudo().browse(ids).exists().unlink()
        return self._notify(self.env._('Demo data removed.'), reload=True)
