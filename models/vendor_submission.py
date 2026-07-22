# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

# States a portal vendor is allowed to edit their own submission in
PORTAL_EDITABLE_STATES = ('draft', 'changes_requested')
# Fields a portal vendor may write (whitelist — everything else is refused
# for portal users, so approval/selection data can never be forged from the
# portal even by crafting RPC calls; Rule 15 of the spec).
PORTAL_WRITABLE_FIELDS = {
    'name', 'vendor_sku', 'description', 'material', 'color', 'size',
    'available_sizes', 'purchase_price', 'mrp', 'min_order_qty',
    'available_qty', 'brand', 'gender', 'season', 'style', 'tag_ids',
    'primary_category_id', 'category_ids', 'vendor_notes', 'image_ids',
    'main_image_id',
}


class OtmVendorProductTag(models.Model):
    _name = 'otm.vendor.product.tag'
    _description = 'Vendor Product Tag'
    _order = 'name'

    name = fields.Char(required=True)
    color = fields.Integer(string='Color Index')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Tag name must be unique.'),
    ]


class OtmVendorProductSubmission(models.Model):
    """A product proposed by a vendor, reviewed by the Purchase Manager.

    Deliberately a separate model from ``product.template`` (Rule 13 of the
    spec): a real Odoo product is only created when the Purchase Manager
    runs "Create Odoo Product" on a selected submission.
    """
    _name = 'otm.vendor.product.submission'
    _description = 'Vendor Product Submission'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    name = fields.Char(string='Product Name', required=True, tracking=True)
    code = fields.Char(string='Reference', copy=False, readonly=True,
                       default=lambda self: self.env._('New'))
    vendor_sku = fields.Char(string='Vendor Product Code / SKU', tracking=True)
    vendor_id = fields.Many2one(
        'res.partner', string='Vendor', required=True, index=True,
        domain=[('is_otm_vendor', '=', True)], tracking=True,
        default=lambda self: self.env['res.partner']._otm_get_vendor_for_user(
            self.env.user))
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        related='company_id.currency_id', string='Currency')

    # ------------------------------------------------------------------
    # Categorisation
    # ------------------------------------------------------------------
    primary_category_id = fields.Many2one(
        'otm.vendor.product.category', string='Main Category',
        index=True, tracking=True)
    category_ids = fields.Many2many(
        'otm.vendor.product.category',
        'otm_vendor_submission_category_rel', 'submission_id', 'category_id',
        string='Categories')
    tag_ids = fields.Many2many(
        'otm.vendor.product.tag',
        'otm_vendor_submission_tag_rel', 'submission_id', 'tag_id',
        string='Product Tags')

    # ------------------------------------------------------------------
    # Product attributes
    # ------------------------------------------------------------------
    description = fields.Html(string='Description')
    material = fields.Char(string='Material / Fabric')
    color = fields.Char(string='Color')
    size = fields.Char(string='Size')
    available_sizes = fields.Char(
        string='Available Sizes', help='e.g. S, M, L, XL, XXL')
    brand = fields.Char(string='Brand')
    gender = fields.Selection([
        ('women', 'Women'), ('men', 'Men'),
        ('girls', 'Girls'), ('boys', 'Boys'), ('unisex', 'Unisex'),
    ], string='Gender')
    season = fields.Selection([
        ('summer', 'Summer'), ('winter', 'Winter'),
        ('monsoon', 'Monsoon'), ('all', 'All Season'),
    ], string='Season')
    style = fields.Char(string='Style')
    vendor_notes = fields.Text(string='Vendor Notes')

    # ------------------------------------------------------------------
    # Commercials
    # ------------------------------------------------------------------
    purchase_price = fields.Monetary(string='Purchase Price', tracking=True)
    mrp = fields.Monetary(string='MRP', tracking=True)
    min_order_qty = fields.Float(string='Minimum Order Quantity', default=1.0)
    available_qty = fields.Float(string='Available Quantity')

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------
    image_ids = fields.One2many(
        'otm.vendor.product.image', 'submission_id', string='Images')
    main_image_id = fields.Many2one(
        'otm.vendor.product.image', string='Main Image',
        domain="[('submission_id', '=', id)]")
    image_count = fields.Integer(compute='_compute_image_stats', store=True)
    has_duplicate_flag = fields.Boolean(
        string='Has Duplicate Images', compute='_compute_image_stats',
        store=True, index=True,
        help='True when at least one image is flagged as an exact or '
             'possible duplicate awaiting review.')

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('duplicate_review', 'Duplicate Review'),
        ('changes_requested', 'Changes Requested'),
        ('selected', 'Selected'),
        ('rejected', 'Rejected'),
        ('archived', 'Archived'),
    ], string='Status', default='draft', required=True, index=True,
        tracking=True, copy=False)
    active = fields.Boolean(default=True)
    submit_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    review_user_id = fields.Many2one(
        'res.users', string='Reviewed By', readonly=True, copy=False)

    # Selection data
    selected_by_id = fields.Many2one(
        'res.users', string='Selected By', readonly=True, copy=False)
    selected_date = fields.Datetime(string='Selection Date', readonly=True, copy=False)
    selection_notes = fields.Text(string='Selection Notes', copy=False)
    selected_qty = fields.Float(string='Selected Quantity', copy=False)
    negotiated_price = fields.Monetary(
        string='Negotiated Purchase Price', copy=False)

    # Rejection / change request data
    rejection_reason = fields.Text(string='Rejection Reason', copy=False)
    change_request_notes = fields.Text(string='Requested Changes', copy=False)
    manager_comments = fields.Text(string='Purchase Manager Comments', copy=False)

    # Conversion
    product_tmpl_id = fields.Many2one(
        'product.template', string='Odoo Product', readonly=True, copy=False,
        index=True)

    _sql_constraints = [
        ('vendor_sku_uniq', 'unique(vendor_id, vendor_sku)',
         'This vendor already uses this SKU on another submission.'),
    ]

    # ------------------------------------------------------------------
    # Computes / constraints
    # ------------------------------------------------------------------
    @api.depends('image_ids', 'image_ids.duplicate_status')
    def _compute_image_stats(self):
        for submission in self:
            submission.image_count = len(submission.image_ids)
            submission.has_duplicate_flag = any(
                img.duplicate_status in ('exact_duplicate', 'possible_duplicate')
                for img in submission.image_ids)

    @api.constrains('purchase_price', 'mrp')
    def _check_prices(self):
        for submission in self:
            if submission.purchase_price < 0 or submission.mrp < 0:
                raise ValidationError(
                    self.env._('Prices cannot be negative.'))

    # ------------------------------------------------------------------
    # CRUD with portal security (server-side, not just hidden buttons)
    # ------------------------------------------------------------------
    def _is_portal_vendor_user(self):
        user = self.env.user
        return (user.has_group('base.group_portal')
                and not user.has_group('base.group_user'))

    @api.model_create_multi
    def create(self, vals_list):
        is_portal = self._is_portal_vendor_user()
        vendor = self.env['res.partner']._otm_get_vendor_for_user(self.env.user)
        for vals in vals_list:
            if vals.get('code', self.env._('New')) == self.env._('New'):
                # Sequence numbering is an internal detail; portal vendors
                # have no ir.sequence access, so this must run as sudo.
                vals['code'] = self.env['ir.sequence'].sudo().next_by_code(
                    'otm.vendor.product.submission') or self.env._('New')
            if is_portal:
                # Portal users can only ever create drafts for themselves.
                if not vendor:
                    raise AccessError(self.env._(
                        'Your portal account is not linked to a registered '
                        'vendor. Please contact the administrator.'))
                vals['vendor_id'] = vendor.id
                vals['state'] = 'draft'
                illegal = set(vals) - PORTAL_WRITABLE_FIELDS - {
                    'code', 'vendor_id', 'state', 'company_id'}
                if illegal:
                    raise AccessError(self.env._(
                        'You are not allowed to set: %(fields)s',
                        fields=', '.join(sorted(illegal))))
        return super().create(vals_list)

    def write(self, vals):
        if self._is_portal_vendor_user():
            illegal = set(vals) - PORTAL_WRITABLE_FIELDS
            if illegal:
                raise AccessError(self.env._(
                    'You are not allowed to modify: %(fields)s',
                    fields=', '.join(sorted(illegal))))
            for submission in self:
                if submission.state not in PORTAL_EDITABLE_STATES:
                    raise AccessError(self.env._(
                        'Submission %(code)s can no longer be edited in its '
                        'current status.', code=submission.code))
        return super().write(vals)

    # ------------------------------------------------------------------
    # Workflow transitions
    # ------------------------------------------------------------------
    def _check_manager(self):
        if not self.env.user.has_group(
                'otm_vendor_product_selection.group_otm_vendor_manager'):
            raise AccessError(self.env._(
                'Only Purchase Managers can perform this action.'))

    def action_submit(self):
        """Vendor (or internal user) submits a draft for review."""
        for submission in self:
            if submission.state not in PORTAL_EDITABLE_STATES:
                raise UserError(self.env._(
                    'Only draft submissions or submissions with requested '
                    'changes can be submitted.'))
            if not submission.image_ids:
                raise UserError(self.env._(
                    'Add at least one product image before submitting.'))
            if self._is_portal_vendor_user():
                vendor = self.env['res.partner']._otm_get_vendor_for_user(
                    self.env.user)
                if submission.vendor_id != vendor:
                    raise AccessError(self.env._(
                        'You can only submit your own products.'))
        self.sudo().write({
            'state': 'submitted',
            'submit_date': fields.Datetime.now(),
        })
        self.sudo()._notify_vendor('mail_template_otm_submission_submitted')

    def action_start_review(self):
        self._check_manager()
        self.filtered(lambda s: s.state == 'submitted').write({
            'state': 'under_review',
            'review_user_id': self.env.user.id,
        })

    def action_select(self, qty=None, price=None, notes=None):
        """Mark as selected. Callable from the wizard, backend button or the
        mobile review controller — permission is enforced HERE, server-side."""
        self._check_manager()
        for submission in self:
            if submission.state in ('selected', 'archived'):
                continue
            submission.write({
                'state': 'selected',
                'selected_by_id': self.env.user.id,
                'selected_date': fields.Datetime.now(),
                'selected_qty': qty if qty is not None else submission.selected_qty,
                'negotiated_price': price if price is not None else submission.negotiated_price,
                'selection_notes': notes or submission.selection_notes,
            })
        self._notify_vendor('mail_template_otm_submission_selected')

    def action_reject(self, reason=None):
        self._check_manager()
        self.write({
            'state': 'rejected',
            'rejection_reason': reason or self.env.context.get(
                'otm_rejection_reason') or '',
            'review_user_id': self.env.user.id,
        })
        self._notify_vendor('mail_template_otm_submission_rejected')

    def action_request_changes(self, notes=None):
        self._check_manager()
        self.write({
            'state': 'changes_requested',
            'change_request_notes': notes or self.env.context.get(
                'otm_change_notes') or '',
            'review_user_id': self.env.user.id,
        })
        self._notify_vendor('mail_template_otm_submission_changes')

    def action_send_duplicate_review(self):
        """Flag for internal duplicate review. Deliberately does NOT notify
        the vendor — telling a vendor which images were flagged as
        duplicates would let them learn and evade the detection system.
        Duplicate status is visible to Purchase Managers only, via the
        Duplicate Management screens / mobile review app.
        """
        self._check_manager()
        self.write({'state': 'duplicate_review'})

    def action_archive_submission(self):
        self._check_manager()
        self.write({'state': 'archived', 'active': False})

    def action_reset_draft(self):
        self._check_manager()
        self.write({'state': 'draft'})

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def _notify_vendor(self, template_xmlid):
        template = self.env.ref(
            'otm_vendor_product_selection.%s' % template_xmlid,
            raise_if_not_found=False)
        if not template:
            return
        for submission in self.filtered(lambda s: s.vendor_id.email):
            template.sudo().send_mail(submission.id, force_send=False)

    # ------------------------------------------------------------------
    # Conversion to real product (Rule 13 of the spec)
    # ------------------------------------------------------------------
    def action_create_product(self):
        self._check_manager()
        Product = self.env['product.template']
        for submission in self:
            if submission.state != 'selected':
                raise UserError(self.env._(
                    'Only selected submissions can be converted to '
                    'Odoo products.'))
            if submission.product_tmpl_id:
                raise UserError(self.env._(
                    'Submission %(code)s is already linked to product '
                    '"%(product)s".', code=submission.code,
                    product=submission.product_tmpl_id.display_name))
            main_image = (submission.main_image_id
                          or submission.image_ids.filtered('is_main_image')[:1]
                          or submission.image_ids[:1])
            product = Product.create({
                'name': submission.name,
                'default_code': submission.vendor_sku,
                'type': 'consu',
                'purchase_ok': True,
                'sale_ok': True,
                'list_price': submission.mrp,
                'standard_price': (submission.negotiated_price
                                   or submission.purchase_price),
                'description_sale': submission.name,
                'image_1920': main_image.image_1920 if main_image else False,
                'seller_ids': [(0, 0, {
                    'partner_id': submission.vendor_id.id,
                    'price': (submission.negotiated_price
                              or submission.purchase_price),
                    'min_qty': submission.min_order_qty,
                    'product_code': submission.vendor_sku,
                })],
            })
            submission.product_tmpl_id = product
            submission.message_post(body=self.env._(
                'Converted to Odoo product %(name)s by %(user)s.',
                name=product.display_name, user=self.env.user.name))
        if len(self) == 1 and self.product_tmpl_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'product.template',
                'res_id': self.product_tmpl_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return True

    # ------------------------------------------------------------------
    # Portal helpers
    # ------------------------------------------------------------------
    def _get_portal_url_suffix(self):
        self.ensure_one()
        return '/my/vendor/product/%s' % self.id
