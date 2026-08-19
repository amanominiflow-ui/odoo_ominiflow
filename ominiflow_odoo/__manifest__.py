{
    'name': 'OminiFlow',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Connect Odoo 19 with the OminiFlow WhatsApp and catalog APIs',
    'description': """
OminiFlow Connector for Odoo 19
===============================

HTTP connector between Odoo 19 and the existing OminiFlow PHP backend.

Supported (real OminiFlow APIs):
- Connection test via GET /api/wpbox/me
- Product catalog pull/push via /api/wpbox/ecommerce/products
- Contact (customer) sync via /api/wpbox/getContacts and /api/wpbox/makeContact
- Developer Portal webhooks (HMAC SHA-256)

Not included (OminiFlow has no public REST API yet):
- Sales order synchronization
- Warehouse inventory moves
    """,
    'author': 'OminiFlow',
    'website': 'https://www.ominiflow.com',
    'license': 'LGPL-3',
    'depends': ['base', 'product'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/ominiflow_instance_views.xml',
        'views/ominiflow_sync_log_views.xml',
        'views/ominiflow_dashboard_views.xml',
        'views/product_views.xml',
        'views/partner_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/sync_wizard_views.xml',
        'views/ominiflow_menus.xml',
        'data/ir_cron.xml',
    ],
    'images': [
        'static/description/icon.png',
        'static/description/connection.png',
        'static/description/synclogs.png',
    ],
    'application': True,
    'installable': True,
}
