from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.ominiflow_odoo.services.exceptions import (
    OminiFlowAPIError,
    OminiFlowValidationError,
)
from .common import FakeResponse, OminiFlowCaseMixin


@tagged('post_install', '-at_install', 'ominiflow')
class TestOminiFlowConnection(OminiFlowCaseMixin, TransactionCase):

    def test_module_models_exist(self):
        self.assertTrue(self.env['ir.model'].search([('model', '=', 'ominiflow.instance')]))
        self.assertTrue(self.env['ir.model'].search([('model', '=', 'ominiflow.sync.log')]))
        self.assertTrue(self.env['ir.model'].search([('model', '=', 'ominiflow.binding')]))

    def test_create_connection_without_calling_api(self):
        instance = self._create_instance()
        self.assertEqual(instance.connection_status, 'unknown')
        self.assertTrue(instance.api_base_url.startswith('https://'))

    def test_invalid_url_rejected(self):
        instance = self._create_instance(api_base_url='not-a-url')
        action = instance.action_test_connection()
        self.assertEqual(instance.connection_status, 'error')
        self.assertEqual(action['params']['type'], 'danger')
        self.assertNotIn('OMINI_', instance.last_error or '')

    def test_missing_api_key(self):
        instance = self._create_instance()
        instance.sudo().write({'api_key': False})
        with self.assertRaises(UserError):
            instance.action_test_connection()
        self.assertEqual(instance.connection_status, 'unknown')

    def test_connection_success(self):
        instance = self._create_instance()
        with self._patch_request(self._me_ok()):
            action = instance.action_test_connection()
        self.assertEqual(instance.connection_status, 'connected')
        self.assertEqual(instance.company_external_id, '10')
        self.assertFalse(instance.last_error)
        self.assertEqual(action['params']['type'], 'success')
        self.assertTrue(instance.last_connection_test)

    def test_authentication_failure_json_status(self):
        instance = self._create_instance()
        fake = FakeResponse(200, {'status': 'error', 'message': 'Invalid token'})
        with self._patch_request(fake):
            action = instance.action_test_connection()
        self.assertEqual(instance.connection_status, 'error')
        self.assertIn('Invalid token', instance.last_error)
        self.assertEqual(action['params']['type'], 'danger')
        self.assertNotIn('OMINI_test_key_not_real', instance.last_error)

    def test_http_401(self):
        instance = self._create_instance()
        with self._patch_request(FakeResponse(401, {'message': 'Unauthorized'})):
            instance.action_test_connection()
        self.assertEqual(instance.connection_status, 'error')

    def test_timeout(self):
        instance = self._create_instance()
        with patch(
            'odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request',
            side_effect=requests.Timeout(),
        ), patch('odoo.addons.ominiflow_odoo.services.api_client.time.sleep'):
            instance.action_test_connection()
        self.assertEqual(instance.connection_status, 'error')
        self.assertIn('time', (instance.last_error or '').lower())

    def test_invalid_json(self):
        client = self._client()
        with self._patch_request(FakeResponse(200, payload=None, invalid_json=True)):
            with self.assertRaises(OminiFlowAPIError):
                client.test_connection()

    def test_http_500(self):
        client = self._client()
        with self._patch_request(FakeResponse(500, {'message': 'crash'})):
            with self.assertRaises(OminiFlowAPIError):
                client.test_connection()

    def test_http_422(self):
        client = self._client()
        with self._patch_request(FakeResponse(422, {'message': 'sku invalid'})):
            with self.assertRaises(OminiFlowValidationError):
                client.create_product({'name': 'X'})

    def test_never_connected_without_http_success(self):
        instance = self._create_instance()
        with self._patch_request(FakeResponse(500, {'status': 'error', 'message': 'down'})):
            instance.action_test_connection()
        self.assertNotEqual(instance.connection_status, 'connected')
