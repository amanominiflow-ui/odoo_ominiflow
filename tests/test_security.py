import hashlib
import hmac

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from odoo.addons.ominiflow_odoo.controllers.webhook import OminiFlowWebhookController
from .common import OminiFlowCaseMixin


@tagged('post_install', '-at_install', 'ominiflow')
class TestOminiFlowSecurity(OminiFlowCaseMixin, TransactionCase):

    def setUp(self):
        super().setUp()
        self.instance = self._create_instance()
        company = self.env.company
        self.user = self.env['res.users'].create({
            'name': 'OminiFlow User',
            'login': 'ominiflow_user_test',
            'email': 'of-user@example.com',
            'company_id': company.id,
            'company_ids': [(6, 0, [company.id])],
            'group_ids': [(6, 0, [self.env.ref('ominiflow_odoo.group_ominiflow_user').id])],
        })
        self.manager = self.env['res.users'].create({
            'name': 'OminiFlow Manager',
            'login': 'ominiflow_manager_test',
            'email': 'of-manager@example.com',
            'company_id': company.id,
            'company_ids': [(6, 0, [company.id])],
            'group_ids': [(6, 0, [self.env.ref('ominiflow_odoo.group_ominiflow_manager').id])],
        })

    def test_user_cannot_read_api_key(self):
        with self.assertRaises(AccessError):
            self.instance.with_user(self.user).api_key

    def test_manager_can_read_api_key(self):
        key = self.instance.with_user(self.manager).api_key
        self.assertTrue(key)
        self.assertTrue(key.startswith('OMINI_'))

    def test_user_cannot_create_connection(self):
        with self.assertRaises(AccessError):
            self.env['ominiflow.instance'].with_user(self.user).create({
                'name': 'Forbidden',
                'api_base_url': 'https://whatsapp.ominiflow.com',
                'company_id': self.env.company.id,
            })

    def test_user_can_read_instance_name(self):
        name = self.instance.with_user(self.user).name
        self.assertEqual(name, 'Test OminiFlow')

    def test_company_rule(self):
        other_company = self.env['res.company'].create({'name': 'Other Co'})
        other = self._create_instance(name='Other connection', company_id=other_company.id)
        visible = self.env['ominiflow.instance'].with_user(self.manager).search([])
        self.assertIn(self.instance, visible)
        self.assertNotIn(other, visible)

    def test_webhook_hmac_matches_ominiflow_php(self):
        secret = 'portal-webhook-secret'
        body = b'{"id":"evt_abc","event":"message.received","data":{}}'
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(
            OminiFlowWebhookController._valid_signature(secret, body, 'sha256=' + digest)
        )
        self.assertFalse(
            OminiFlowWebhookController._valid_signature(secret, body, 'sha256=deadbeef')
        )
        self.assertFalse(
            OminiFlowWebhookController._valid_signature(secret, body, '')
        )
