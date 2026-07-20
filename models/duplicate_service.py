# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.
"""Two-level duplicate image detection.

Level 1 — Exact duplicate
    SHA-256 of the raw (base64-decoded) file bytes, matched via an indexed
    equality search. Cost: one hash + one indexed SELECT per image.

Level 2 — Visual similarity
    64-bit perceptual hashes. If the optional ``imagehash`` library is
    installed it is used (pHash + dHash); otherwise a pure-Pillow dHash and
    average-hash implementation is used, so the module has NO hard external
    dependency beyond Pillow (which Odoo already requires).

    Similarity search is NOT a full scan: the 64-bit dhash is split into
    four 16-bit bands stored in individually indexed columns. Candidate
    images are fetched with an indexed ``OR`` over the bands
    (locality-sensitive banding), then the exact Hamming distance is
    computed in Python over that small candidate set only. By pigeonhole,
    any image within Hamming distance 3 is guaranteed to be found; images
    within the wider "similar" threshold share a band in the overwhelming
    majority of real-world cases. This scales to hundreds of thousands of
    images because the per-upload cost stays proportional to the candidate
    set, not the table size.

Interpretation of results (deliberately conservative — fashion products
legitimately have front/back/side/detail shots that can look alike):
    * exact SHA match          -> ``exact_duplicate`` (blocked from re-storage)
    * distance <= strict thr.  -> ``possible_duplicate`` (manager review)
    * distance <= loose thr.   -> ``similar`` (manager review, informational)
    * otherwise                -> ``new``
Nothing except byte-exact duplicates is ever auto-rejected.
"""

import base64
import hashlib
import io
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

try:
    from PIL import Image as PILImage
except ImportError:  # pragma: no cover - Pillow is a hard Odoo dependency
    PILImage = None
    _logger.warning('Pillow is not available; perceptual hashing disabled.')

try:
    import imagehash as _imagehash
except ImportError:
    _imagehash = None  # optional; pure-Pillow fallback below


PARAM_STRICT = 'otm_vendor_product_selection.duplicate_strict_distance'
PARAM_LOOSE = 'otm_vendor_product_selection.duplicate_similar_distance'
PARAM_MAX_SIZE = 'otm_vendor_product_selection.max_upload_size_mb'
PARAM_SYNC_LIMIT = 'otm_vendor_product_selection.sync_processing_limit'

ALLOWED_EXTENSIONS = ('jpg', 'jpeg', 'png', 'webp')
ALLOWED_MIMETYPES = ('image/jpeg', 'image/png', 'image/webp')


class OtmVendorDuplicateService(models.AbstractModel):
    _name = 'otm.vendor.duplicate.service'
    _description = 'Vendor Image Duplicate Detection Service'

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(
                key, default))
        except (TypeError, ValueError):
            return default

    @api.model
    def get_thresholds(self):
        return {
            'strict': self._get_int_param(PARAM_STRICT, 6),
            'loose': self._get_int_param(PARAM_LOOSE, 12),
        }

    @api.model
    def get_max_upload_bytes(self):
        return self._get_int_param(PARAM_MAX_SIZE, 10) * 1024 * 1024

    @api.model
    def get_sync_limit(self):
        """Uploads with at most this many files are analysed synchronously
        inside the HTTP request; larger batches are left ``pending`` for the
        cron worker so the request never blocks (Rule 16 of the spec)."""
        return self._get_int_param(PARAM_SYNC_LIMIT, 20)

    # ------------------------------------------------------------------
    # Hash computation
    # ------------------------------------------------------------------
    @api.model
    def _compute_hashes_for_image(self, b64_data):
        """Return a dict of hash field values for a base64 image payload."""
        if not b64_data:
            return {}
        try:
            raw = base64.b64decode(b64_data)
        except Exception:
            return {}
        vals = {'sha256_hash': hashlib.sha256(raw).hexdigest()}
        dhash_hex = ahash_hex = None
        if PILImage is not None:
            try:
                with PILImage.open(io.BytesIO(raw)) as img:
                    img = img.convert('L')
                    if _imagehash is not None:
                        dhash_hex = str(_imagehash.dhash(img))
                        ahash_hex = str(_imagehash.average_hash(img))
                    else:
                        dhash_hex = self._pillow_dhash(img)
                        ahash_hex = self._pillow_ahash(img)
            except Exception as exc:
                _logger.warning('Perceptual hash failed: %s', exc)
        if dhash_hex:
            dhash_hex = dhash_hex.zfill(16)
            vals.update({
                'perceptual_hash': dhash_hex,
                'dhash_c1': dhash_hex[0:4],
                'dhash_c2': dhash_hex[4:8],
                'dhash_c3': dhash_hex[8:12],
                'dhash_c4': dhash_hex[12:16],
            })
        if ahash_hex:
            vals['average_hash'] = ahash_hex.zfill(16)
        return vals

    @staticmethod
    def _pillow_dhash(gray_img):
        """Pure-Pillow 64-bit difference hash (row-wise gradient, 9x8)."""
        small = gray_img.resize((9, 8), PILImage.LANCZOS)
        pixels = list(small.getdata())
        bits = 0
        for row in range(8):
            for col in range(8):
                left = pixels[row * 9 + col]
                right = pixels[row * 9 + col + 1]
                bits = (bits << 1) | (1 if left > right else 0)
        return '%016x' % bits

    @staticmethod
    def _pillow_ahash(gray_img):
        """Pure-Pillow 64-bit average hash (8x8 mean threshold)."""
        small = gray_img.resize((8, 8), PILImage.LANCZOS)
        pixels = list(small.getdata())
        avg = sum(pixels) / 64.0
        bits = 0
        for px in pixels:
            bits = (bits << 1) | (1 if px >= avg else 0)
        return '%016x' % bits

    @staticmethod
    def _hamming(hex_a, hex_b):
        try:
            return bin(int(hex_a, 16) ^ int(hex_b, 16)).count('1')
        except (TypeError, ValueError):
            return 64

    # ------------------------------------------------------------------
    # Validation helpers (used by controllers)
    # ------------------------------------------------------------------
    @api.model
    def validate_upload(self, filename, mimetype, size_bytes):
        """Return an error string, or False when the upload is acceptable."""
        ext = (filename or '').rsplit('.', 1)[-1].lower()
        if ext not in ALLOWED_EXTENSIONS and mimetype not in ALLOWED_MIMETYPES:
            return self.env._(
                'Unsupported file type. Allowed: JPG, JPEG, PNG, WEBP.')
        max_bytes = self.get_max_upload_bytes()
        if size_bytes and size_bytes > max_bytes:
            return self.env._(
                'File too large (max %(mb)s MB).',
                mb=max_bytes // (1024 * 1024))
        return False

    # ------------------------------------------------------------------
    # Duplicate analysis
    # ------------------------------------------------------------------
    @api.model
    def analyse_images(self, images):
        """Run both duplicate-detection levels for the given image records.

        Idempotent: only records in ``process_state = pending`` are analysed
        (prevents the same upload from being processed twice, e.g. by a
        concurrent cron run right after a synchronous request analysis).
        """
        Image = self.env['otm.vendor.product.image']
        thresholds = self.get_thresholds()
        for image in images.filtered(lambda i: i.process_state == 'pending'):
            try:
                vals = self._analyse_single(Image, image, thresholds)
                vals['process_state'] = 'done'
                image.write(vals)
            except Exception as exc:
                _logger.exception(
                    'Duplicate analysis failed for image %s', image.id)
                image.write({'process_state': 'error',
                             'process_error': str(exc)})
                if image.batch_id:
                    image.batch_id._log_error(
                        'Image %s (%s): %s' % (image.id, image.name, exc))
        # roll batch states forward
        for batch in images.batch_id:
            pending = batch.image_ids.filtered(
                lambda i: i.process_state == 'pending')
            if not pending and batch.state in ('uploading', 'processing'):
                failed = batch.image_ids.filtered(
                    lambda i: i.process_state == 'error')
                batch.state = 'failed' if failed and not (
                    batch.image_ids - failed) else 'done'

    def _analyse_single(self, Image, image, thresholds):
        # ---- Level 1: exact SHA-256 duplicate --------------------------
        if image.sha256_hash:
            exact = Image.search([
                ('sha256_hash', '=', image.sha256_hash),
                ('id', '!=', image.id),
                ('duplicate_status', '!=', 'rejected_duplicate'),
            ], order='id', limit=1)
            if exact:
                return {
                    'duplicate_status': 'exact_duplicate',
                    'duplicate_image_id': exact.id,
                    'similarity_score': 100.0,
                }
        # ---- Level 2: perceptual similarity ----------------------------
        if image.perceptual_hash:
            # Banded candidate retrieval: indexed OR over the 4 hash bands.
            candidates = Image.search([
                ('id', '!=', image.id),
                ('perceptual_hash', '!=', False),
                ('duplicate_status', 'not in',
                 ('rejected_duplicate', 'exact_duplicate')),
                '|', '|', '|',
                ('dhash_c1', '=', image.dhash_c1),
                ('dhash_c2', '=', image.dhash_c2),
                ('dhash_c3', '=', image.dhash_c3),
                ('dhash_c4', '=', image.dhash_c4),
            ], limit=500)
            best, best_dist = None, 65
            for cand in candidates:
                dist = self._hamming(image.perceptual_hash,
                                     cand.perceptual_hash)
                if dist < best_dist:
                    best, best_dist = cand, dist
            if best and best_dist <= thresholds['strict']:
                return {
                    'duplicate_status': 'possible_duplicate',
                    'duplicate_image_id': best.id,
                    'similarity_score': round((64 - best_dist) / 64.0 * 100, 1),
                }
            if best and best_dist <= thresholds['loose']:
                return {
                    'duplicate_status': 'similar',
                    'duplicate_image_id': best.id,
                    'similarity_score': round((64 - best_dist) / 64.0 * 100, 1),
                }
        return {'duplicate_status': 'new', 'similarity_score': 0.0}

    # ------------------------------------------------------------------
    # Cron worker for large batches
    # ------------------------------------------------------------------
    @api.model
    def _cron_process_pending_images(self, batch_size=100):
        """Background worker: analyse pending images in bounded batches so a
        250-image bulk upload never blocks an HTTP request. Re-triggers
        itself while work remains."""
        Image = self.env['otm.vendor.product.image']
        pending = Image.search(
            [('process_state', '=', 'pending')],
            order='id', limit=batch_size)
        if not pending:
            return
        pending.batch_id.filtered(
            lambda b: b.state == 'uploading').write({'state': 'processing'})
        self.analyse_images(pending)
        if Image.search_count([('process_state', '=', 'pending')], limit=1):
            self.env.ref(
                'otm_vendor_product_selection.ir_cron_process_pending_images'
            )._trigger(at=fields.Datetime.now())
