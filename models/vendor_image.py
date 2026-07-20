# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.exceptions import UserError


class OtmVendorProductImage(models.Model):
    """One image of a vendor product submission.

    Inherits ``image.mixin`` so Odoo automatically maintains resized
    variants (image_1024/512/256/128) — grids and the mobile review UI only
    ever load thumbnails; the original ``image_1920`` is loaded on demand.

    Duplicate detection data:
      * ``sha256_hash``       — exact duplicate detection (indexed).
      * ``dhash`` / ``ahash`` — 64-bit perceptual hashes stored as 16-char hex.
      * ``dhash_c1..c4``      — the 4 x 16-bit bands of the dhash, each
        indexed. Candidate retrieval for similarity search matches on ANY
        band being equal (locality-sensitive banding): by the pigeonhole
        principle every image within Hamming distance 3 shares at least one
        band, and in practice near-duplicates within the configured
        thresholds nearly always share one. This avoids comparing every new
        image against every stored hash.
    """
    _name = 'otm.vendor.product.image'
    _description = 'Vendor Product Image'
    _inherit = ['image.mixin']
    _order = 'submission_id, sequence, id'

    name = fields.Char(string='Filename')
    sequence = fields.Integer(default=10)
    submission_id = fields.Many2one(
        'otm.vendor.product.submission', string='Product Submission',
        index=True, ondelete='cascade')
    batch_id = fields.Many2one(
        'otm.vendor.upload.batch', string='Upload Batch',
        index=True, ondelete='set null')
    vendor_id = fields.Many2one(
        'res.partner', string='Vendor', index=True, store=True,
        compute='_compute_vendor_id', readonly=False,
        domain=[('is_otm_vendor', '=', True)])
    is_main_image = fields.Boolean(string='Main Image', default=False)
    view_type = fields.Selection([
        ('front', 'Front View'),
        ('back', 'Back View'),
        ('side', 'Side View'),
        ('detail', 'Detail View'),
        ('other', 'Other'),
    ], string='View Type', default='other')

    # --- duplicate detection data -------------------------------------
    sha256_hash = fields.Char(string='SHA-256 Hash', size=64, index=True,
                              readonly=True, copy=False)
    perceptual_hash = fields.Char(
        string='Perceptual Hash (dHash)', size=16, index=True,
        readonly=True, copy=False,
        help='64-bit difference hash stored as hexadecimal.')
    average_hash = fields.Char(
        string='Average Hash', size=16, readonly=True, copy=False)
    dhash_c1 = fields.Char(size=4, index=True, readonly=True, copy=False)
    dhash_c2 = fields.Char(size=4, index=True, readonly=True, copy=False)
    dhash_c3 = fields.Char(size=4, index=True, readonly=True, copy=False)
    dhash_c4 = fields.Char(size=4, index=True, readonly=True, copy=False)

    duplicate_status = fields.Selection([
        ('pending', 'Pending Analysis'),
        ('new', 'New'),
        ('exact_duplicate', 'Exact Duplicate'),
        ('possible_duplicate', 'Possible Duplicate'),
        ('similar', 'Similar Image'),
        ('approved_duplicate', 'Approved Duplicate'),
        ('rejected_duplicate', 'Duplicate Rejected'),
    ], string='Duplicate Status', default='pending', index=True, copy=False)
    duplicate_image_id = fields.Many2one(
        'otm.vendor.product.image', string='Matching Existing Image',
        index=True, copy=False, ondelete='set null')
    similarity_score = fields.Float(
        string='Similarity Score (%)', copy=False,
        help='100% = identical perceptual hash.')
    process_state = fields.Selection([
        ('pending', 'Pending'),
        ('done', 'Processed'),
        ('error', 'Error'),
    ], string='Processing', default='pending', index=True, copy=False,
        help='Guards against the same upload being analysed twice.')
    process_error = fields.Text(readonly=True, copy=False)

    # Convenience related fields for the duplicate review screen
    duplicate_vendor_id = fields.Many2one(
        related='duplicate_image_id.vendor_id', string='Existing Vendor')
    duplicate_submission_id = fields.Many2one(
        related='duplicate_image_id.submission_id', string='Existing Product')
    duplicate_upload_date = fields.Datetime(
        related='duplicate_image_id.create_date', string='Existing Upload Date')

    @api.depends('submission_id.vendor_id', 'batch_id.vendor_id')
    def _compute_vendor_id(self):
        for image in self:
            image.vendor_id = (
                image.submission_id.vendor_id
                or image.batch_id.vendor_id
                or image.vendor_id)

    @api.model_create_multi
    def create(self, vals_list):
        images = super().create(vals_list)
        # Hashes are computed synchronously at create time (cheap: SHA-256 +
        # one 9x8 grayscale resize). Full duplicate *comparison* is done
        # either synchronously (small uploads, from the controllers) or by
        # the cron for large batches — see duplicate_service.py.
        images._otm_compute_hashes()
        return images

    def write(self, vals):
        res = super().write(vals)
        if 'image_1920' in vals:
            self.write_hash_reset()
            self._otm_compute_hashes()
        return res

    def write_hash_reset(self):
        # Bypass recursion: only clear derived data, don't touch image_1920.
        super().write({
            'sha256_hash': False, 'perceptual_hash': False,
            'average_hash': False, 'dhash_c1': False, 'dhash_c2': False,
            'dhash_c3': False, 'dhash_c4': False,
            'duplicate_status': 'pending', 'process_state': 'pending',
        })

    def _otm_compute_hashes(self):
        service = self.env['otm.vendor.duplicate.service']
        for image in self.filtered(lambda i: i.image_1920 and not i.sha256_hash):
            hashes = service._compute_hashes_for_image(image.image_1920)
            if hashes:
                super(OtmVendorProductImage, image).write(hashes)

    # ------------------------------------------------------------------
    # Duplicate review actions (Purchase Manager)
    # ------------------------------------------------------------------
    def _check_review_rights(self):
        if not self.env.user.has_group(
                'otm_vendor_product_selection.group_otm_vendor_manager'):
            raise UserError(self.env._(
                'Only Purchase Managers can review duplicate images.'))

    def action_confirm_duplicate(self):
        self._check_review_rights()
        self.write({'duplicate_status': 'rejected_duplicate'})
        self._otm_log_review(self.env._('confirmed as duplicate and rejected'))

    def action_not_duplicate(self):
        self._check_review_rights()
        self.write({'duplicate_status': 'new', 'duplicate_image_id': False,
                    'similarity_score': 0.0})
        self._otm_log_review(self.env._('marked as NOT a duplicate'))

    def action_keep_both(self):
        self._check_review_rights()
        self.write({'duplicate_status': 'approved_duplicate'})
        self._otm_log_review(self.env._('kept alongside the existing image'))

    def action_link_existing_product(self):
        """Attach this image to the product submission that owns the
        matching existing image instead of keeping a separate copy."""
        self._check_review_rights()
        for image in self:
            target = image.duplicate_image_id.submission_id
            if not target:
                raise UserError(self.env._(
                    'The matching image is not linked to a product '
                    'submission.'))
            image.write({
                'submission_id': target.id,
                'duplicate_status': 'approved_duplicate',
            })
        self._otm_log_review(self.env._('linked to the existing product'))

    def _otm_log_review(self, action_label):
        for image in self.filtered('submission_id'):
            image.submission_id.message_post(body=self.env._(
                'Duplicate review: image "%(name)s" %(action)s by %(user)s.',
                name=image.name or image.id, action=action_label,
                user=self.env.user.name))
