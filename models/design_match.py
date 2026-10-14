# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class OtmVendorDesignMatch(models.Model):
    """One 'this image looks like that earlier image' result with a
    design-match percentage (any angle / any person wearing it)."""
    _name = 'otm.vendor.design.match'
    _description = 'Vendor Design Match'
    _order = 'score desc, id'

    image_id = fields.Many2one(
        'otm.vendor.product.image', string='New Image', required=True,
        index=True, ondelete='cascade')
    match_image_id = fields.Many2one(
        'otm.vendor.product.image', string='Earlier Image', required=True,
        index=True, ondelete='cascade')
    score = fields.Float(string='Design Match (%)', digits=(5, 1))

    vendor_id = fields.Many2one(
        related='image_id.vendor_id', string='New Image Vendor')
    submission_id = fields.Many2one(
        related='image_id.submission_id', string='New Image Product')
    match_vendor_id = fields.Many2one(
        related='match_image_id.vendor_id', string='Earlier Vendor')
    match_submission_id = fields.Many2one(
        related='match_image_id.submission_id', string='Earlier Product')
    match_state = fields.Selection(
        related='match_submission_id.state',
        string='Earlier Product Status')
    match_date = fields.Datetime(
        related='match_image_id.create_date', string='Earlier Upload Date')
    match_image_128 = fields.Image(
        related='match_image_id.image_128', string='Earlier Preview')
    same_vendor = fields.Boolean(
        string='Same Vendor', compute='_compute_same_vendor',
        store=True)

    @api.depends('image_id.vendor_id', 'match_image_id.vendor_id')
    def _compute_same_vendor(self):
        for match in self:
            match.same_vendor = bool(
                match.image_id.vendor_id
                and match.image_id.vendor_id == match.match_image_id.vendor_id)
