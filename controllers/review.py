# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.
"""Mobile-first Purchase Manager review interface (/purchase/product-review).

SECURITY MODEL
==============
Every route in this controller — the HTML page AND every JSON-RPC data or
action endpoint — re-checks the Purchase Manager group *server-side* with
``_check_manager_or_deny()``.  Hiding buttons in the template is cosmetic
only; a user manually calling any of these URLs without the
``group_otm_vendor_manager`` group receives a 403 / access error.

On top of that, all state-changing calls delegate to the model layer
(``action_select`` / ``action_reject`` / ... on otm.vendor.product.submission
and the review actions on otm.vendor.product.image), which perform their own
``_check_manager()`` / ``_check_review_rights()`` checks.  Authorization is
therefore enforced twice and never depends on the UI.
"""

from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

MANAGER_GROUP = 'otm_vendor_product_selection.group_otm_vendor_manager'
PAGE_SIZE = 24


class OtmProductReviewController(http.Controller):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _check_manager_or_deny(self):
        """Server-side authorization gate used by EVERY route below."""
        user = request.env.user
        if user._is_public() or not user.has_group(MANAGER_GROUP):
            raise Forbidden()

    def _image_url(self, image, size='image_512'):
        return '/web/image/otm.vendor.product.image/%s/%s' % (image.id, size)

    def _submission_card_data(self, submission):
        """Compact JSON payload for one product card (thumbnails only)."""
        main = submission.main_image_id or submission.image_ids[:1]
        return {
            'id': submission.id,
            'name': submission.name,
            'code': submission.code or '',
            'vendor_sku': submission.vendor_sku or '',
            'vendor_id': submission.vendor_id.id,
            'vendor_name': submission.vendor_id.display_name,
            'category': submission.primary_category_id.complete_name or '',
            'purchase_price': submission.purchase_price,
            'mrp': submission.mrp,
            'currency': submission.currency_id.symbol or '',
            'state': submission.state,
            'state_label': dict(
                submission._fields['state']._description_selection(
                    request.env)).get(submission.state, submission.state),
            'has_duplicate': submission.has_duplicate_flag,
            'image_count': submission.image_count,
            'main_image_url': self._image_url(main, 'image_512')
                if main else False,
            # thumbnail list for the swipe gallery (lazy-loaded client side)
            'image_ids': submission.image_ids.ids,
        }

    # ------------------------------------------------------------------
    # Page
    # ------------------------------------------------------------------
    @http.route('/purchase/product-review', type='http', auth='user',
                website=True)
    def review_page(self, **kw):
        self._check_manager_or_deny()
        categories = request.env['otm.vendor.product.category'].search(
            [('active', '=', True)], order='complete_name')
        vendors = request.env['res.partner'].search(
            [('is_otm_vendor', '=', True)], order='name')
        counts = self._status_counts()
        return request.render(
            'otm_vendor_product_selection.review_interface_page', {
                'page_name': 'otm_product_review',
                'categories': categories,
                'vendors': vendors,
                'counts': counts,
            })

    def _status_counts(self):
        Submission = request.env['otm.vendor.product.submission']
        data = Submission._read_group(
            [('state', '!=', 'draft')], groupby=['state'],
            aggregates=['__count'])
        counts = {state: count for state, count in data}
        counts['duplicate_pending'] = request.env[
            'otm.vendor.product.image'].search_count(
                [('duplicate_status', 'in',
                  ('exact_duplicate', 'possible_duplicate', 'similar'))])
        return counts

    # ------------------------------------------------------------------
    # Data endpoints (JSON-RPC)
    # ------------------------------------------------------------------
    @http.route('/purchase/product-review/data', type='jsonrpc',
                auth='user', methods=['POST'])
    def review_data(self, page=1, state='submitted', vendor_id=None,
                    category_id=None, price_min=None, price_max=None,
                    duplicates_only=False, search='', **kw):
        """Paginated product card feed with all mobile filters.

        Filters only use stored fields so the domains stay index-friendly.
        """
        self._check_manager_or_deny()
        Submission = request.env['otm.vendor.product.submission']
        domain = []
        if state and state != 'all':
            domain.append(('state', '=', state))
        else:
            domain.append(('state', '!=', 'draft'))
        if vendor_id:
            domain.append(('vendor_id', '=', int(vendor_id)))
        if category_id:
            # child_of covers parent-category filtering over the hierarchy
            domain.append(
                ('category_ids', 'child_of', int(category_id)))
        if price_min not in (None, ''):
            domain.append(('purchase_price', '>=', float(price_min)))
        if price_max not in (None, ''):
            domain.append(('purchase_price', '<=', float(price_max)))
        if duplicates_only:
            domain.append(('has_duplicate_flag', '=', True))
        if search:
            domain += ['|', '|', ('name', 'ilike', search),
                       ('vendor_sku', 'ilike', search),
                       ('vendor_id.name', 'ilike', search)]

        page = max(int(page), 1)
        total = Submission.search_count(domain)
        submissions = Submission.search(
            domain, order='submit_date desc, id desc',
            limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
        return {
            'total': total,
            'page': page,
            'page_size': PAGE_SIZE,
            'has_more': page * PAGE_SIZE < total,
            'records': [self._submission_card_data(s) for s in submissions],
        }

    @http.route('/purchase/product-review/product/<int:submission_id>',
                type='jsonrpc', auth='user', methods=['POST'])
    def review_product_detail(self, submission_id, **kw):
        self._check_manager_or_deny()
        submission = request.env['otm.vendor.product.submission'].browse(
            submission_id).exists()
        if not submission:
            return {'error': 'not_found'}
        data = self._submission_card_data(submission)
        data.update({
            'description': submission.description or '',
            'material': submission.material or '',
            'color': submission.color or '',
            'size': submission.size or '',
            'available_sizes': submission.available_sizes or '',
            'brand': submission.brand or '',
            'gender': submission.gender or '',
            'season': submission.season or '',
            'style': submission.style or '',
            'min_order_qty': submission.min_order_qty,
            'available_qty': submission.available_qty,
            'vendor_notes': submission.vendor_notes or '',
            'categories': submission.category_ids.mapped('complete_name'),
            'selected_qty': submission.selected_qty,
            'negotiated_price': submission.negotiated_price,
            'selection_notes': submission.selection_notes or '',
            'images': [{
                'id': img.id,
                'thumb_url': self._image_url(img, 'image_256'),
                'url': self._image_url(img, 'image_1024'),
                'full_url': self._image_url(img, 'image_1920'),
                'is_main': img.is_main_image,
                'duplicate_status': img.duplicate_status,
                'similarity_score': img.similarity_score,
            } for img in submission.image_ids],
        })
        return data

    @http.route('/purchase/product-review/duplicates', type='jsonrpc',
                auth='user', methods=['POST'])
    def review_duplicates(self, page=1, **kw):
        """Duplicate comparison feed: new image vs existing match."""
        self._check_manager_or_deny()
        Image = request.env['otm.vendor.product.image']
        domain = [('duplicate_status', 'in',
                   ('exact_duplicate', 'possible_duplicate', 'similar')),
                  ('duplicate_image_id', '!=', False)]
        page = max(int(page), 1)
        total = Image.search_count(domain)
        images = Image.search(domain, order='create_date desc',
                              limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
        records = []
        for img in images:
            existing = img.duplicate_image_id
            records.append({
                'id': img.id,
                'new_url': self._image_url(img, 'image_1024'),
                'new_thumb': self._image_url(img, 'image_512'),
                'new_vendor': img.vendor_id.display_name or '',
                'new_product': img.submission_id.display_name or '',
                'new_date': str(img.create_date or ''),
                'existing_id': existing.id,
                'existing_url': self._image_url(existing, 'image_1024'),
                'existing_thumb': self._image_url(existing, 'image_512'),
                'existing_vendor': existing.vendor_id.display_name or '',
                'existing_product':
                    existing.submission_id.display_name or '',
                'existing_date': str(existing.create_date or ''),
                'similarity_score': img.similarity_score,
                'duplicate_type': img.duplicate_status,
            })
        return {'total': total, 'page': page,
                'has_more': page * PAGE_SIZE < total, 'records': records}

    # ------------------------------------------------------------------
    # Action endpoints (JSON-RPC) — model methods re-check the group
    # ------------------------------------------------------------------
    def _get_submissions_or_error(self, submission_ids):
        ids = [int(i) for i in (submission_ids or [])]
        submissions = request.env['otm.vendor.product.submission'].browse(
            ids).exists()
        if not submissions:
            return None, {'success': False, 'error': 'No products found.'}
        return submissions, None

    @http.route('/purchase/product-review/action/select', type='jsonrpc',
                auth='user', methods=['POST'])
    def action_select(self, submission_ids=None, qty=None, price=None,
                      notes=None, **kw):
        self._check_manager_or_deny()
        submissions, error = self._get_submissions_or_error(submission_ids)
        if error:
            return error
        try:
            qty = float(qty) if qty not in (None, '') else None
            price = float(price) if price not in (None, '') else None
            submissions.action_select(qty=qty, price=price, notes=notes)
        except AccessError:
            raise Forbidden()
        except Exception as exc:  # surfaced to the UI as a toast
            return {'success': False, 'error': str(exc)}
        return {'success': True, 'count': len(submissions)}

    @http.route('/purchase/product-review/action/reject', type='jsonrpc',
                auth='user', methods=['POST'])
    def action_reject(self, submission_ids=None, reason=None, **kw):
        self._check_manager_or_deny()
        submissions, error = self._get_submissions_or_error(submission_ids)
        if error:
            return error
        try:
            submissions.action_reject(reason=reason)
        except AccessError:
            raise Forbidden()
        except Exception as exc:
            return {'success': False, 'error': str(exc)}
        return {'success': True, 'count': len(submissions)}

    @http.route('/purchase/product-review/action/request-changes',
                type='jsonrpc', auth='user', methods=['POST'])
    def action_request_changes(self, submission_ids=None, notes=None, **kw):
        self._check_manager_or_deny()
        submissions, error = self._get_submissions_or_error(submission_ids)
        if error:
            return error
        try:
            submissions.action_request_changes(notes=notes)
        except AccessError:
            raise Forbidden()
        except Exception as exc:
            return {'success': False, 'error': str(exc)}
        return {'success': True, 'count': len(submissions)}

    @http.route('/purchase/product-review/action/start-review',
                type='jsonrpc', auth='user', methods=['POST'])
    def action_start_review(self, submission_ids=None, **kw):
        self._check_manager_or_deny()
        submissions, error = self._get_submissions_or_error(submission_ids)
        if error:
            return error
        try:
            submissions.filtered(
                lambda s: s.state == 'submitted').action_start_review()
        except AccessError:
            raise Forbidden()
        except Exception as exc:
            return {'success': False, 'error': str(exc)}
        return {'success': True, 'count': len(submissions)}

    @http.route('/purchase/product-review/action/duplicate-review',
                type='jsonrpc', auth='user', methods=['POST'])
    def action_send_duplicate_review(self, submission_ids=None, **kw):
        self._check_manager_or_deny()
        submissions, error = self._get_submissions_or_error(submission_ids)
        if error:
            return error
        try:
            submissions.action_send_duplicate_review()
        except AccessError:
            raise Forbidden()
        except Exception as exc:
            return {'success': False, 'error': str(exc)}
        return {'success': True, 'count': len(submissions)}

    @http.route('/purchase/product-review/duplicate/<int:image_id>/<string:decision>',
                type='jsonrpc', auth='user', methods=['POST'])
    def action_duplicate_decision(self, image_id, decision, **kw):
        """decision in: confirm | not_duplicate | keep_both | link_existing"""
        self._check_manager_or_deny()
        image = request.env['otm.vendor.product.image'].browse(
            image_id).exists()
        if not image:
            return {'success': False, 'error': 'Image not found.'}
        handlers = {
            'confirm': image.action_confirm_duplicate,
            'not_duplicate': image.action_not_duplicate,
            'keep_both': image.action_keep_both,
            'link_existing': image.action_link_existing_product,
        }
        if decision not in handlers:
            return {'success': False, 'error': 'Unknown action.'}
        try:
            handlers[decision]()
        except AccessError:
            raise Forbidden()
        except Exception as exc:
            return {'success': False, 'error': str(exc)}
        return {'success': True}
