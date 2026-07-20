/* Part of Otomater. See LICENSE file for full copyright and licensing details. */
/* Purchase Manager mobile review interface — vanilla JS. */
(function () {
    'use strict';

    function jsonrpcCall(url, params) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                id: Date.now() + Math.random(),
                params: params || {},
            }),
        }).then(function (res) {
            return res.json();
        }).then(function (data) {
            if (data.error) {
                throw new Error(
                    (data.error.data && data.error.data.message)
                    || data.error.message || 'Request failed');
            }
            return data.result;
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var root = document.getElementById('wrap');
        if (!root || !root.classList.contains('otm-review-app')) { return; }

        var urls = {
            data: root.getAttribute('data-data-url'),
            detailTpl: root.getAttribute('data-detail-url-tpl'),
            duplicates: root.getAttribute('data-duplicates-url'),
            select: root.getAttribute('data-action-select-url'),
            reject: root.getAttribute('data-action-reject-url'),
            changes: root.getAttribute('data-action-changes-url'),
            review: root.getAttribute('data-action-review-url'),
            dupReview: root.getAttribute('data-action-dupreview-url'),
            dupDecisionTpl: root.getAttribute('data-duplicate-decision-url-tpl'),
        };

        var grid = document.getElementById('otm_review_grid');
        var loadingEl = document.getElementById('otm_review_loading');
        var emptyEl = document.getElementById('otm_review_empty');
        var loadMoreBtn = document.getElementById('otm_load_more');
        var bulkBar = document.getElementById('otm_bulk_bar');
        var bulkCountEl = document.getElementById('otm_bulk_count');
        var toastEl = document.getElementById('otm_toast');

        var state = {
            tab: 'submitted',
            page: 1,
            hasMore: false,
            loading: false,
            selected: {}, // id -> true
            listMode: false,
            filters: { search: '', vendor_id: '', category_id: '',
                      price_min: '', price_max: '', duplicates_only: false },
        };

        function toast(message, isError) {
            toastEl.textContent = message;
            toastEl.classList.remove('d-none', 'otm-toast-error');
            if (isError) { toastEl.classList.add('otm-toast-error'); }
            clearTimeout(toastEl._timer);
            toastEl._timer = setTimeout(function () {
                toastEl.classList.add('d-none');
            }, 3000);
        }

        function escapeHtml(str) {
            var div = document.createElement('div');
            div.textContent = str || '';
            return div.innerHTML;
        }

        /* ---------------------------------------------------------- *
         * Tabs
         * ---------------------------------------------------------- */
        document.querySelectorAll('.otm-tab').forEach(function (btn) {
            btn.addEventListener('click', function () {
                document.querySelectorAll('.otm-tab').forEach(function (b) {
                    b.classList.remove('btn-primary', 'btn-success',
                        'btn-danger', 'btn-warning', 'btn-secondary');
                    b.classList.add(
                        'btn-outline-' + (b.dataset.variant || 'primary'));
                });
                state.tab = btn.getAttribute('data-state');
                state.page = 1;
                state.selected = {};
                updateBulkBar();
                fetchAndRender(true);
            });
        });

        /* ---------------------------------------------------------- *
         * Grid / list toggle
         * ---------------------------------------------------------- */
        document.getElementById('otm_view_toggle').addEventListener(
            'click', function () {
                state.listMode = !state.listMode;
                grid.classList.toggle('otm-list-mode', state.listMode);
            });

        /* ---------------------------------------------------------- *
         * Filter drawer
         * ---------------------------------------------------------- */
        var drawer = document.getElementById('otm_filter_drawer');
        document.getElementById('otm_filter_open').addEventListener(
            'click', function () { drawer.classList.add('otm-open'); });
        document.getElementById('otm_filter_close').addEventListener(
            'click', function () { drawer.classList.remove('otm-open'); });
        drawer.addEventListener('click', function (e) {
            if (e.target === drawer) { drawer.classList.remove('otm-open'); }
        });
        document.getElementById('otm_filter_apply').addEventListener(
            'click', function () {
                state.filters.search =
                    document.getElementById('otm_f_search').value.trim();
                state.filters.vendor_id =
                    document.getElementById('otm_f_vendor').value;
                state.filters.category_id =
                    document.getElementById('otm_f_category').value;
                state.filters.price_min =
                    document.getElementById('otm_f_pmin').value;
                state.filters.price_max =
                    document.getElementById('otm_f_pmax').value;
                state.filters.duplicates_only =
                    document.getElementById('otm_f_dup').checked;
                state.page = 1;
                drawer.classList.remove('otm-open');
                fetchAndRender(true);
            });
        document.getElementById('otm_filter_reset').addEventListener(
            'click', function () {
                ['otm_f_search', 'otm_f_vendor', 'otm_f_category',
                 'otm_f_pmin', 'otm_f_pmax'].forEach(function (id) {
                    document.getElementById(id).value = '';
                });
                document.getElementById('otm_f_dup').checked = false;
                state.filters = { search: '', vendor_id: '', category_id: '',
                                  price_min: '', price_max: '',
                                  duplicates_only: false };
                state.page = 1;
                fetchAndRender(true);
            });

        /* ---------------------------------------------------------- *
         * Fetch + render product grid
         * ---------------------------------------------------------- */
        function fetchAndRender(reset) {
            if (state.loading) { return; }
            state.loading = true;
            if (reset) {
                grid.innerHTML = '';
                emptyEl.classList.add('d-none');
            }
            loadingEl.classList.remove('d-none');
            loadMoreBtn.classList.add('d-none');

            var request;
            if (state.tab === '__duplicates__') {
                request = jsonrpcCall(urls.duplicates, { page: state.page })
                    .then(renderDuplicates);
            } else {
                request = jsonrpcCall(urls.data, {
                    page: state.page,
                    state: state.tab,
                    vendor_id: state.filters.vendor_id || null,
                    category_id: state.filters.category_id || null,
                    price_min: state.filters.price_min || null,
                    price_max: state.filters.price_max || null,
                    duplicates_only: state.filters.duplicates_only,
                    search: state.filters.search,
                }).then(renderProducts);
            }

            request.catch(function (err) {
                toast(err.message || 'Failed to load products.', true);
            }).then(function () {
                state.loading = false;
                loadingEl.classList.add('d-none');
            });
        }

        function renderProducts(res) {
            state.hasMore = res.has_more;
            if (res.page === 1 && !res.records.length) {
                emptyEl.classList.remove('d-none');
            }
            res.records.forEach(function (rec) {
                grid.appendChild(buildProductCard(rec));
            });
            loadMoreBtn.classList.toggle('d-none', !state.hasMore);
        }

        function buildProductCard(rec) {
            var card = document.createElement('div');
            card.className = 'otm-pcard';
            card.dataset.id = rec.id;

            var imgWrap = document.createElement('div');
            imgWrap.className = 'otm-pcard-imgwrap';

            var checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'form-check-input otm-pcard-check';
            checkbox.checked = !!state.selected[rec.id];
            checkbox.addEventListener('click', function (e) {
                e.stopPropagation();
                if (checkbox.checked) {
                    state.selected[rec.id] = true;
                } else {
                    delete state.selected[rec.id];
                }
                updateBulkBar();
            });
            imgWrap.appendChild(checkbox);

            var img = document.createElement('img');
            img.className = 'otm-pcard-img';
            img.loading = 'lazy';
            img.src = rec.main_image_url || '';
            img.alt = rec.name;
            img.addEventListener('click', function () {
                openDetail(rec.id);
            });
            imgWrap.appendChild(img);

            if (rec.has_duplicate) {
                var dupBadge = document.createElement('span');
                dupBadge.className = 'badge text-bg-warning otm-pcard-dup';
                dupBadge.textContent = 'Dup?';
                imgWrap.appendChild(dupBadge);
            }
            var stateBadge = document.createElement('span');
            stateBadge.className = 'badge text-bg-dark otm-pcard-state';
            stateBadge.textContent = rec.state_label;
            imgWrap.appendChild(stateBadge);

            card.appendChild(imgWrap);

            var body = document.createElement('div');
            body.className = 'otm-pcard-body';
            body.innerHTML =
                '<div class="otm-pcard-name">' + escapeHtml(rec.name) + '</div>'
                + '<div class="otm-pcard-meta">' + escapeHtml(rec.vendor_name)
                + '</div>'
                + '<div class="otm-pcard-meta">' + escapeHtml(rec.category)
                + '</div>'
                + '<div class="otm-pcard-price">' + escapeHtml(rec.currency)
                + ' ' + Number(rec.purchase_price).toFixed(2) + '</div>';
            body.addEventListener('click', function () { openDetail(rec.id); });
            card.appendChild(body);

            var actions = document.createElement('div');
            actions.className = 'otm-pcard-actions';
            var selectBtn = document.createElement('button');
            selectBtn.type = 'button';
            selectBtn.className = 'btn btn-success btn-sm';
            selectBtn.textContent = 'Select';
            selectBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                openSelectModal([rec.id]);
            });
            var rejectBtn = document.createElement('button');
            rejectBtn.type = 'button';
            rejectBtn.className = 'btn btn-outline-danger btn-sm';
            rejectBtn.textContent = 'Reject';
            rejectBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                openReasonModal('reject', [rec.id]);
            });
            actions.appendChild(selectBtn);
            actions.appendChild(rejectBtn);
            card.appendChild(actions);

            return card;
        }

        loadMoreBtn.addEventListener('click', function () {
            state.page += 1;
            fetchAndRender(false);
        });

        /* ---------------------------------------------------------- *
         * Bulk selection bar
         * ---------------------------------------------------------- */
        function updateBulkBar() {
            var count = Object.keys(state.selected).length;
            bulkCountEl.textContent = count;
            bulkBar.classList.toggle('d-none', count === 0);
        }
        document.getElementById('otm_bulk_clear').addEventListener(
            'click', function () {
                state.selected = {};
                grid.querySelectorAll('.otm-pcard-check').forEach(
                    function (cb) { cb.checked = false; });
                updateBulkBar();
            });
        document.getElementById('otm_bulk_all').addEventListener(
            'click', function () {
                grid.querySelectorAll('.otm-pcard').forEach(function (card) {
                    state.selected[card.dataset.id] = true;
                    var cb = card.querySelector('.otm-pcard-check');
                    if (cb) { cb.checked = true; }
                });
                updateBulkBar();
            });
        document.getElementById('otm_bulk_select').addEventListener(
            'click', function () {
                openSelectModal(Object.keys(state.selected));
            });
        document.getElementById('otm_bulk_reject').addEventListener(
            'click', function () {
                openReasonModal('reject', Object.keys(state.selected));
            });

        /* ---------------------------------------------------------- *
         * Selection modal
         * ---------------------------------------------------------- */
        var selectModal = document.getElementById('otm_select_modal');
        var selectTargetIds = [];
        function openSelectModal(ids) {
            selectTargetIds = ids;
            document.getElementById('otm_sel_multi').textContent =
                ids.length > 1 ? ' (' + ids.length + ' items)' : '';
            document.getElementById('otm_sel_qty').value = '';
            document.getElementById('otm_sel_price').value = '';
            document.getElementById('otm_sel_notes').value = '';
            selectModal.classList.add('otm-open');
        }
        document.getElementById('otm_sel_confirm').addEventListener(
            'click', function () {
                var btn = document.getElementById('otm_sel_confirm');
                if (btn.classList.contains('otm-busy')) { return; }
                btn.classList.add('otm-busy');
                jsonrpcCall(urls.select, {
                    submission_ids: selectTargetIds,
                    qty: document.getElementById('otm_sel_qty').value || null,
                    price: document.getElementById('otm_sel_price').value || null,
                    notes: document.getElementById('otm_sel_notes').value,
                }).then(function (res) {
                    btn.classList.remove('otm-busy');
                    selectModal.classList.remove('otm-open');
                    if (res.success) {
                        toast(res.count + ' product(s) selected.');
                        removeCardsFromGrid(selectTargetIds);
                        state.selected = {};
                        updateBulkBar();
                        closeDetail();
                    } else {
                        toast(res.error || 'Could not select product(s).', true);
                    }
                }).catch(function (err) {
                    btn.classList.remove('otm-busy');
                    toast(err.message || 'Request failed.', true);
                });
            });

        /* ---------------------------------------------------------- *
         * Reject / request-changes modal
         * ---------------------------------------------------------- */
        var reasonModal = document.getElementById('otm_reason_modal');
        var reasonMode = 'reject';
        var reasonTargetIds = [];
        function openReasonModal(mode, ids) {
            reasonMode = mode;
            reasonTargetIds = ids;
            document.getElementById('otm_reason_title').textContent =
                mode === 'reject' ? 'Reject Product' : 'Request Changes';
            document.getElementById('otm_reason_label').textContent =
                mode === 'reject' ? 'Rejection Reason' : 'What needs to change?';
            document.getElementById('otm_reason_text').value = '';
            reasonModal.classList.add('otm-open');
        }
        document.getElementById('otm_reason_confirm').addEventListener(
            'click', function () {
                var btn = document.getElementById('otm_reason_confirm');
                if (btn.classList.contains('otm-busy')) { return; }
                btn.classList.add('otm-busy');
                var url = reasonMode === 'reject' ? urls.reject : urls.changes;
                var payload = { submission_ids: reasonTargetIds };
                var text = document.getElementById('otm_reason_text').value;
                if (reasonMode === 'reject') { payload.reason = text; }
                else { payload.notes = text; }
                jsonrpcCall(url, payload).then(function (res) {
                    btn.classList.remove('otm-busy');
                    reasonModal.classList.remove('otm-open');
                    if (res.success) {
                        toast(res.count + ' product(s) updated.');
                        removeCardsFromGrid(reasonTargetIds);
                        state.selected = {};
                        updateBulkBar();
                        closeDetail();
                    } else {
                        toast(res.error || 'Request failed.', true);
                    }
                }).catch(function (err) {
                    btn.classList.remove('otm-busy');
                    toast(err.message || 'Request failed.', true);
                });
            });

        document.querySelectorAll('.otm-modal-cancel').forEach(
            function (btn) {
                btn.addEventListener('click', function () {
                    btn.closest('.otm-modal').classList.remove('otm-open');
                });
            });

        function removeCardsFromGrid(ids) {
            var idSet = {};
            ids.forEach(function (i) { idSet[String(i)] = true; });
            grid.querySelectorAll('.otm-pcard').forEach(function (card) {
                if (idSet[card.dataset.id]) { card.remove(); }
            });
        }

        /* ---------------------------------------------------------- *
         * Detail sheet
         * ---------------------------------------------------------- */
        var sheet = document.getElementById('otm_detail_sheet');
        var detailBody = document.getElementById('otm_detail_body');

        function closeDetail() {
            sheet.classList.remove('otm-open');
        }
        sheet.addEventListener('click', function (e) {
            if (e.target === sheet) { closeDetail(); }
        });

        function openDetail(id) {
            var url = urls.detailTpl.replace('ID', id);
            detailBody.innerHTML = '<div class="text-center py-4">'
                + '<div class="spinner-border"></div></div>';
            sheet.classList.add('otm-open');
            jsonrpcCall(url, {}).then(function (rec) {
                if (rec.error) {
                    detailBody.innerHTML = '<p class="text-muted">Not found.</p>';
                    return;
                }
                renderDetail(rec);
            }).catch(function (err) {
                detailBody.innerHTML = '<p class="text-danger">'
                    + escapeHtml(err.message || 'Failed to load.') + '</p>';
            });
        }

        function renderDetail(rec) {
            var galleryImgs = rec.images.map(function (img, idx) {
                return '<img data-idx="' + idx + '" class="otm-gallery-img" src="'
                    + img.url + '" data-full="' + img.full_url + '" alt=""/>';
            }).join('');
            var thumbs = rec.images.map(function (img, idx) {
                return '<img data-idx="' + idx + '" class="otm-thumb-img'
                    + (idx === 0 ? ' otm-active' : '') + '" src="'
                    + img.thumb_url + '" alt=""/>';
            }).join('');

            var html = ''
                + '<h5>' + escapeHtml(rec.name) + '</h5>'
                + '<div class="text-muted small mb-2">'
                + escapeHtml(rec.vendor_name) + ' &#8226; '
                + escapeHtml(rec.code) + ' &#8226; '
                + escapeHtml(rec.vendor_sku) + '</div>'
                + '<div class="otm-gallery">' + galleryImgs + '</div>'
                + '<div class="otm-gallery-thumbs">' + thumbs + '</div>'
                + '<table class="table table-sm mt-3"><tbody>'
                + detailRow('Category', rec.categories.join(', '))
                + detailRow('Material', rec.material)
                + detailRow('Color', rec.color)
                + detailRow('Sizes', rec.available_sizes || rec.size)
                + detailRow('Brand', rec.brand)
                + detailRow('Purchase Price',
                    rec.currency + ' ' + Number(rec.purchase_price).toFixed(2))
                + detailRow('MRP',
                    rec.currency + ' ' + Number(rec.mrp).toFixed(2))
                + detailRow('Min Order Qty', String(rec.min_order_qty))
                + detailRow('Available Qty', String(rec.available_qty))
                + detailRow('Vendor Notes', rec.vendor_notes)
                + '</tbody></table>';

            if (rec.description) {
                html += '<div class="mb-3">' + rec.description + '</div>';
            }

            html += '<div class="otm-detail-actions">';
            if (rec.state === 'submitted') {
                html += '<button type="button" class="btn btn-outline-primary" '
                    + 'id="otm_d_review">Start Review</button>';
            }
            html += '<button type="button" class="btn btn-outline-warning" '
                + 'id="otm_d_changes">Changes</button>'
                + '<button type="button" class="btn btn-outline-danger" '
                + 'id="otm_d_reject">Reject</button>'
                + '<button type="button" class="btn btn-success" '
                + 'id="otm_d_select">Select</button>'
                + '</div>';

            detailBody.innerHTML = html;

            var mainGalleryImgs = detailBody.querySelectorAll('.otm-gallery-img');
            var thumbImgs = detailBody.querySelectorAll('.otm-thumb-img');
            function setActive(idx) {
                thumbImgs.forEach(function (t) {
                    t.classList.toggle('otm-active',
                        Number(t.dataset.idx) === idx);
                });
                var target = detailBody.querySelector(
                    '.otm-gallery-img[data-idx="' + idx + '"]');
                if (target) {
                    target.scrollIntoView({ inline: 'center', behavior: 'smooth' });
                }
            }
            thumbImgs.forEach(function (t) {
                t.addEventListener('click', function () {
                    setActive(Number(t.dataset.idx));
                });
            });
            mainGalleryImgs.forEach(function (im) {
                im.addEventListener('click', function () {
                    openLightbox(im.dataset.full);
                });
            });

            var reviewBtn = document.getElementById('otm_d_review');
            if (reviewBtn) {
                reviewBtn.addEventListener('click', function () {
                    jsonrpcCall(urls.review, { submission_ids: [rec.id] })
                        .then(function (res) {
                            if (res.success) {
                                toast('Moved to Under Review.');
                                removeCardsFromGrid([rec.id]);
                                closeDetail();
                            } else {
                                toast(res.error || 'Failed.', true);
                            }
                        }).catch(function (err) {
                            toast(err.message || 'Failed.', true);
                        });
                });
            }
            document.getElementById('otm_d_changes').addEventListener(
                'click', function () {
                    closeDetail();
                    openReasonModal('changes', [rec.id]);
                });
            document.getElementById('otm_d_reject').addEventListener(
                'click', function () {
                    closeDetail();
                    openReasonModal('reject', [rec.id]);
                });
            document.getElementById('otm_d_select').addEventListener(
                'click', function () {
                    closeDetail();
                    openSelectModal([rec.id]);
                });
        }

        function detailRow(label, value) {
            if (!value) { return ''; }
            return '<tr><th class="w-25">' + escapeHtml(label) + '</th><td>'
                + escapeHtml(value) + '</td></tr>';
        }

        /* ---------------------------------------------------------- *
         * Lightbox
         * ---------------------------------------------------------- */
        var lightbox = document.getElementById('otm_lightbox');
        var lightboxImg = document.getElementById('otm_lightbox_img');
        function openLightbox(src) {
            lightboxImg.src = src;
            lightbox.classList.add('otm-open');
        }
        document.getElementById('otm_lightbox_close').addEventListener(
            'click', function () { lightbox.classList.remove('otm-open'); });
        lightbox.addEventListener('click', function (e) {
            if (e.target === lightbox) { lightbox.classList.remove('otm-open'); }
        });

        /* ---------------------------------------------------------- *
         * Duplicate comparison feed
         * ---------------------------------------------------------- */
        function renderDuplicates(res) {
            state.hasMore = res.has_more;
            if (res.page === 1 && !res.records.length) {
                emptyEl.classList.remove('d-none');
            }
            res.records.forEach(function (rec) {
                grid.appendChild(buildDuplicateCard(rec));
            });
            loadMoreBtn.classList.toggle('d-none', !state.hasMore);
        }

        function buildDuplicateCard(rec) {
            var card = document.createElement('div');
            card.className = 'otm-dup-card';
            card.style.gridColumn = '1 / -1';
            card.innerHTML =
                '<div class="otm-dup-compare">'
                + '<div><img class="otm-dup-new" src="' + rec.new_thumb
                + '" data-full="' + rec.new_url + '" alt=""/>'
                + '<div class="small text-muted mt-1">'
                + escapeHtml(rec.new_vendor) + '<br/>'
                + escapeHtml(rec.new_product) + '</div></div>'
                + '<div class="otm-dup-vs">VS<br/><span class="small">'
                + Math.round((rec.similarity_score || 0) * 100) + '%</span></div>'
                + '<div><img class="otm-dup-existing" src="' + rec.existing_thumb
                + '" data-full="' + rec.existing_url + '" alt=""/>'
                + '<div class="small text-muted mt-1">'
                + escapeHtml(rec.existing_vendor) + '<br/>'
                + escapeHtml(rec.existing_product) + '</div></div>'
                + '</div>'
                + '<div class="otm-dup-actions">'
                + '<button type="button" class="btn btn-outline-secondary" '
                + 'data-decision="not_duplicate">Not a Duplicate</button>'
                + '<button type="button" class="btn btn-outline-primary" '
                + 'data-decision="keep_both">Keep Both</button>'
                + '<button type="button" class="btn btn-outline-info" '
                + 'data-decision="link_existing">Link Existing</button>'
                + '<button type="button" class="btn btn-danger" '
                + 'data-decision="confirm">Confirm Duplicate</button>'
                + '</div>';

            card.querySelector('.otm-dup-new').addEventListener(
                'click', function (e) { openLightbox(e.target.dataset.full); });
            card.querySelector('.otm-dup-existing').addEventListener(
                'click', function (e) { openLightbox(e.target.dataset.full); });

            card.querySelectorAll('[data-decision]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    if (btn.classList.contains('otm-busy')) { return; }
                    card.classList.add('otm-busy');
                    var url = urls.dupDecisionTpl
                        .replace('IMAGE_ID', rec.id)
                        .replace('DECISION', btn.dataset.decision);
                    jsonrpcCall(url, {}).then(function (res) {
                        card.classList.remove('otm-busy');
                        if (res.success) {
                            toast('Updated.');
                            card.remove();
                        } else {
                            toast(res.error || 'Failed.', true);
                        }
                    }).catch(function (err) {
                        card.classList.remove('otm-busy');
                        toast(err.message || 'Failed.', true);
                    });
                });
            });

            return card;
        }

        /* ---------------------------------------------------------- *
         * Initial load
         * ---------------------------------------------------------- */
        fetchAndRender(true);
    });
})();
