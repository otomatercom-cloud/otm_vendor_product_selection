# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.
"""Design-level (semantic) duplicate detection.

The perceptual hash in ``duplicate_service`` only recognises the *same
photograph* (resized / recompressed). Vendors, however, re-send the same
dress photographed from another angle, on another model, or flat-lay. This
service turns every image into an embedding vector with a CLIP vision model
(ONNX) so that photos of the same *design* land close together, and stores
the closest earlier images as ``otm.vendor.design.match`` records with a
design-match percentage.

Operational notes
-----------------
* ``onnxruntime`` and ``numpy`` are OPTIONAL. They are deliberately NOT in
  the manifest ``external_dependencies`` (that would block the whole module
  from loading when missing). Without them the module works exactly as
  before and images simply stay ``embed_state = 'pending'``.
* The model file is looked up at the configured path
  (``otm_vendor_product_selection.design_model_path``) or at
  ``<data_dir>/otm_vendor_design_model/clip_vision.onnx``. If it is missing,
  the cron downloads it once from ``design_model_url`` (never inside a web
  request). Offline servers can copy the file there by hand.
* Only images that are NOT in the same product submission and are OLDER
  (lower id) are compared, so the later upload is the one flagged and the
  front/back/side shots of one product never flag each other.
* Nothing is auto-rejected; the Purchase Manager decides.
"""

import base64
import io
import logging
import os
import threading
import time
import urllib.request

from odoo import api, fields, models, tools
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None
try:
    import onnxruntime as ort
except ImportError:  # pragma: no cover
    ort = None
try:
    from PIL import Image as PILImage, ImageOps
except ImportError:  # pragma: no cover
    PILImage = ImageOps = None

PARAM_MODEL_PATH = 'otm_vendor_product_selection.design_model_path'
PARAM_MODEL_URL = 'otm_vendor_product_selection.design_model_url'
PARAM_FLAG = 'otm_vendor_product_selection.design_flag_score'
PARAM_SIMILAR = 'otm_vendor_product_selection.design_similar_score'
DEFAULT_MODEL_URL = (
    'https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/'
    'onnx/vision_model_quantized.onnx')
CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)
INPUT_SIZE = 224
TOP_MATCHES = 5
DOWNLOAD_RETRY_SECONDS = 3600

# One loaded ONNX session per worker process.
_STATE = {'session': None, 'path': None, 'last_download_try': 0.0}
_LOCK = threading.Lock()


class OtmVendorDesignService(models.AbstractModel):
    _name = 'otm.vendor.design.service'
    _description = 'Vendor Design Similarity Service'

    # ------------------------------------------------------------------
    # Configuration / model loading
    # ------------------------------------------------------------------
    @api.model
    def _get_float_param(self, key, default):
        try:
            return float(self.env['ir.config_parameter'].sudo().get_param(
                key, default))
        except (TypeError, ValueError):
            return float(default)

    @api.model
    def get_design_thresholds(self):
        """Design match percentages: ``flag`` -> possible duplicate,
        ``similar`` -> informational 'similar'."""
        return {
            'flag': self._get_float_param(PARAM_FLAG, 88),
            'similar': self._get_float_param(PARAM_SIMILAR, 80),
        }

    @api.model
    def _libs_available(self):
        return bool(np is not None and ort is not None
                    and PILImage is not None)

    @api.model
    def _model_path(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_MODEL_PATH)
        if param:
            return param
        return os.path.join(
            tools.config['data_dir'], 'otm_vendor_design_model',
            'clip_vision.onnx')

    @api.model
    def _download_model(self, path):
        url = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_MODEL_URL) or DEFAULT_MODEL_URL
        now = time.time()
        if now - _STATE['last_download_try'] < DOWNLOAD_RETRY_SECONDS:
            return False
        _STATE['last_download_try'] = now
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + '.part'
        try:
            _logger.info('Downloading design model from %s', url)
            with urllib.request.urlopen(url, timeout=120) as resp, \
                    open(tmp_path, 'wb') as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            if os.path.getsize(tmp_path) < 1024 * 1024:
                raise ValueError('downloaded file is too small')
            os.replace(tmp_path, path)
            return True
        except Exception as exc:
            _logger.warning(
                'Design model download failed (%s). Copy the ONNX file to '
                '%s manually or set %s.', exc, path, PARAM_MODEL_PATH)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return False

    @api.model
    def _get_session(self, allow_download=False):
        """Return a loaded ONNX session or ``None`` when unavailable."""
        if not self._libs_available():
            _logger.info('onnxruntime/numpy/Pillow missing: design matching '
                         'is disabled.')
            return None
        path = self._model_path()
        with _LOCK:
            if _STATE['session'] is not None and _STATE['path'] == path:
                return _STATE['session']
            if not os.path.exists(path):
                if not allow_download or not self._download_model(path):
                    return None
            try:
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                session = ort.InferenceSession(
                    path, sess_options=opts,
                    providers=['CPUExecutionProvider'])
            except Exception as exc:
                _logger.warning('Cannot load design model %s: %s', path, exc)
                return None
            _STATE['session'] = session
            _STATE['path'] = path
            return session

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------
    @api.model
    def _preprocess(self, raw):
        """Pad to a square on white (so the whole garment stays visible,
        unlike CLIP's centre-crop), resize to 224 and normalise."""
        img = PILImage.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGBA')
            background = PILImage.new('RGBA', img.size, (255, 255, 255, 255))
            background.alpha_composite(img)
            img = background
        img = img.convert('RGB')
        side = max(img.size)
        canvas = PILImage.new('RGB', (side, side), (255, 255, 255))
        canvas.paste(img, ((side - img.size[0]) // 2,
                           (side - img.size[1]) // 2))
        canvas = canvas.resize((INPUT_SIZE, INPUT_SIZE), PILImage.BICUBIC)
        arr = np.asarray(canvas, dtype=np.float32) / 255.0
        arr = (arr - np.array(CLIP_MEAN, dtype=np.float32)) / np.array(
            CLIP_STD, dtype=np.float32)
        return arr.transpose(2, 0, 1)[None, ...].astype(np.float32)

    @api.model
    def _embed(self, session, b64_data):
        """L2-normalised float32 embedding for a base64 image."""
        tensor = self._preprocess(base64.b64decode(b64_data))
        input_name = session.get_inputs()[0].name
        names = [o.name for o in session.get_outputs()]
        outputs = dict(zip(names, session.run(None, {input_name: tensor})))
        out = outputs.get('image_embeds')
        if out is None:
            out = next((v for v in outputs.values() if v.ndim == 2), None)
        if out is None:  # token output (1, N, D): mean pool
            out = next(iter(outputs.values())).mean(axis=1)
        vec = np.asarray(out, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vec))
        if not norm:
            raise ValueError('empty embedding')
        return vec / norm

    # ------------------------------------------------------------------
    # Index + matching
    # ------------------------------------------------------------------
    @api.model
    def _load_index(self, exclude_ids, dim):
        """All stored embeddings (except ``exclude_ids``) as numpy arrays."""
        Image = self.env['otm.vendor.product.image']
        Image.flush_model(['design_embedding'])
        self.env.cr.execute(SQL(
            "SELECT id, COALESCE(submission_id, -1), design_embedding "
            "FROM %s WHERE design_embedding IS NOT NULL "
            "AND NOT (id = ANY(%s))",
            SQL.identifier(Image._table), list(exclude_ids) or [0]))
        ids, subs, vecs = [], [], []
        for rec_id, sub_id, blob in self.env.cr.fetchall():
            vec = np.frombuffer(bytes(blob), dtype=np.float32)
            if vec.shape[0] != dim:
                continue  # produced by another model; re-index needed
            ids.append(rec_id)
            subs.append(sub_id)
            vecs.append(vec)
        if not vecs:
            return (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64),
                    np.zeros((0, dim), dtype=np.float32))
        return (np.array(ids, dtype=np.int64), np.array(subs, dtype=np.int64),
                np.vstack(vecs))

    @api.model
    def process_images(self, images, allow_download=False):
        """Embed ``images`` (those still ``embed_state = pending`` whose
        duplicate hash analysis is finished) and record design matches.
        Never raises: design matching must not break an upload."""
        try:
            return self._process_images(images, allow_download)
        except Exception:
            _logger.exception('Design matching failed')
            return 0

    @api.model
    def _process_images(self, images, allow_download):
        todo = images.filtered(
            lambda i: i.embed_state == 'pending'
            and i.process_state == 'done' and i.image_512).sorted('id')
        if not todo:
            return 0
        session = self._get_session(allow_download=allow_download)
        if session is None:
            return 0
        Match = self.env['otm.vendor.design.match'].sudo()
        thresholds = self.get_design_thresholds()
        min_store = thresholds['similar'] / 100.0
        done = 0
        index = None
        for image in todo:
            try:
                vec = self._embed(session, image.image_512)
                if index is None:
                    index = list(self._load_index(todo.ids, vec.shape[0]))
                ids, subs, mat = index
                matches = []
                if len(ids):
                    scores = mat @ vec
                    own_sub = image.submission_id.id or -2
                    valid = (ids < image.id) & (subs != own_sub)
                    scores = np.where(valid, scores, -1.0)
                    order = np.argsort(-scores)[:TOP_MATCHES]
                    matches = [(int(ids[k]), float(scores[k]))
                               for k in order if scores[k] >= min_store]
                vals = {
                    'design_embedding': base64.b64encode(vec.tobytes()),
                    'embed_state': 'done',
                    'embed_error': False,
                    'design_score': round(matches[0][1] * 100, 1)
                    if matches else 0.0,
                }
                vals.update(self._status_vals(image, matches, thresholds))
                image.write(vals)
                Match.search([('image_id', '=', image.id)]).unlink()
                Match.create([{
                    'image_id': image.id,
                    'match_image_id': mid,
                    'score': round(score * 100, 1),
                } for mid, score in matches])
                # make this image visible to the rest of the batch
                index = [np.append(ids, image.id),
                         np.append(subs, image.submission_id.id or -1),
                         np.vstack([mat, vec[None, :]])
                         if len(ids) else vec[None, :]]
                done += 1
            except Exception as exc:
                _logger.exception('Design embedding failed for image %s',
                                  image.id)
                image.write({'embed_state': 'error',
                             'embed_error': str(exc)})
        return done

    @api.model
    def _status_vals(self, image, matches, thresholds):
        """Upgrade the duplicate status of a not-yet-flagged image when a
        strong design match exists."""
        if not matches:
            return {}
        best_id, best = matches[0]
        pct = round(best * 100, 1)
        if best * 100 >= thresholds['flag'] and image.duplicate_status in (
                'new', 'similar'):
            status = 'possible_duplicate'
        elif best * 100 >= thresholds['similar'] and (
                image.duplicate_status == 'new'):
            status = 'similar'
        else:
            return {}
        return {'duplicate_status': status, 'duplicate_image_id': best_id,
                'similarity_score': pct}

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_process_embeddings(self, batch_size=40):
        Image = self.env['otm.vendor.product.image']
        pending = Image.search([
            ('embed_state', '=', 'pending'),
            ('process_state', '=', 'done'),
        ], order='id', limit=batch_size)
        if not pending:
            return
        done = self.process_images(pending, allow_download=True)
        if done and Image.search_count(
                [('embed_state', '=', 'pending'),
                 ('process_state', '=', 'done')], limit=1):
            self.env.ref(
                'otm_vendor_product_selection.ir_cron_process_design_matches'
            )._trigger(at=fields.Datetime.now())
