from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.ominiflow_odoo.services.sync_service import OminiFlowSyncService
from .common import FakeResponse, OminiFlowCaseMixin


def _product_page(rows, page=1, last=1):
    return FakeResponse(200, {
        'status': 'success',
        'data': rows,
        'pagination': {
            'current_page': page,
            'last_page': last,
            'per_page': 50,
            'total': len(rows),
        },
    })


@tagged('post_install', '-at_install', 'ominiflow')
class TestOminiFlowSync(OminiFlowCaseMixin, TransactionCase):

    def test_product_sync_creates_and_is_idempotent(self):
        instance = self._create_instance()
        row = {
            'id': 501,
            'name': 'Demo Soap',
            'description': 'A soap',
            'price': 99.5,
            'currency': 'INR',
            'sku': 'SOAP-501',
            'stock_quantity': 7,
            'is_available': True,
        }
        page = _product_page([row])
        with patch('odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request', return_value=page):
            OminiFlowSyncService(self.env, instance).sync_products()
            OminiFlowSyncService(self.env, instance).sync_products()
        products = self.env['product.template'].search([('ominiflow_id', '=', '501')])
        self.assertEqual(len(products), 1)
        self.assertEqual(products.default_code, 'SOAP-501')
        self.assertEqual(products.list_price, 99.5)
        self.assertEqual(products.ominiflow_stock_quantity, 7.0)
        bindings = self.env['ominiflow.binding'].search([
            ('instance_id', '=', instance.id),
            ('resource_type', '=', 'product'),
            ('external_id', '=', '501'),
        ])
        self.assertEqual(len(bindings), 1)

    def test_product_match_by_sku_without_duplicate(self):
        instance = self._create_instance()
        existing = self.env['product.template'].create({
            'name': 'Existing Soap',
            'default_code': 'SOAP-501',
            'company_id': instance.company_id.id,
        })
        row = {
            'id': 501,
            'name': 'Demo Soap updated',
            'price': 120,
            'sku': 'SOAP-501',
            'is_available': True,
        }
        with patch(
            'odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request',
            return_value=_product_page([row]),
        ):
            OminiFlowSyncService(self.env, instance).sync_products()
        products = self.env['product.template'].search([('default_code', '=', 'SOAP-501')])
        self.assertEqual(len(products), 1)
        self.assertEqual(products.id, existing.id)
        self.assertEqual(products.ominiflow_id, '501')
        self.assertEqual(products.name, 'Demo Soap updated')

    def test_product_without_id_or_sku_is_not_created(self):
        instance = self._create_instance()
        row = {'name': 'Nameless match risk', 'price': 10}
        with patch(
            'odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request',
            return_value=_product_page([row]),
        ):
            OminiFlowSyncService(self.env, instance).sync_products()
        self.assertFalse(self.env['product.template'].search([('name', '=', 'Nameless match risk')]))

    def test_product_pagination(self):
        instance = self._create_instance()
        page1 = _product_page([{'id': 1, 'name': 'P1', 'price': 1, 'sku': 'P1'}], page=1, last=2)
        page2 = _product_page([{'id': 2, 'name': 'P2', 'price': 2, 'sku': 'P2'}], page=2, last=2)
        with patch(
            'odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request',
            side_effect=[page1, page2],
        ):
            stats = OminiFlowSyncService(self.env, instance).sync_products()
        self.assertEqual(stats['created'], 2)
        self.assertEqual(
            self.env['product.template'].search_count([('ominiflow_instance_id', '=', instance.id)]),
            2,
        )

    def test_customer_sync_idempotent_by_phone(self):
        instance = self._create_instance()
        existing = self.env['res.partner'].create({
            'name': 'Priya',
            'phone': '919876543210',
            'company_id': instance.company_id.id,
        })
        payload = FakeResponse(200, {
            'status': 'success',
            'contacts': [
                {'id': 88, 'name': 'Priya Sharma', 'phone': '+919876543210', 'email': 'priya@example.com'},
            ],
        })
        with patch(
            'odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request',
            return_value=payload,
        ):
            OminiFlowSyncService(self.env, instance).sync_customers()
            OminiFlowSyncService(self.env, instance).sync_customers()
        partners = self.env['res.partner'].search([('ominiflow_id', '=', '88')])
        self.assertEqual(len(partners), 1)
        self.assertEqual(partners.id, existing.id)
        self.assertEqual(partners.email, 'priya@example.com')

    def test_customer_sync_matches_shared_partner(self):
        instance = self._create_instance()
        existing = self.env['res.partner'].create({
            'name': 'Shared contact',
            'phone': '918888777666',
            'company_id': False,
        })
        payload = FakeResponse(200, {
            'status': 'success',
            'contacts': [
                {'id': 77, 'name': 'Shared contact', 'phone': '918888777666'},
            ],
        })
        with patch(
            'odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request',
            return_value=payload,
        ):
            stats = OminiFlowSyncService(self.env, instance).sync_customers()
        self.assertEqual(stats['failed'], 0)
        self.assertEqual(existing.ominiflow_id, '77')
        self.assertEqual(existing.ominiflow_instance_id, instance)

    def test_customer_sync_does_not_bind_company_partner(self):
        instance = self._create_instance()
        company_partner = instance.company_id.partner_id
        phone = '917777666555'
        company_partner.write({'phone': phone})
        payload = FakeResponse(200, {
            'status': 'success',
            'contacts': [
                {'id': 99, 'name': 'WhatsApp User', 'phone': phone},
            ],
        })
        with patch(
            'odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request',
            return_value=payload,
        ):
            stats = OminiFlowSyncService(self.env, instance).sync_customers()
        self.assertEqual(stats['failed'], 0)
        self.assertFalse(company_partner.ominiflow_id)
        created = self.env['res.partner'].search([('ominiflow_id', '=', '99')])
        self.assertEqual(len(created), 1)
        self.assertNotEqual(created.id, company_partner.id)

    def test_customer_sync_respects_time_budget(self):
        instance = self._create_instance()
        payload = FakeResponse(200, {
            'status': 'success',
            'contacts': [
                {'id': 1, 'name': 'A', 'phone': '911111111111'},
                {'id': 2, 'name': 'B', 'phone': '922222222222'},
            ],
        })
        monotonic = iter([0.0, 100.0])
        with patch(
            'odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request',
            return_value=payload,
        ), patch(
            'odoo.addons.ominiflow_odoo.services.sync_service.time.monotonic',
            side_effect=lambda: next(monotonic, 100.0),
        ):
            stats = OminiFlowSyncService(self.env, instance).sync_customers(time_budget=90)
        self.assertEqual(stats['remaining'], 2)
        self.assertEqual(stats['success'], 0)

    def test_order_sync_is_not_faked(self):
        instance = self._create_instance()
        stats = OminiFlowSyncService(self.env, instance).sync_orders()
        self.assertGreaterEqual(stats['failed'], 1)
        logs = self.env['ominiflow.sync.log'].search([
            ('instance_id', '=', instance.id),
            ('resource_type', '=', 'order'),
        ])
        self.assertTrue(logs)
        self.assertTrue(all(log.status == 'failed' for log in logs))
        if 'sale.order' in self.env:
            self.assertFalse(self.env['sale.order'].search([('client_order_ref', 'ilike', 'ominiflow')], limit=1))

    def test_inventory_sync_is_not_faked(self):
        instance = self._create_instance()
        stats = OminiFlowSyncService(self.env, instance).sync_inventory()
        self.assertGreaterEqual(stats['failed'], 1)
        logs = self.env['ominiflow.sync.log'].search([
            ('instance_id', '=', instance.id),
            ('resource_type', '=', 'inventory'),
            ('status', '=', 'failed'),
        ])
        self.assertTrue(logs)

    def test_sync_log_created(self):
        instance = self._create_instance()
        with patch(
            'odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request',
            return_value=_product_page([]),
        ):
            OminiFlowSyncService(self.env, instance).sync_products()
        logs = self.env['ominiflow.sync.log'].search([
            ('instance_id', '=', instance.id),
            ('resource_type', '=', 'product'),
        ])
        self.assertTrue(logs)
        self.assertNotIn('OMINI_', (logs[0].message or '') + (logs[0].error or ''))

    def test_rate_limit_retry(self):
        client = self._client()
        limited = FakeResponse(
            429,
            {'status': 'error', 'message': 'Rate limit exceeded', 'retry_after': 1},
            headers={'Retry-After': '1'},
        )
        ok = FakeResponse(200, {'status': 'success', 'company': {'id': 1, 'name': 'Co'}})
        with patch(
            'odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request',
            side_effect=[limited, ok],
        ), patch('odoo.addons.ominiflow_odoo.services.api_client.time.sleep'):
            payload = client.test_connection()
        self.assertEqual(payload['status'], 'success')
