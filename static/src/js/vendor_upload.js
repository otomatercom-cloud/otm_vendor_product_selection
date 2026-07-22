/* Part of Otomater. See LICENSE file for full copyright and licensing details. */
/* Vendor portal frontend JS — vanilla JS, no build step (Odoo 19 asset
 * pipeline serves this as a plain web.assets_frontend bundle entry). */
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
                id: Date.now(),
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

    function humanSize(bytes) {
        if (bytes < 1024) { return bytes + ' B'; }
        if (bytes < 1024 * 1024) { return (bytes / 1024).toFixed(0) + ' KB'; }
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function showToastFallback(message, isError) {
        // Simple, dependency-free toast for pages without the review app shell
        var el = document.createElement('div');
        el.textContent = message;
        el.style.position = 'fixed';
        el.style.bottom = '1.5rem';
        el.style.left = '50%';
        el.style.transform = 'translateX(-50%)';
        el.style.background = isError ? '#b91c1c' : '#111827';
        el.style.color = '#fff';
        el.style.padding = '0.6rem 1rem';
        el.style.borderRadius = '2rem';
        el.style.fontSize = '0.85rem';
        el.style.zIndex = 2000;
        document.body.appendChild(el);
        setTimeout(function () { el.remove(); }, 3000);
    }

    /* ------------------------------------------------------------ *
     * Single-product image upload widget (product detail page)
     * ------------------------------------------------------------ */
    function initSingleUploadWidget(widget) {
        var uploadUrl = widget.getAttribute('data-upload-url');
        var fileInput = widget.querySelector('.otm-file-input');
        var previewWrap = widget.querySelector('.otm-upload-previews');
        var uploadBtn = widget.querySelector('.otm-upload-btn');
        var progressWrap = widget.querySelector('.otm-upload-progress');
        var progressBar = progressWrap ? progressWrap.querySelector('.progress-bar') : null;
        var pending = [];

        function renderPreviews() {
            previewWrap.innerHTML = '';
            pending.forEach(function (item, idx) {
                var col = document.createElement('div');
                col.className = 'col-4 col-md-3 otm-preview-cell';
                var img = document.createElement('img');
                img.src = item.dataUrl;
                col.appendChild(img);
                var status = document.createElement('div');
                status.className = 'otm-preview-status';
                status.textContent = humanSize(item.file.size);
                col.appendChild(status);
                var removeBtn = document.createElement('button');
                removeBtn.type = 'button';
                removeBtn.className = 'btn btn-sm btn-danger otm-preview-remove';
                removeBtn.textContent = String.fromCharCode(215);
                removeBtn.addEventListener('click', function () {
                    pending.splice(idx, 1);
                    renderPreviews();
                });
                col.appendChild(removeBtn);
                previewWrap.appendChild(col);
            });
            uploadBtn.disabled = pending.length === 0;
        }

        fileInput.addEventListener('change', function () {
            var files = Array.prototype.slice.call(fileInput.files || []);
            files.forEach(function (file) {
                var reader = new FileReader();
                reader.onload = function () {
                    pending.push({ file: file, dataUrl: reader.result });
                    renderPreviews();
                };
                reader.readAsDataURL(file);
            });
            fileInput.value = '';
        });

        uploadBtn.addEventListener('click', function () {
            if (!pending.length || uploadBtn.disabled) { return; }
            uploadBtn.disabled = true;
            uploadBtn.textContent = 'Uploading...';
            if (progressWrap) { progressWrap.classList.remove('d-none'); }

            var formData = new FormData();
            formData.append('csrf_token', widget.getAttribute('data-csrf'));
            pending.forEach(function (item) {
                formData.append('images', item.file, item.file.name);
            });

            var xhr = new XMLHttpRequest();
            xhr.open('POST', uploadUrl, true);
            xhr.upload.addEventListener('progress', function (evt) {
                if (evt.lengthComputable && progressBar) {
                    var pct = Math.round((evt.loaded / evt.total) * 100);
                    progressBar.style.width = pct + '%';
                    progressBar.textContent = pct + '%';
                }
            });
            xhr.onload = function () {
                uploadBtn.disabled = false;
                uploadBtn.textContent = 'Upload Selected Images';
                if (progressWrap) { progressWrap.classList.add('d-none'); }
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (data.success) {
                        window.location.reload();
                        return;
                    }
                    showToastFallback(
                        (data.error) || 'Some images failed to upload.', true);
                } catch (e) {
                    showToastFallback('Upload failed. Please try again.', true);
                }
            };
            xhr.onerror = function () {
                uploadBtn.disabled = false;
                uploadBtn.textContent = 'Upload Selected Images';
                showToastFallback('Network error during upload.', true);
            };
            xhr.send(formData);
        });
    }

    /* ------------------------------------------------------------ *
     * Delete image buttons (product detail page)
     * ------------------------------------------------------------ */
    function initImageDeleteButtons() {
        document.querySelectorAll('.otm-img-delete').forEach(function (btn) {
            btn.addEventListener('click', function () {
                if (btn.disabled) { return; }
                if (!window.confirm('Remove this image?')) { return; }
                var imageId = btn.getAttribute('data-image-id');
                btn.disabled = true;
                var formData = new FormData();
                var csrfInput = document.querySelector(
                    'input[name="csrf_token"]');
                formData.append(
                    'csrf_token', csrfInput ? csrfInput.value : '');
                fetch('/my/vendor/image/' + imageId + '/delete', {
                    method: 'POST',
                    credentials: 'same-origin',
                    body: formData,
                }).then(function (res) { return res.json(); })
                    .then(function (data) {
                        if (data.success) {
                            window.location.reload();
                        } else {
                            btn.disabled = false;
                            showToastFallback(
                                data.error || 'Could not remove image.', true);
                        }
                    }).catch(function () {
                        btn.disabled = false;
                        showToastFallback('Network error.', true);
                    });
            });
        });
    }

    /* ------------------------------------------------------------ *
     * Prevent double-tap on plain form submissions (submit / save)
     * ------------------------------------------------------------ */
    function initDoubleSubmitGuards() {
        document.querySelectorAll('form.otm-single-submit').forEach(
            function (form) {
                form.addEventListener('submit', function () {
                    var btn = form.querySelector(
                        'button[type="submit"]');
                    if (btn) {
                        if (btn.disabled) {
                            // already submitting — block a second event
                            return false;
                        }
                        btn.disabled = true;
                        btn.dataset.originalText = btn.textContent;
                        btn.textContent = 'Please wait...';
                    }
                });
            });
    }

    /* ------------------------------------------------------------ *
     * Bulk upload page
     * ------------------------------------------------------------ */
    function initBulkUpload() {
        var root = document.getElementById('otm_bulk_upload');
        if (!root) { return; }

        var createUrl = root.getAttribute('data-batch-create-url');
        var finishUrlTpl = root.getAttribute('data-batch-finish-url-tpl');
        var imageUrlTpl = root.getAttribute('data-batch-image-url-tpl');
        var imagesUrlTpl = root.getAttribute('data-batch-images-url-tpl');
        var quickCreateUrl = root.getAttribute('data-quick-create-url');
        var csrfToken = root.getAttribute('data-csrf');
        var maxMb = parseFloat(root.getAttribute('data-max-mb') || '10');

        var fileInput = document.getElementById('otm_bulk_files');
        var previewsEl = document.getElementById('otm_bulk_previews');
        var startBtn = document.getElementById('otm_bulk_start');
        var progressWrap = document.getElementById('otm_bulk_progress_wrap');
        var progressBar = document.getElementById('otm_bulk_progress');
        var statusEl = document.getElementById('otm_bulk_status');
        var resultEl = document.getElementById('otm_bulk_result');
        var dropzone = root.querySelector('.otm-dropzone');

        var groupSection = document.getElementById('otm_group_section');
        var groupGrid = document.getElementById('otm_group_grid');
        var groupSelectedCount = document.getElementById('otm_group_selected_count');
        var groupCreateBtn = document.getElementById('otm_group_create_btn');
        var quickModal = document.getElementById('otm_quick_modal');
        var quickName = document.getElementById('otm_quick_name');
        var quickPrice = document.getElementById('otm_quick_price');
        var quickConfirm = document.getElementById('otm_quick_confirm');

        var queued = []; // { file, dataUrl, cellEl, statusEl }
        var currentBatchId = null;
        var groupSelected = {}; // image id -> true

        function addFiles(fileList) {
            Array.prototype.slice.call(fileList).forEach(function (file) {
                if (file.size > maxMb * 1024 * 1024) {
                    showToastFallback(
                        file.name + ' is larger than ' + maxMb + ' MB and was skipped.',
                        true);
                    return;
                }
                var reader = new FileReader();
                reader.onload = function () {
                    var cell = document.createElement('div');
                    cell.className = 'col-4 col-md-2 otm-preview-cell';
                    var img = document.createElement('img');
                    img.src = reader.result;
                    cell.appendChild(img);
                    var status = document.createElement('div');
                    status.className = 'otm-preview-status';
                    status.textContent = humanSize(file.size);
                    cell.appendChild(status);
                    var removeBtn = document.createElement('button');
                    removeBtn.type = 'button';
                    removeBtn.className = 'btn btn-sm btn-danger otm-preview-remove';
                    removeBtn.textContent = String.fromCharCode(215);
                    cell.appendChild(removeBtn);
                    previewsEl.appendChild(cell);

                    var entry = { file: file, cellEl: cell, statusEl: status };
                    queued.push(entry);
                    removeBtn.addEventListener('click', function () {
                        var idx = queued.indexOf(entry);
                        if (idx >= 0) { queued.splice(idx, 1); }
                        cell.remove();
                        startBtn.disabled = queued.length === 0;
                    });
                    startBtn.disabled = queued.length === 0;
                };
                reader.readAsDataURL(file);
            });
        }

        fileInput.addEventListener('change', function () {
            addFiles(fileInput.files);
            fileInput.value = '';
        });

        if (dropzone) {
            ['dragover', 'dragenter'].forEach(function (evtName) {
                dropzone.addEventListener(evtName, function (e) {
                    e.preventDefault();
                    dropzone.classList.add('otm-dragover');
                });
            });
            ['dragleave', 'dragend'].forEach(function (evtName) {
                dropzone.addEventListener(evtName, function () {
                    dropzone.classList.remove('otm-dragover');
                });
            });
            dropzone.addEventListener('drop', function (e) {
                e.preventDefault();
                dropzone.classList.remove('otm-dragover');
                if (e.dataTransfer && e.dataTransfer.files) {
                    addFiles(e.dataTransfer.files);
                }
            });
        }

        function uploadOne(batchId, entry) {
            return new Promise(function (resolve) {
                var formData = new FormData();
                formData.append('csrf_token', csrfToken);
                formData.append('images', entry.file, entry.file.name);
                // No submission_id here on purpose — bulk-uploaded images
                // start unassigned and get grouped into products below.
                var url = imageUrlTpl.replace('BATCH_ID', batchId);
                fetch(url, {
                    method: 'POST', credentials: 'same-origin', body: formData,
                }).then(function (res) { return res.json(); })
                    .then(function (data) {
                        var ok = data.success && data.results
                            && data.results[0] && data.results[0].success;
                        entry.statusEl.textContent = ok ? 'Uploaded' : 'Failed';
                        entry.cellEl.classList.toggle('otm-preview-error', !ok);
                        resolve(ok);
                    }).catch(function () {
                        entry.statusEl.textContent = 'Failed';
                        entry.cellEl.classList.add('otm-preview-error');
                        resolve(false);
                    });
            });
        }

        function runSequential(batchId) {
            var total = queued.length;
            var done = 0;
            var failures = 0;

            function next() {
                if (done >= total) {
                    return Promise.resolve();
                }
                var entry = queued[done];
                return uploadOne(batchId, entry).then(function (ok) {
                    done += 1;
                    if (!ok) { failures += 1; }
                    var pct = Math.round((done / total) * 100);
                    progressBar.style.width = pct + '%';
                    progressBar.textContent = pct + '%';
                    statusEl.textContent = 'Uploaded ' + done + ' of '
                        + total + (failures ? (' (' + failures + ' failed)') : '');
                    return next();
                });
            }
            return next();
        }

        /* ------------------------------------------------------------ *
         * Grouping grid: render uploaded images, select some, create a
         * product from the selection — no separate "new product" page.
         * ------------------------------------------------------------ */
        function loadGroupGrid(batchId) {
            var url = imagesUrlTpl.replace('BATCH_ID', batchId);
            return jsonrpcCall(url, {}).then(function (res) {
                if (!res.success) { return; }
                renderGroupGrid(res.images);
                groupSection.classList.remove('d-none');
            });
        }

        function renderGroupGrid(images) {
            groupGrid.innerHTML = '';
            images.forEach(function (img) {
                var col = document.createElement('div');
                col.className = 'col-4 col-md-2 otm-group-cell';
                if (img.assigned) { col.classList.add('otm-group-assigned'); }
                col.dataset.id = img.id;

                var checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'form-check-input otm-group-check';
                checkbox.disabled = img.assigned;
                col.appendChild(checkbox);

                var imgEl = document.createElement('img');
                imgEl.src = img.thumb_url;
                imgEl.loading = 'lazy';
                col.appendChild(imgEl);

                if (img.assigned) {
                    var badge = document.createElement('div');
                    badge.className = 'otm-group-badge';
                    badge.textContent = img.submission_name || 'Assigned';
                    col.appendChild(badge);
                }

                if (!img.assigned) {
                    col.addEventListener('click', function (e) {
                        if (e.target === checkbox) { return; }
                        checkbox.checked = !checkbox.checked;
                        toggleGroupSelect(img.id, checkbox.checked, col);
                    });
                    checkbox.addEventListener('click', function () {
                        toggleGroupSelect(img.id, checkbox.checked, col);
                    });
                }

                groupGrid.appendChild(col);
            });
        }

        function toggleGroupSelect(id, selected, cellEl) {
            if (selected) {
                groupSelected[id] = true;
            } else {
                delete groupSelected[id];
            }
            cellEl.classList.toggle('otm-group-selected', selected);
            var count = Object.keys(groupSelected).length;
            groupSelectedCount.textContent = count;
            groupCreateBtn.disabled = count === 0;
        }

        var quickMainCategory = document.getElementById('otm_quick_main_category');
        var quickSubcategory = document.getElementById('otm_quick_subcategory');
        var allCategories = [];
        try {
            allCategories = JSON.parse(
                quickModal.getAttribute('data-categories') || '[]');
        } catch (e) {
            allCategories = [];
        }
        var mainCategories = allCategories.filter(function (c) {
            return !c.parent_id;
        });

        function populateMainCategories() {
            quickMainCategory.innerHTML = '';
            var placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = '-- Select --';
            quickMainCategory.appendChild(placeholder);
            mainCategories.forEach(function (cat) {
                var opt = document.createElement('option');
                opt.value = cat.id;
                opt.textContent = cat.name;
                quickMainCategory.appendChild(opt);
            });
        }

        function populateSubcategories(parentId) {
            quickSubcategory.innerHTML = '';
            var children = allCategories.filter(function (c) {
                return String(c.parent_id) === String(parentId);
            });
            if (!parentId || !children.length) {
                var placeholder = document.createElement('option');
                placeholder.value = '';
                placeholder.textContent = parentId
                    ? '-- No subcategories --' : '-- Select main category first --';
                quickSubcategory.appendChild(placeholder);
                quickSubcategory.disabled = true;
                return;
            }
            var blank = document.createElement('option');
            blank.value = '';
            blank.textContent = '-- None --';
            quickSubcategory.appendChild(blank);
            children.forEach(function (cat) {
                var opt = document.createElement('option');
                opt.value = cat.id;
                opt.textContent = cat.name;
                quickSubcategory.appendChild(opt);
            });
            quickSubcategory.disabled = false;
        }

        quickMainCategory.addEventListener('change', function () {
            populateSubcategories(quickMainCategory.value);
        });

        populateMainCategories();
        populateSubcategories('');

        groupCreateBtn.addEventListener('click', function () {
            if (!Object.keys(groupSelected).length) { return; }
            quickName.value = '';
            quickPrice.value = '';
            quickMainCategory.value = '';
            populateSubcategories('');
            quickModal.classList.add('otm-open');
            quickName.focus();
        });

        document.querySelectorAll('.otm-quick-cancel').forEach(function (btn) {
            btn.addEventListener('click', function () {
                quickModal.classList.remove('otm-open');
            });
        });
        quickModal.addEventListener('click', function (e) {
            if (e.target === quickModal) {
                quickModal.classList.remove('otm-open');
            }
        });

        quickConfirm.addEventListener('click', function () {
            var name = quickName.value.trim();
            if (!name) {
                showToastFallback('Enter a product name.', true);
                return;
            }
            if (quickConfirm.disabled) { return; }
            quickConfirm.disabled = true;
            quickConfirm.textContent = 'Creating...';

            var ids = Object.keys(groupSelected).map(function (i) {
                return parseInt(i, 10);
            });
            jsonrpcCall(quickCreateUrl, {
                image_ids: ids,
                name: name,
                purchase_price: quickPrice.value || null,
            }).then(function (res) {
                quickConfirm.disabled = false;
                quickConfirm.textContent = 'Create Product';
                if (!res.success) {
                    showToastFallback(
                        res.error || 'Could not create product.', true);
                    return;
                }
                quickModal.classList.remove('otm-open');
                showToastFallback('Product "' + res.submission_name
                    + '" created with ' + ids.length + ' image(s).');
                // Mark those cells assigned instead of a full reload, so the
                // vendor can keep grouping the remaining images.
                ids.forEach(function (id) {
                    delete groupSelected[id];
                    var cell = groupGrid.querySelector(
                        '.otm-group-cell[data-id="' + id + '"]');
                    if (cell) {
                        cell.classList.add('otm-group-assigned');
                        cell.classList.remove('otm-group-selected');
                        var cb = cell.querySelector('.otm-group-check');
                        if (cb) { cb.checked = false; cb.disabled = true; }
                        var oldBadge = cell.querySelector('.otm-group-badge');
                        if (oldBadge) { oldBadge.remove(); }
                        var badge = document.createElement('div');
                        badge.className = 'otm-group-badge';
                        badge.textContent = res.submission_name;
                        cell.appendChild(badge);
                    }
                });
                groupSelectedCount.textContent = '0';
                groupCreateBtn.disabled = true;
            }).catch(function (err) {
                quickConfirm.disabled = false;
                quickConfirm.textContent = 'Create Product';
                showToastFallback(err.message || 'Request failed.', true);
            });
        });

        startBtn.addEventListener('click', function () {
            if (!queued.length || startBtn.disabled) { return; }
            startBtn.disabled = true;
            startBtn.textContent = 'Uploading...';
            progressWrap.classList.remove('d-none');
            statusEl.textContent = 'Creating batch...';

            jsonrpcCall(createUrl, {}).then(function (batchRes) {
                var batchId = batchRes.batch_id;
                currentBatchId = batchId;
                statusEl.textContent = 'Uploading images...';
                return runSequential(batchId).then(function () {
                    statusEl.textContent = 'Finalising batch...';
                    var finishUrl = finishUrlTpl.replace('BATCH_ID', batchId);
                    return jsonrpcCall(finishUrl, {});
                }).then(function (finishRes) {
                    document.getElementById('otm_res_batch').textContent =
                        'Batch #' + batchId;
                    document.getElementById('otm_res_total').textContent =
                        finishRes.total;
                    document.getElementById('otm_res_new').textContent =
                        finishRes.new;
                    var processingNote = document.getElementById(
                        'otm_res_processing');
                    if (finishRes.state === 'processing') {
                        processingNote.classList.remove('d-none');
                    }
                    resultEl.classList.remove('d-none');
                    statusEl.textContent = 'Done.';
                    startBtn.textContent = 'Upload All Images';
                    return loadGroupGrid(batchId);
                });
            }).catch(function (err) {
                startBtn.disabled = false;
                startBtn.textContent = 'Upload All Images';
                showToastFallback(
                    err.message || 'Upload failed. Please try again.', true);
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.otm-upload-widget').forEach(
            initSingleUploadWidget);
        initImageDeleteButtons();
        initDoubleSubmitGuards();
        initBulkUpload();
    });
})();
