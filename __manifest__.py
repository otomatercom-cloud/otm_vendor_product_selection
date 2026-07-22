# -*- coding: utf-8 -*-
# Part of Otomater. See LICENSE file for full copyright and licensing details.
{
    'name': 'Otomater Vendor Product Selection Management',
    'summary': 'Vendor portal product submission, duplicate image detection '
               'and Purchase Manager selection workflow for fashion retail.',
    'description': """
Otomater Vendor Product Selection Management
============================================
Fashion/dress retail vendor submission platform:

* Vendor management integrated with res.partner (vendor code, portal login)
* Vendor portal (/my/vendor): dashboard, product submission, bulk image upload
* Hierarchical multi-category product categorisation
* Two-level duplicate image detection (SHA-256 exact + perceptual hash)
* Purchase Manager duplicate review screen
* Submission workflow: Draft -> Submitted -> Under Review -> Selected/Rejected
* Mobile-first Purchase Manager review interface (/purchase/product-review)
* Conversion of selected submissions into product.template records
* Vendor e-mail notifications on every status change
""",
    'version': '19.0.1.0.0',
    'category': 'Purchases',
    'author': 'Otomater',
    'company': 'Otomater',
    'maintainer': 'Otomater',
    'website': 'https://otomater.com',
    'license': 'OPL-1',
    'depends': [
        'base',
        'mail',
        'contacts',
        'portal',
        'website',
        'product',
        'purchase',
    ],
    'external_dependencies': {
        'python': [],  # Pillow ships with Odoo; imagehash is optional (see duplicate_service.py)
    },
    'data': [
        # 1. Security: privilege + groups first, then ACLs, then record rules
        'security/vendor_security.xml',
        'security/ir.model.access.csv',
        'security/vendor_record_rules.xml',
        # 2. Master data
        'data/ir_sequence_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        # 3. Backend views (actions defined before the menus that point at them)
        'views/vendor_category_views.xml',
        'views/vendor_image_views.xml',
        'views/upload_batch_views.xml',
        'wizards/selection_wizard_views.xml',
        'wizards/rejection_wizard_views.xml',
        'wizards/portal_user_wizard_views.xml',
        'views/vendor_submission_views.xml',
        'views/res_partner_views.xml',
        'views/vendor_menus.xml',
        # 4. Frontend templates
        'views/portal_templates.xml',
        'views/review_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'otm_vendor_product_selection/static/src/css/backend_kanban.css',
        ],
        'web.assets_frontend': [
            'otm_vendor_product_selection/static/src/css/vendor_portal.css',
            'otm_vendor_product_selection/static/src/css/review_interface.css',
            'otm_vendor_product_selection/static/src/js/vendor_upload.js',
            'otm_vendor_product_selection/static/src/js/review_interface.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
