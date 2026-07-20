# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class OtmVendorProductCategory(models.Model):
    """Hierarchical fashion product category.

    A category has at most one parent and unlimited children. Submissions
    reference one *primary* category (Many2one) plus any number of extra
    categories (Many2many), e.g. a "Floral Cotton Maxi Dress" can live under
    Women / Dresses / Maxi Dresses / Cotton Collection / Summer Collection.
    """
    _name = 'otm.vendor.product.category'
    _description = 'Vendor Product Category'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name'

    name = fields.Char(string='Category Name', required=True, translate=True)
    code = fields.Char(string='Category Code', copy=False)
    parent_id = fields.Many2one(
        'otm.vendor.product.category', string='Parent Category',
        index=True, ondelete='cascade')
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many(
        'otm.vendor.product.category', 'parent_id', string='Child Categories')
    complete_name = fields.Char(
        string='Complete Name', compute='_compute_complete_name',
        recursive=True, store=True)
    image = fields.Image(string='Category Image', max_width=1024, max_height=1024)
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    submission_count = fields.Integer(
        string='Submissions', compute='_compute_submission_count')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The category code must be unique.'),
    ]

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = '%s / %s' % (
                    category.parent_id.complete_name, category.name)
            else:
                category.complete_name = category.name

    def _compute_submission_count(self):
        Submission = self.env['otm.vendor.product.submission']
        for category in self:
            category.submission_count = Submission.search_count([
                '|',
                ('primary_category_id', 'child_of', category.id),
                ('category_ids', 'child_of', category.id),
            ])

    @api.constrains('parent_id')
    def _check_category_recursion(self):
        if self._has_cycle():
            raise ValidationError(
                self.env._('You cannot create a recursive category hierarchy.'))

    def action_view_submissions(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'otm_vendor_product_selection.action_otm_vendor_product_submission')
        action['domain'] = [
            '|',
            ('primary_category_id', 'child_of', self.id),
            ('category_ids', 'child_of', self.id),
        ]
        return action
