# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class OtmVendorUploadBatch(models.Model):
    """One bulk-upload session from a vendor (portal or backend).

    Every image uploaded through the bulk uploader is attached to a batch so
    the vendor can later see how many files were accepted, how many were
    exact duplicates and how many were flagged for review.
    """
    _name = 'otm.vendor.upload.batch'
    _description = 'Vendor Bulk Upload Batch'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Batch Number', required=True, copy=False, readonly=True,
        default=lambda self: self.env._('New'))
    vendor_id = fields.Many2one(
        'res.partner', string='Vendor', required=True, index=True,
        domain=[('is_otm_vendor', '=', True)], tracking=True)
    upload_date = fields.Datetime(
        string='Upload Date', default=fields.Datetime.now, readonly=True)
    uploaded_by_id = fields.Many2one(
        'res.users', string='Uploaded By',
        default=lambda self: self.env.user, readonly=True)
    image_ids = fields.One2many(
        'otm.vendor.product.image', 'batch_id', string='Images')
    total_images = fields.Integer(
        string='Total Images', compute='_compute_image_stats', store=True)
    new_images = fields.Integer(
        string='New Images', compute='_compute_image_stats', store=True)
    exact_duplicates = fields.Integer(
        string='Exact Duplicates', compute='_compute_image_stats', store=True)
    possible_duplicates = fields.Integer(
        string='Possible Duplicates', compute='_compute_image_stats', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('uploading', 'Uploading'),
        ('processing', 'Processing'),
        ('done', 'Completed'),
        ('failed', 'Failed'),
    ], string='Processing Status', default='draft', tracking=True, index=True)
    notes = fields.Text(string='Notes')
    error_log = fields.Text(string='Error Log', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', self.env._('New')) == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'otm.vendor.upload.batch') or self.env._('New')
        return super().create(vals_list)

    @api.depends('image_ids.duplicate_status')
    def _compute_image_stats(self):
        for batch in self:
            images = batch.image_ids
            batch.total_images = len(images)
            batch.exact_duplicates = len(images.filtered(
                lambda i: i.duplicate_status == 'exact_duplicate'))
            batch.possible_duplicates = len(images.filtered(
                lambda i: i.duplicate_status in ('possible_duplicate', 'similar')))
            batch.new_images = len(images.filtered(
                lambda i: i.duplicate_status in ('new', 'approved_duplicate')))

    def action_mark_done(self):
        self.write({'state': 'done'})

    def _log_error(self, message):
        """Append a processing error to the batch log (Rule: log errors)."""
        for batch in self:
            existing = batch.error_log or ''
            batch.error_log = '%s%s: %s\n' % (
                existing, fields.Datetime.now(), message)
