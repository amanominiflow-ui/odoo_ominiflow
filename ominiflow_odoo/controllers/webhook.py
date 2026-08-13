import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class OminiFlowWebhookController(http.Controller):
    """Inbound webhooks from the OminiFlow Developer Portal.

    Real contract (DeliverDeveloperWebhook):
    - Header X-Ominiflow-Signature: sha256=<hmac_sha256(raw_body, secret)>
    - Header X-Ominiflow-Event: message.received | ...
    - Body: {id, event, created_at, data}
    Events are WhatsApp lifecycle events, not product/order sync.
    """

    @http.route(
        '/ominiflow/webhook/<int:instance_id>',
        type='http',
        auth='public',
        csrf=False,
        methods=['POST'],
        save_session=False,
    )
    def receive(self, instance_id, **_kwargs):
        instance = request.env['ominiflow.instance'].sudo().browse(instance_id)
        if not instance.exists() or not instance.active:
            return request.make_json_response({'status': 'error', 'message': 'Unknown connection.'}, status=404)

        raw = request.httprequest.get_data() or b''
        secret = (instance.webhook_secret or '').strip()
        if not secret:
            _logger.warning('OminiFlow webhook rejected: no signing secret on instance %s', instance_id)
            return request.make_json_response({'status': 'error', 'message': 'Webhook secret is not configured.'}, status=401)

        header = request.httprequest.headers.get('X-Ominiflow-Signature', '')
        if not self._valid_signature(secret, raw, header):
            _logger.warning('OminiFlow webhook rejected: invalid signature for instance %s', instance_id)
            return request.make_json_response({'status': 'error', 'message': 'Invalid signature.'}, status=401)

        try:
            payload = json.loads(raw.decode('utf-8') or '{}')
        except (UnicodeDecodeError, json.JSONDecodeError):
            return request.make_json_response({'status': 'error', 'message': 'Invalid JSON.'}, status=400)

        if not isinstance(payload, dict):
            return request.make_json_response({'status': 'error', 'message': 'Invalid payload.'}, status=400)

        event_id = str(payload.get('id') or '').strip()
        event_name = (
            payload.get('event')
            or request.httprequest.headers.get('X-Ominiflow-Event')
            or 'unknown'
        )
        if event_id:
            Binding = request.env['ominiflow.binding'].sudo()
            already = Binding.search_count([
                ('instance_id', '=', instance.id),
                ('resource_type', '=', 'webhook_event'),
                ('external_id', '=', event_id),
            ])
            if already:
                return request.make_json_response({'status': 'ok', 'duplicate': True}, status=200)

        Log = request.env['ominiflow.sync.log'].sudo()
        log = Log.create_log(
            instance,
            resource_type='webhook',
            operation=str(event_name),
            direction='inbound',
            external_id=event_id,
            status='running',
            message='Webhook accepted. WhatsApp events are logged only; they do not sync products or orders.',
        )
        if event_id:
            request.env['ominiflow.binding'].sudo().upsert(
                instance,
                'webhook_event',
                event_id,
                'ominiflow.sync.log',
                log.id,
            )
        log.finish('success', message='Webhook stored.')
        return request.make_json_response({'status': 'ok'}, status=200)

    @staticmethod
    def _valid_signature(secret, raw_body, header):
        if not header or not header.startswith('sha256='):
            return False
        expected = hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
        provided = header.split('=', 1)[1].strip()
        if len(expected) != len(provided):
            return False
        return hmac.compare_digest(expected, provided)
