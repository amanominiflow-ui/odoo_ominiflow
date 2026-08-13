"""Reusable OminiFlow HTTP client.

Talks only to documented PHP endpoints under /api/wpbox/*.
Does not invent order or inventory routes.
"""

import logging
import time
from urllib.parse import urlparse

import requests

from .exceptions import (
    OminiFlowAPIError,
    OminiFlowAuthenticationError,
    OminiFlowConnectionError,
    OminiFlowValidationError,
)

_logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_STATUSES = {429, 502, 503, 504}


class OminiFlowClient:
    """HTTP client for the existing OminiFlow PHP public API."""

    def __init__(self, base_url, api_key, timeout=DEFAULT_TIMEOUT):
        self.base_url = self._normalize_base_url(base_url)
        self.api_key = (api_key or '').strip()
        self.timeout = timeout
        self.session = requests.Session()

    @staticmethod
    def _normalize_base_url(base_url):
        url = (base_url or '').strip().rstrip('/')
        for suffix in ('/api/wpbox', '/api'):
            if url.endswith(suffix):
                url = url[:-len(suffix)]
                break
        return url

    @staticmethod
    def validate_base_url(base_url):
        parsed = urlparse((base_url or '').strip())
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise OminiFlowValidationError(
                'Enter a valid OminiFlow URL starting with http:// or https://.'
            )
        return True

    def _url(self, path):
        path = path if path.startswith('/') else f'/{path}'
        if path.startswith('/api/'):
            return f'{self.base_url}{path}'
        return f'{self.base_url}/api/wpbox{path}'

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

    def _safe_log_url(self, url):
        return url.split('?')[0]

    def request(self, method, path, *, params=None, json_body=None):
        if not self.api_key:
            raise OminiFlowAuthenticationError('API key is missing. Add it on the connection.')
        self.validate_base_url(self.base_url)

        url = self._url(path)
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json_body,
                    timeout=self.timeout,
                )
            except requests.Timeout as exc:
                last_error = OminiFlowConnectionError(
                    'OminiFlow did not respond in time. Check the URL and try again.'
                )
                _logger.warning('OminiFlow timeout on %s %s (attempt %s)', method, self._safe_log_url(url), attempt)
                if attempt >= MAX_RETRIES:
                    raise last_error from exc
                time.sleep(min(2 ** attempt, 8))
                continue
            except requests.RequestException as exc:
                last_error = OminiFlowConnectionError(
                    'Could not reach OminiFlow. Check the URL and network connection.'
                )
                _logger.warning(
                    'OminiFlow connection error on %s %s (attempt %s): %s',
                    method,
                    self._safe_log_url(url),
                    attempt,
                    exc.__class__.__name__,
                )
                if attempt >= MAX_RETRIES:
                    raise last_error from exc
                time.sleep(min(2 ** attempt, 8))
                continue

            _logger.info(
                'OminiFlow %s %s -> HTTP %s (attempt %s)',
                method,
                self._safe_log_url(url),
                response.status_code,
                attempt,
            )

            if response.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                wait = self._retry_after_seconds(response)
                _logger.warning(
                    'OminiFlow HTTP %s on %s, retrying in %ss',
                    response.status_code,
                    self._safe_log_url(url),
                    wait,
                )
                time.sleep(wait)
                continue

            return self._evaluate_response(response)

        if last_error:
            raise last_error
        raise OminiFlowAPIError('OminiFlow request failed after retries.')

    @staticmethod
    def _retry_after_seconds(response):
        header = response.headers.get('Retry-After')
        if header:
            try:
                return max(1, min(int(float(header)), 60))
            except (TypeError, ValueError):
                pass
        try:
            payload = response.json()
            retry_after = payload.get('retry_after')
            if retry_after is not None:
                return max(1, min(int(retry_after), 60))
        except ValueError:
            pass
        return 2

    def _evaluate_response(self, response):
        payload = self._parse_json(response)
        status = response.status_code
        json_status = payload.get('status') if isinstance(payload, dict) else None
        message = self._extract_message(payload)

        if status in (401, 403) or self._is_auth_failure(message, json_status, status):
            raise OminiFlowAuthenticationError(
                message or 'OminiFlow rejected the API key.',
                http_status=status or 401,
                payload=payload,
            )
        if status in (400, 409, 422) or json_status == 'error' and status in (400, 409, 422):
            raise OminiFlowValidationError(
                message or 'OminiFlow rejected the request data.',
                http_status=status,
                payload=payload,
            )
        if status == 404:
            raise OminiFlowAPIError(
                message or 'OminiFlow could not find that record.',
                http_status=status,
                payload=payload,
            )
        if status == 429:
            raise OminiFlowAPIError(
                message or 'OminiFlow rate limit exceeded. Wait and try again.',
                http_status=status,
                payload=payload,
            )
        if status >= 500:
            raise OminiFlowAPIError(
                'OminiFlow is temporarily unavailable. Try again later.',
                http_status=status,
                payload=payload,
            )
        if json_status == 'error':
            raise OminiFlowAPIError(
                message or 'OminiFlow returned an error.',
                http_status=status,
                payload=payload,
            )
        if status >= 400:
            raise OminiFlowAPIError(
                message or f'OminiFlow returned HTTP {status}.',
                http_status=status,
                payload=payload,
            )
        return payload

    def _parse_json(self, response):
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise OminiFlowAPIError(
                'OminiFlow returned a response that is not valid JSON.',
                http_status=response.status_code,
            ) from exc

    @staticmethod
    def _extract_message(payload):
        if not isinstance(payload, dict):
            return ''
        for key in ('message', 'errMsg'):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        errors = payload.get('errors')
        if isinstance(errors, dict) and errors:
            first = next(iter(errors.values()))
            if isinstance(first, list) and first:
                return str(first[0])
            return str(first)
        if isinstance(errors, str) and errors.strip():
            return errors.strip()
        return ''

    @staticmethod
    def _is_auth_failure(message, json_status, http_status):
        if http_status in (401, 403):
            return True
        text = (message or '').lower()
        return json_status == 'error' and (
            'invalid token' in text
            or 'api token has expired' in text
            or 'invalid api key' in text
            or 'unauthorized' in text
        )

    def get(self, path, params=None):
        return self.request('GET', path, params=params)

    def post(self, path, json_body=None, params=None):
        return self.request('POST', path, json_body=json_body, params=params)

    def put(self, path, json_body=None):
        return self.request('PUT', path, json_body=json_body)

    def patch(self, path, json_body=None):
        return self.request('PATCH', path, json_body=json_body)

    def test_connection(self):
        """GET /api/wpbox/me — real health/auth check used by Developer Portal."""
        payload = self.get('/me')
        if not isinstance(payload, dict) or payload.get('status') not in (None, 'success', True):
            raise OminiFlowAPIError(
                'OminiFlow connection test did not return a success status.',
                payload=payload,
            )
        return payload

    def get_products(self, page=1, per_page=50):
        per_page = max(1, min(int(per_page or 50), 100))
        page = max(1, int(page or 1))
        return self.get('/ecommerce/products', params={'page': page, 'per_page': per_page})

    def iter_products(self, per_page=50):
        page = 1
        while True:
            payload = self.get_products(page=page, per_page=per_page)
            rows = payload.get('data') or []
            for row in rows:
                yield row
            pagination = payload.get('pagination') or {}
            current = int(pagination.get('current_page') or page)
            last = int(pagination.get('last_page') or current)
            if current >= last or not rows:
                break
            page = current + 1

    def create_product(self, values):
        return self.post('/ecommerce/products', json_body=values)

    def update_product(self, external_id, values):
        return self.put(f'/ecommerce/products/{int(external_id)}', json_body=values)

    def get_categories(self, page=1, per_page=50):
        per_page = max(1, min(int(per_page or 50), 100))
        page = max(1, int(page or 1))
        return self.get('/ecommerce/categories', params={'page': page, 'per_page': per_page})

    def get_contacts(self):
        """GET /api/wpbox/getContacts — PHP returns the full company contact list."""
        return self.get('/getContacts')

    def create_contact(self, values):
        return self.post('/makeContact', json_body=values)

    def get_contact(self, contact_id=None, phone=None):
        params = {}
        if contact_id:
            params['contact_id'] = contact_id
        if phone:
            params['phone'] = phone
        if not params:
            raise OminiFlowValidationError('Provide contact_id or phone to fetch a contact.')
        return self.get('/getSingleContact', params=params)

    def get_orders(self, *args, **kwargs):
        # TODO: OminiFlow PHP has no public REST list/get for ecommerce orders
        # (web UI only: modules/EcommerceWhatsapp OrderController).
        raise NotImplementedError(
            'OminiFlow does not publish a public orders API. '
            'An endpoint such as GET /api/wpbox/ecommerce/orders is required.'
        )

    def get_order(self, *args, **kwargs):
        # TODO: same as get_orders — no public order GET in the PHP app.
        raise NotImplementedError(
            'OminiFlow does not publish a public order API. '
            'An endpoint such as GET /api/wpbox/ecommerce/orders/{id} is required.'
        )

    def get_inventory(self, *args, **kwargs):
        # TODO: no warehouse/location inventory API. stock_quantity lives on products.
        raise NotImplementedError(
            'OminiFlow does not publish a warehouse inventory API. '
            'Catalog quantity is the product field stock_quantity.'
        )
