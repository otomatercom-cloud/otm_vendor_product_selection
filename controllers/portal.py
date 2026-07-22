# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.

import base64
import json

from odoo import fields, http
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

SUBMISSION_STATES = [
    'draft', 'submitted', 'under_review', 'duplicate_review',
    'changes_requested', 'selected', 'rejected',
]


class OtmVendorPortal(CustomerPortal):
    """Vendor portal (/my/vendor).

    SECURITY MODEL
    Every route resolves the vendor from the LOGGED-IN USER (never from a
    request parameter) via ``res.partner._otm_get_vendor_for_user`` and then
    only browses records already filtered by that vendor. Record rules
    (vendor_record_rules.xml) provide a second, ORM-level fence, and the
    submission model's write() whitelist provides a third — so even a
    hand-crafted RPC/controller call cannot read or alter another vendor's
    data or approval fields.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_vendor(self):
        return request.env['res.partner']._otm_get_vendor_for_user(
            request.env.user)

    def _get_vendor_or_403(self):
        vendor = self._get_vendor()
        if not vendor or not vendor.otm_vendor_active:
            raise AccessError(request.env._(
                'Your account is not linked to an active vendor.'))
        return vendor

    def _get_own_submission(self, vendor, submission_id):
        submission = request.env['otm.vendor.product.submission'].search([
            ('id', '=', submission_id),
            ('vendor_id', '=', vendor.id),
        ], limit=1)
        if not submission:
            raise request.not_found()
        return submission

    def _submission_counts(self, vendor):
        Submission = request.env['otm.vendor.product.submission']
        grouped = dict(Submission._read_group(
            domain=[('vendor_id', '=', vendor.id)],
            groupby=['state'], aggregates=['__count']))
        return {
            'total': sum(grouped.values()),
            'draft': grouped.get('draft', 0),
            'under_review': (grouped.get('submitted', 0)
                             + grouped.get('under_review', 0)
                             + grouped.get('duplicate_review', 0)),
            'selected': grouped.get('selected', 0),
            'rejected': grouped.get('rejected', 0),
            'changes_requested': grouped.get('changes_requested', 0),
        }

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'otm_submission_count' in counters:
            vendor = self._get_vendor()
            values['otm_submission_count'] = (
                request.env['otm.vendor.product.submission'].search_count(
                    [('vendor_id', '=', vendor.id)]) if vendor else 0)
        return values

    def _portal_categories(self):
        return request.env['otm.vendor.product.category'].sudo().search(
            [('active', '=', True)], order='complete_name')

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    @http.route('/my/vendor', type='http', auth='user', website=True)
    def vendor_dashboard(self, **kw):
        vendor = self._get_vendor_or_403()
        values = {
            'page_name': 'otm_vendor_dashboard',
            'vendor': vendor,
            'counts': self._submission_counts(vendor),
            'recent_batches': request.env['otm.vendor.upload.batch'].search(
                [('vendor_id', '=', vendor.id)], limit=5),
        }
        return request.render(
            'otm_vendor_product_selection.portal_vendor_dashboard', values)

    # ------------------------------------------------------------------
    # Product list / detail
    # ------------------------------------------------------------------
    @http.route(['/my/vendor/products', '/my/vendor/products/page/<int:page>'],
                type='http', auth='user', website=True)
    def vendor_products(self, page=1, filterby='all', search='', **kw):
        vendor = self._get_vendor_or_403()
        Submission = request.env['otm.vendor.product.submission']
        domain = [('vendor_id', '=', vendor.id)]
        searchbar_filters = {
            'all': {'label': request.env._('All'), 'domain': []},
            'draft': {'label': request.env._('Draft'),
                      'domain': [('state', '=', 'draft')]},
            'review': {'label': request.env._('Under Review'),
                       'domain': [('state', 'in', ('submitted', 'under_review',
                                                   'duplicate_review'))]},
            'changes': {'label': request.env._('Changes Requested'),
                        'domain': [('state', '=', 'changes_requested')]},
            'selected': {'label': request.env._('Selected'),
                         'domain': [('state', '=', 'selected')]},
            'rejected': {'label': request.env._('Rejected'),
                         'domain': [('state', '=', 'rejected')]},
        }
        if filterby not in searchbar_filters:
            filterby = 'all'
        domain += searchbar_filters[filterby]['domain']
        if search:
            domain += ['|', ('name', 'ilike', search),
                       ('vendor_sku', 'ilike', search)]

        total = Submission.search_count(domain)
        pager = portal_pager(
            url='/my/vendor/products',
            url_args={'filterby': filterby, 'search': search},
            total=total, page=page, step=12)
        submissions = Submission.search(
            domain, order='create_date desc', limit=12,
            offset=pager['offset'])
        values = {
            'page_name': 'otm_vendor_products',
            'vendor': vendor,
            'submissions': submissions,
            'pager': pager,
            'searchbar_filters': searchbar_filters,
            'filterby': filterby,
            'search': search,
        }
        return request.render(
            'otm_vendor_product_selection.portal_vendor_products', values)

    @http.route('/my/vendor/product/<int:submission_id>', type='http',
                auth='user', website=True)
    def vendor_product_detail(self, submission_id, **kw):
        vendor = self._get_vendor_or_403()
        submission = self._get_own_submission(vendor, submission_id)
        values = {
            'page_name': 'otm_vendor_product_detail',
            'vendor': vendor,
            'submission': submission,
            'categories': self._portal_categories(),
            'editable': submission.state in ('draft', 'changes_requested'),
            'error': kw.get('error'),
        }
        return request.render(
            'otm_vendor_product_selection.portal_vendor_product_detail', values)

    # ------------------------------------------------------------------
    # Create / edit / submit
    # ------------------------------------------------------------------
    @http.route('/my/vendor/product/new', type='http', auth='user',
                website=True, methods=['GET'])
    def vendor_product_new(self, **kw):
        vendor = self._get_vendor_or_403()
        values = {
            'page_name': 'otm_vendor_product_new',
            'vendor': vendor,
            'submission': request.env['otm.vendor.product.submission'],
            'categories': self._portal_categories(),
            'editable': True,
        }
        return request.render(
            'otm_vendor_product_selection.portal_vendor_product_form', values)

    def _extract_submission_vals(self, post):
        vals = {}
        for field_name in ('name', 'vendor_sku', 'material', 'color', 'size',
                           'available_sizes', 'brand', 'style',
                           'vendor_notes', 'gender', 'season'):
            if field_name in post:
                vals[field_name] = post.get(field_name) or False
        for field_name in ('purchase_price', 'mrp', 'min_order_qty',
                           'available_qty'):
            if post.get(field_name):
                try:
                    vals[field_name] = float(post[field_name])
                except ValueError:
                    pass
        if post.get('description'):
            vals['description'] = post['description']
        if post.get('primary_category_id'):
            vals['primary_category_id'] = int(post['primary_category_id'])
        category_ids = request.httprequest.form.getlist('category_ids')
        if category_ids:
            vals['category_ids'] = [(6, 0, [int(c) for c in category_ids])]
        return vals

    @http.route('/my/vendor/product/create', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def vendor_product_create(self, **post):
        vendor = self._get_vendor_or_403()
        vals = self._extract_submission_vals(post)
        if not vals.get('name'):
            return request.redirect('/my/vendor/product/new')
        # vendor_id/state are forced inside create() for portal users
        submission = request.env['otm.vendor.product.submission'].create(vals)
        # Attach any images selected on the same form, if the browser sent
        # any — the "images" file input is optional on this page.
        files = request.httprequest.files.getlist('images')
        for file_storage in files:
            if file_storage and file_storage.filename:
                self._handle_image_upload(
                    vendor, file_storage, submission=submission)
        return request.redirect('/my/vendor/product/%s' % submission.id)

    @http.route('/my/vendor/product/<int:submission_id>/update', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def vendor_product_update(self, submission_id, **post):
        vendor = self._get_vendor_or_403()
        submission = self._get_own_submission(vendor, submission_id)
        # write() enforces state + field whitelist for portal users
        submission.write(self._extract_submission_vals(post))
        return request.redirect('/my/vendor/product/%s' % submission.id)

    @http.route('/my/vendor/product/<int:submission_id>/submit', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def vendor_product_submit(self, submission_id, **post):
        vendor = self._get_vendor_or_403()
        submission = self._get_own_submission(vendor, submission_id)
        try:
            submission.action_submit()
        except Exception as exc:
            return request.redirect(
                '/my/vendor/product/%s?error=%s' % (submission.id, exc))
        return request.redirect('/my/vendor/product/%s' % submission.id)

    # ------------------------------------------------------------------
    # Image upload (single product) — one request per file so mobile
    # uploads stream progressively and huge payloads are never built
    # in memory at once.
    # ------------------------------------------------------------------
    def _handle_image_upload(self, vendor, file_storage, submission=None,
                             batch=None, is_main=False):
        service = request.env['otm.vendor.duplicate.service']
        data = file_storage.read()
        error = service.validate_upload(
            file_storage.filename, file_storage.mimetype, len(data))
        if error:
            return {'success': False, 'error': error,
                    'filename': file_storage.filename}
        image = request.env['otm.vendor.product.image'].create({
            'name': file_storage.filename,
            'image_1920': base64.b64encode(data),
            'submission_id': submission.id if submission else False,
            'batch_id': batch.id if batch else False,
            'vendor_id': vendor.id,
            'is_main_image': is_main,
        })
        return {'success': True, 'image_id': image.id,
                'filename': file_storage.filename}

    @http.route('/my/vendor/product/<int:submission_id>/image/upload',
                type='http', auth='user', website=True, methods=['POST'],
                csrf=True)
    def vendor_product_image_upload(self, submission_id, **post):
        vendor = self._get_vendor_or_403()
        submission = self._get_own_submission(vendor, submission_id)
        if submission.state not in ('draft', 'changes_requested'):
            return request.make_json_response(
                {'success': False,
                 'error': request.env._('This product can no longer be edited.')})
        results = []
        files = request.httprequest.files.getlist('images')
        for file_storage in files:
            results.append(self._handle_image_upload(
                vendor, file_storage, submission=submission))
        # Run duplicate analysis now so it's ready for Purchase Managers —
        # but deliberately never send the result back to the vendor. A
        # vendor learning which images get flagged would let them tweak
        # and re-upload to dodge detection, so this stays manager-only
        # (Duplicate Management / mobile review app).
        images = request.env['otm.vendor.product.image'].browse(
            [r['image_id'] for r in results if r.get('image_id')])
        service = request.env['otm.vendor.duplicate.service']
        if len(images) <= service.get_sync_limit():
            service.sudo().analyse_images(images.sudo())
        return request.make_json_response({'success': True, 'results': results})

    @http.route('/my/vendor/image/<int:image_id>/delete', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def vendor_image_delete(self, image_id, **post):
        vendor = self._get_vendor_or_403()
        image = request.env['otm.vendor.product.image'].search([
            ('id', '=', image_id), ('vendor_id', '=', vendor.id)], limit=1)
        if image and (not image.submission_id
                      or image.submission_id.state in ('draft',
                                                       'changes_requested')):
            image.unlink()
            return request.make_json_response({'success': True})
        return request.make_json_response(
            {'success': False,
             'error': request.env._('Image cannot be removed.')})

    # ------------------------------------------------------------------
    # Bulk upload
    # ------------------------------------------------------------------
    @http.route('/my/vendor/upload', type='http', auth='user', website=True)
    def vendor_bulk_upload(self, **kw):
        vendor = self._get_vendor_or_403()
        drafts = request.env['otm.vendor.product.submission'].search([
            ('vendor_id', '=', vendor.id),
            ('state', 'in', ('draft', 'changes_requested'))])
        values = {
            'page_name': 'otm_vendor_bulk_upload',
            'vendor': vendor,
            'draft_submissions': drafts,
            'categories': self._portal_categories(),
            'max_upload_mb': request.env['otm.vendor.duplicate.service']
                .get_max_upload_bytes() // (1024 * 1024),
        }
        return request.render(
            'otm_vendor_product_selection.portal_vendor_bulk_upload', values)

    @http.route('/my/vendor/upload/batch/create', type='jsonrpc',
                auth='user', methods=['POST'])
    def vendor_batch_create(self, **kw):
        vendor = self._get_vendor_or_403()
        batch = request.env['otm.vendor.upload.batch'].create({
            'vendor_id': vendor.id,
            'state': 'uploading',
        })
        return {'batch_id': batch.id, 'batch_name': batch.name}

    @http.route('/my/vendor/upload/batch/<int:batch_id>/image', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def vendor_batch_image_upload(self, batch_id, submission_id=None, **post):
        vendor = self._get_vendor_or_403()
        batch = request.env['otm.vendor.upload.batch'].search([
            ('id', '=', batch_id), ('vendor_id', '=', vendor.id)], limit=1)
        if not batch or batch.state not in ('draft', 'uploading'):
            return request.make_json_response(
                {'success': False,
                 'error': request.env._('Invalid upload batch.')})
        submission = None
        if submission_id:
            submission = self._get_own_submission(vendor, int(submission_id))
        results = []
        for file_storage in request.httprequest.files.getlist('images'):
            results.append(self._handle_image_upload(
                vendor, file_storage, submission=submission, batch=batch))
        return request.make_json_response({'success': True, 'results': results})

    @http.route('/my/vendor/upload/batch/<int:batch_id>/finish',
                type='jsonrpc', auth='user', methods=['POST'])
    def vendor_batch_finish(self, batch_id, **kw):
        vendor = self._get_vendor_or_403()
        batch = request.env['otm.vendor.upload.batch'].search([
            ('id', '=', batch_id), ('vendor_id', '=', vendor.id)], limit=1)
        if not batch:
            return {'success': False}
        service = request.env['otm.vendor.duplicate.service']
        pending = batch.image_ids.filtered(
            lambda i: i.process_state == 'pending')
        if len(pending) <= service.get_sync_limit():
            # small batch: analyse now, inside this request
            service.sudo().analyse_images(pending.sudo())
        else:
            # large batch: leave for the cron worker; never block the request
            batch.state = 'processing'
            cron = request.env.ref(
                'otm_vendor_product_selection.ir_cron_process_pending_images',
                raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger(at=fields.Datetime.now())
        return {
            'success': True,
            'state': batch.state,
            'total': batch.total_images,
            'new': batch.new_images,
        }

    @http.route('/my/vendor/upload/batch/<int:batch_id>/images',
                type='jsonrpc', auth='user', methods=['POST'])
    def vendor_batch_images(self, batch_id, **kw):
        """Per-image status for a batch, so the bulk-upload page can render
        a grouping grid once uploads/duplicate analysis finish — without
        the vendor having to visit each image/product individually.
        """
        vendor = self._get_vendor_or_403()
        batch = request.env['otm.vendor.upload.batch'].search([
            ('id', '=', batch_id), ('vendor_id', '=', vendor.id)], limit=1)
        if not batch:
            return {'success': False, 'error': 'Batch not found.'}
        images = []
        for img in batch.image_ids.sorted('id'):
            images.append({
                'id': img.id,
                'thumb_url': '/web/image/otm.vendor.product.image/%s/image_256'
                    % img.id,
                'process_state': img.process_state,
                'assigned': bool(img.submission_id),
                'submission_name': img.submission_id.name or '',
            })
        return {'success': True, 'state': batch.state, 'images': images}

    @http.route('/my/vendor/product/quick-create', type='jsonrpc',
                auth='user', methods=['POST'])
    def vendor_quick_product_create(self, image_ids=None, name=None,
                                    purchase_price=None,
                                    primary_category_id=None, **kw):
        """Create one product submission from a set of already-uploaded,
        unassigned images in a single call — the fast path for vendors who
        bulk-upload photos first and only want to name/price/categorise a
        group of images, instead of the full new-product form per item.
        """
        vendor = self._get_vendor_or_403()
        if not name or not str(name).strip():
            return {'success': False, 'error': 'Product name is required.'}
        ids = [int(i) for i in (image_ids or [])]
        if not ids:
            return {'success': False,
                    'error': 'Select at least one image for this product.'}
        # Ownership check: every image must belong to this vendor and not
        # already be attached to a different submission.
        images = request.env['otm.vendor.product.image'].search([
            ('id', 'in', ids), ('vendor_id', '=', vendor.id),
            ('submission_id', '=', False)])
        if len(images) != len(ids):
            return {'success': False,
                    'error': 'Some images are unavailable or already '
                             'assigned to another product.'}
        vals = {'name': name.strip(), 'image_ids': [(6, 0, images.ids)]}
        if purchase_price not in (None, ''):
            try:
                vals['purchase_price'] = float(purchase_price)
            except ValueError:
                pass
        if primary_category_id not in (None, ''):
            try:
                category_id = int(primary_category_id)
            except ValueError:
                category_id = None
            if category_id and request.env[
                    'otm.vendor.product.category'].sudo().browse(
                        category_id).exists():
                vals['primary_category_id'] = category_id
                vals['category_ids'] = [(6, 0, [category_id])]
        try:
            submission = request.env[
                'otm.vendor.product.submission'].create(vals)
        except AccessError as exc:
            return {'success': False, 'error': str(exc)}
        return {'success': True, 'submission_id': submission.id,
                'submission_name': submission.name}

    # ------------------------------------------------------------------
    # Simple bulk upload (no JavaScript dependency)
    #
    # The JS-driven bulk upload above needs the frontend asset bundle to
    # be current; if a vendor's browser is stuck on a stale cached bundle
    # (a real, if uncommon, Odoo deployment issue — not something this
    # module can prevent), that page's Upload button can appear to do
    # nothing. This flow is a fallback that never depends on custom JS:
    # a native <input type="file" required> plus a normal <button
    # type="submit">, so the browser's own HTML5 validation — not our
    # JavaScript — is what enables/blocks submission. Every step below
    # is a full-page POST + redirect.
    # ------------------------------------------------------------------
    @http.route('/my/vendor/upload/simple', type='http', auth='user',
                website=True)
    def vendor_simple_bulk_upload(self, **kw):
        vendor = self._get_vendor_or_403()
        values = {
            'page_name': 'otm_vendor_simple_bulk_upload',
            'vendor': vendor,
            'max_upload_mb': request.env['otm.vendor.duplicate.service']
                .get_max_upload_bytes() // (1024 * 1024),
        }
        return request.render(
            'otm_vendor_product_selection.portal_vendor_simple_bulk_upload',
            values)

    @http.route('/my/vendor/upload/simple/submit', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def vendor_simple_bulk_upload_submit(self, **post):
        vendor = self._get_vendor_or_403()
        files = request.httprequest.files.getlist('images')
        files = [f for f in files if f and f.filename]
        if not files:
            return request.redirect('/my/vendor/upload/simple?error=nofiles')

        batch = request.env['otm.vendor.upload.batch'].create({
            'vendor_id': vendor.id,
            'state': 'uploading',
        })
        for file_storage in files:
            self._handle_image_upload(vendor, file_storage, batch=batch)

        service = request.env['otm.vendor.duplicate.service']
        pending = batch.image_ids.filtered(
            lambda i: i.process_state == 'pending')
        if len(pending) <= service.get_sync_limit():
            service.sudo().analyse_images(pending.sudo())
        else:
            batch.state = 'processing'
            cron = request.env.ref(
                'otm_vendor_product_selection.ir_cron_process_pending_images',
                raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger(at=fields.Datetime.now())

        return request.redirect(
            '/my/vendor/upload/simple/group?batch=%s' % batch.id)

    @http.route('/my/vendor/upload/simple/group', type='http', auth='user',
                website=True)
    def vendor_simple_bulk_group(self, batch=None, **kw):
        vendor = self._get_vendor_or_403()
        images = request.env['otm.vendor.product.image'].search([
            ('vendor_id', '=', vendor.id), ('submission_id', '=', False)],
            order='id desc')
        values = {
            'page_name': 'otm_vendor_simple_bulk_group',
            'vendor': vendor,
            'images': images,
            'categories': self._portal_categories(),
            'just_uploaded_batch': batch,
        }
        return request.render(
            'otm_vendor_product_selection.portal_vendor_simple_bulk_group',
            values)

    @http.route('/my/vendor/upload/simple/create-product', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def vendor_simple_bulk_create_product(self, **post):
        vendor = self._get_vendor_or_403()
        image_ids = request.httprequest.form.getlist('image_ids')
        name = (post.get('name') or '').strip()
        if not image_ids or not name:
            return request.redirect(
                '/my/vendor/upload/simple/group?error=missing')

        images = request.env['otm.vendor.product.image'].search([
            ('id', 'in', [int(i) for i in image_ids]),
            ('vendor_id', '=', vendor.id), ('submission_id', '=', False)])
        if not images:
            return request.redirect(
                '/my/vendor/upload/simple/group?error=missing')

        vals = {'name': name, 'image_ids': [(6, 0, images.ids)]}
        if post.get('purchase_price'):
            try:
                vals['purchase_price'] = float(post['purchase_price'])
            except ValueError:
                pass
        if post.get('primary_category_id'):
            vals['primary_category_id'] = int(post['primary_category_id'])
            vals['category_ids'] = [(6, 0, [int(post['primary_category_id'])])]

        request.env['otm.vendor.product.submission'].create(vals)
        return request.redirect('/my/vendor/upload/simple/group?created=1')

    @http.route(['/my/vendor/batches', '/my/vendor/batches/page/<int:page>'],
                type='http', auth='user', website=True)
    def vendor_batches(self, page=1, **kw):
        vendor = self._get_vendor_or_403()
        Batch = request.env['otm.vendor.upload.batch']
        domain = [('vendor_id', '=', vendor.id)]
        total = Batch.search_count(domain)
        pager = portal_pager(url='/my/vendor/batches', total=total,
                             page=page, step=20)
        batches = Batch.search(domain, order='create_date desc',
                               limit=20, offset=pager['offset'])
        values = {
            'page_name': 'otm_vendor_batches',
            'vendor': vendor,
            'batches': batches,
            'pager': pager,
        }
        return request.render(
            'otm_vendor_product_selection.portal_vendor_batches', values)

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------
    @http.route('/my/vendor/profile', type='http', auth='user', website=True)
    def vendor_profile(self, **kw):
        vendor = self._get_vendor_or_403()
        return request.render(
            'otm_vendor_product_selection.portal_vendor_profile', {
                'page_name': 'otm_vendor_profile',
                'vendor': vendor,
            })
