from unittest.mock import patch

from odoo.addons.ominiflow_odoo.services.api_client import OminiFlowClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, invalid_json=False):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self._invalid_json = invalid_json
        if invalid_json:
            self.content = b'<html>error</html>'
        elif payload is None:
            self.content = b''
        else:
            self.content = b'{"ok": true}'
        self.ok = 200 <= status_code < 400

    def json(self):
        if self._invalid_json:
            raise ValueError('invalid json')
        return self._payload


class OminiFlowCaseMixin:
    def _create_instance(self, **values):
        vals = {
            'name': 'Test OminiFlow',
            'api_base_url': 'https://whatsapp.ominiflow.com',
            'api_key': 'OMINI_test_key_not_real',
            'company_id': self.env.company.id,
            'sync_products': True,
            'sync_customers': True,
        }
        vals.update(values)
        return self.env['ominiflow.instance'].create(vals)

    def _patch_request(self, response_or_list):
        return patch(
            'odoo.addons.ominiflow_odoo.services.api_client.requests.Session.request',
            side_effect=response_or_list if isinstance(response_or_list, list) else [response_or_list],
        )

    def _me_ok(self):
        return FakeResponse(200, {
            'status': 'success',
            'user': {'id': 1, 'name': 'Test'},
            'company': {'id': 10, 'name': 'Demo Co', 'phone': '919999999999'},
        })

    def _client(self, instance=None):
        instance = instance or self._create_instance()
        return OminiFlowClient(instance.api_base_url, instance.sudo().api_key)
