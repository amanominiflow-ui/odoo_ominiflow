"""Reusable OminiFlow sync engine.

Idempotent: external ID first, then SKU (products) or phone (contacts).
Does not create sale.order or stock moves — those APIs are not published.
"""

import logging
import time

from odoo import fields

from .exceptions import OminiFlowError

_logger = logging.getLogger(__name__)

RESOURCE_PRODUCT = 'product'
RESOURCE_CUSTOMER = 'customer'
RESOURCE_ORDER = 'order'
RESOURCE_INVENTORY = 'inventory'

# HTTP button is killed at limit_time_real=120s. Stop earlier and keep progress.
CUSTOMER_HTTP_BUDGET_SECONDS = 90
CUSTOMER_COMMIT_EVERY = 25


class OminiFlowSyncService:
    def __init__(self, env, instance):
        self.env = env
        self.instance = instance
        self.client = instance._get_client()
        self.Log = env['ominiflow.sync.log']
        self.Binding = env['ominiflow.binding']

    def sync_all(self, customer_time_budget=None):
        product_stats = self.sync_products()
        customer_stats = self.sync_customers(time_budget=customer_time_budget)
        return {
            'products': product_stats,
            'customers': customer_stats,
        }

    def sync_products(self, direction='pull'):
        if direction == 'push':
            return self._push_products()
        return self._pull_products()

    def sync_customers(self, direction='pull', time_budget=None):
        if direction == 'push':
            return self._push_customers()
        return self._pull_customers(time_budget=time_budget)

    def sync_orders(self):
        return self._unsupported('order', 'pull', self.client.get_orders)

    def sync_inventory(self):
        return self._unsupported('inventory', 'pull', self.client.get_inventory)

    def _unsupported(self, resource_type, operation, caller):
        log = self.Log.create_log(
            self.instance,
            resource_type=resource_type,
            operation=operation,
            direction='from_ominiflow',
        )
        try:
            caller()
            message = 'Unexpected success from an unpublished API.'
            log.finish('failed', message=message, error=message)
            return self._empty_stats(failed=1)
        except NotImplementedError as exc:
            log.finish('failed', message=str(exc), error=str(exc))
            return self._empty_stats(failed=1, skipped=1)

    def _pull_products(self):
        stats = self._empty_stats()
        log = self.Log.create_log(
            self.instance,
            resource_type=RESOURCE_PRODUCT,
            operation='pull',
            direction='from_ominiflow',
        )
        Product = self.env['product.template']
        try:
            for row in self.client.iter_products(per_page=50):
                stats['processed'] += 1
                try:
                    created = self._import_product(Product, row)
                    if created:
                        stats['created'] += 1
                    else:
                        stats['updated'] += 1
                    stats['success'] += 1
                except Exception as exc:
                    stats['failed'] += 1
                    _logger.warning('OminiFlow product sync failed for %s: %s', row.get('id'), exc)
                    self.Log.create_log(
                        self.instance,
                        resource_type=RESOURCE_PRODUCT,
                        operation='pull',
                        direction='from_ominiflow',
                        external_id=str(row.get('id') or ''),
                        status='failed',
                        message='Product row failed.',
                        error=str(exc),
                    ).finish('failed', message='Product row failed.', error=str(exc))
            message = (
                f"Products: {stats['success']} ok "
                f"({stats['created']} created, {stats['updated']} updated), "
                f"{stats['failed']} failed."
            )
            log.finish('success' if stats['failed'] == 0 else 'failed', message=message)
        except OminiFlowError as exc:
            stats['failed'] += 1
            log.finish('failed', message=exc.user_message, error=exc.user_message)
        except Exception as exc:
            stats['failed'] += 1
            log.finish('failed', message='Product sync stopped unexpectedly.', error=str(exc))
            _logger.exception('OminiFlow product sync crashed')
        return stats

    def _import_product(self, Product, row):
        external_id = str(row.get('id') or '').strip()
        sku = (row.get('sku') or '').strip() or False
        if not external_id and not sku:
            raise ValueError('Product has no OminiFlow id or SKU; skipped to avoid duplicates.')

        product = self._find_bound_record(RESOURCE_PRODUCT, 'product.template', external_id)
        if not product and sku:
            product = Product.search([
                ('default_code', '=', sku),
                '|',
                ('company_id', '=', False),
                ('company_id', '=', self.instance.company_id.id),
            ], limit=1)

        vals = {
            'name': row.get('name') or 'OminiFlow product',
            'description': row.get('description') or False,
            'description_sale': row.get('description') or False,
            'list_price': float(row.get('price') or 0.0),
            'default_code': sku,
            'active': bool(row.get('is_available', True)),
            'company_id': self.instance.company_id.id,
            'ominiflow_id': external_id or False,
            'ominiflow_instance_id': self.instance.id,
            'ominiflow_last_sync': fields.Datetime.now(),
            'ominiflow_stock_quantity': float(row.get('stock_quantity') or 0.0),
        }
        created = False
        if product:
            product.write(vals)
        else:
            product = Product.create(vals)
            created = True

        if external_id:
            self.Binding.upsert(
                self.instance,
                RESOURCE_PRODUCT,
                external_id,
                'product.template',
                product.id,
            )
        return created

    def _push_products(self):
        stats = self._empty_stats()
        log = self.Log.create_log(
            self.instance,
            resource_type=RESOURCE_PRODUCT,
            operation='push',
            direction='to_ominiflow',
        )
        products = self.env['product.template'].search([
            '|',
            ('ominiflow_instance_id', '=', self.instance.id),
            ('company_id', 'in', [False, self.instance.company_id.id]),
        ])
        try:
            for product in products:
                if not product.default_code and not product.ominiflow_id:
                    stats['skipped'] += 1
                    continue
                stats['processed'] += 1
                payload = {
                    'name': product.name,
                    'description': product.description_sale or product.description or '',
                    'price': product.list_price,
                    'currency': product.company_id.currency_id.name or self.env.company.currency_id.name,
                    'sku': product.default_code or None,
                    'is_available': product.active,
                    'stock_quantity': int(product.ominiflow_stock_quantity or 0),
                    'sync_meta': False,
                }
                try:
                    if product.ominiflow_id:
                        result = self.client.update_product(product.ominiflow_id, payload)
                    else:
                        result = self.client.create_product(payload)
                    data = result.get('data') or {}
                    external_id = str(data.get('id') or product.ominiflow_id or '')
                    product.write({
                        'ominiflow_id': external_id or product.ominiflow_id,
                        'ominiflow_instance_id': self.instance.id,
                        'ominiflow_last_sync': fields.Datetime.now(),
                    })
                    if external_id:
                        self.Binding.upsert(
                            self.instance,
                            RESOURCE_PRODUCT,
                            external_id,
                            'product.template',
                            product.id,
                        )
                    stats['success'] += 1
                    stats['updated' if product.ominiflow_id else 'created'] += 1
                except Exception as exc:
                    stats['failed'] += 1
                    _logger.warning('OminiFlow product push failed for %s: %s', product.id, exc)
            message = (
                f"Pushed products: {stats['success']} ok, {stats['failed']} failed, "
                f"{stats['skipped']} skipped."
            )
            log.finish('success' if stats['failed'] == 0 else 'failed', message=message)
        except OminiFlowError as exc:
            stats['failed'] += 1
            log.finish('failed', message=exc.user_message, error=exc.user_message)
        return stats

    def _pull_customers(self, time_budget=None):
        stats = self._empty_stats()
        self._prepare_customer_caches()
        log = self.Log.create_log(
            self.instance,
            resource_type=RESOURCE_CUSTOMER,
            operation='pull',
            direction='from_ominiflow',
        )
        Partner = self._partner_env()
        started = time.monotonic()
        row_errors = []
        try:
            payload = self.client.get_contacts()
            contacts = payload.get('contacts') or payload.get('data') or []
            total = len(contacts)
            for index, row in enumerate(contacts):
                if time_budget and (time.monotonic() - started) >= time_budget:
                    stats['remaining'] = total - index
                    break
                external_id = str(row.get('id') or '').strip()
                if external_id and external_id in self._customer_bindings:
                    stats['skipped'] += 1
                    continue
                stats['processed'] += 1
                try:
                    created = self._import_partner(Partner, row)
                    if created:
                        stats['created'] += 1
                    else:
                        stats['updated'] += 1
                    stats['success'] += 1
                except Exception as exc:
                    stats['failed'] += 1
                    if len(row_errors) < 5:
                        row_errors.append(self._row_error_message(external_id or 'contact', exc))
                    _logger.warning('OminiFlow contact sync failed for %s: %s', row.get('id'), exc)
                if stats['processed'] and stats['processed'] % CUSTOMER_COMMIT_EVERY == 0:
                    refreshed = self._commit_customer_progress(log, stats, total)
                    if refreshed:
                        log = refreshed
                    Partner = self._partner_env()
            message = (
                f"Customers: {stats['success']} ok "
                f"({stats['created']} created, {stats['updated']} updated), "
                f"{stats['failed']} failed, {stats['skipped']} already synced"
            )
            if stats.get('remaining'):
                message += (
                    f", {stats['remaining']} remaining. "
                    'Click Sync Customers again or wait for the hourly cron.'
                )
            if row_errors:
                message += ' | ' + ' ; '.join(row_errors)
            status = 'failed' if stats['failed'] and not stats['success'] else 'success'
            if stats['failed'] and stats['success']:
                status = 'success'
            log.finish(status, message=message, error='\n'.join(row_errors) or False)
        except OminiFlowError as exc:
            stats['failed'] += 1
            log.finish('failed', message=exc.user_message, error=exc.user_message)
        except Exception as exc:
            stats['failed'] += 1
            log.finish('failed', message='Customer sync stopped unexpectedly.', error=str(exc))
            _logger.exception('OminiFlow customer sync crashed')
        return stats

    def _import_partner(self, Partner, row):
        external_id = str(row.get('id') or '').strip()
        phone = (row.get('phone') or '').strip()
        email = (row.get('email') or '').strip() or False
        if not external_id and not phone and not email:
            raise ValueError('Contact has no id, phone, or email; skipped to avoid duplicates.')

        partner = Partner.browse()
        bound_id = self._customer_bindings.get(external_id) if external_id else None
        if bound_id:
            partner = Partner.browse(bound_id).exists()
            if self._is_company_entity_partner(partner):
                partner = Partner.browse()
        if not partner and external_id:
            partner = Partner.search([
                ('ominiflow_id', '=', external_id),
            ] + self._partner_company_domain(), limit=1)
            if self._is_company_entity_partner(partner):
                partner = Partner.browse()
        if not partner and phone:
            partner = self._find_partner_by_phone(Partner, phone)
        if not partner and email:
            partner = Partner.search([
                ('email', '=ilike', email),
            ] + self._partner_company_domain(), limit=1)
            if self._is_company_entity_partner(partner):
                partner = Partner.browse()

        vals = {
            'name': row.get('name') or phone or email or 'OminiFlow contact',
            'phone': phone or False,
            'email': email,
            'company_id': self.instance.company_id.id,
            'ominiflow_id': external_id or False,
            'ominiflow_instance_id': self.instance.id,
            'ominiflow_last_sync': fields.Datetime.now(),
        }
        created = False
        if partner:
            update = {
                'ominiflow_id': vals['ominiflow_id'] or partner.ominiflow_id,
                'ominiflow_instance_id': self.instance.id,
                'ominiflow_last_sync': vals['ominiflow_last_sync'],
            }
            if phone and not partner.phone:
                update['phone'] = phone
            if email and not partner.email:
                update['email'] = email
            if row.get('name') and partner.name in ('', partner.phone, partner.email):
                update['name'] = row['name']
            partner.write(update)
        else:
            partner = Partner.create(vals)
            created = True

        if external_id:
            self._bind_customer(external_id, partner.id)
        return created

    def _push_customers(self):
        stats = self._empty_stats()
        log = self.Log.create_log(
            self.instance,
            resource_type=RESOURCE_CUSTOMER,
            operation='push',
            direction='to_ominiflow',
        )
        partners = self.env['res.partner'].search([
            ('ominiflow_instance_id', '=', self.instance.id),
        ])
        try:
            for partner in partners:
                if not partner.phone:
                    stats['skipped'] += 1
                    continue
                stats['processed'] += 1
                payload = {
                    'phone': partner.phone,
                    'name': partner.name,
                }
                if partner.email:
                    payload['email'] = partner.email
                try:
                    result = self.client.create_contact(payload)
                    contact = result.get('contact') or result.get('data') or {}
                    external_id = str(contact.get('id') or partner.ominiflow_id or '')
                    partner.write({
                        'ominiflow_id': external_id or partner.ominiflow_id,
                        'ominiflow_last_sync': fields.Datetime.now(),
                    })
                    if external_id:
                        self.Binding.upsert(
                            self.instance,
                            RESOURCE_CUSTOMER,
                            external_id,
                            'res.partner',
                            partner.id,
                        )
                    stats['success'] += 1
                except Exception as exc:
                    stats['failed'] += 1
                    _logger.warning('OminiFlow contact push failed for %s: %s', partner.id, exc)
            message = (
                f"Pushed customers: {stats['success']} ok, {stats['failed']} failed, "
                f"{stats['skipped']} skipped (no phone)."
            )
            log.finish('success' if stats['failed'] == 0 else 'failed', message=message)
        except OminiFlowError as exc:
            stats['failed'] += 1
            log.finish('failed', message=exc.user_message, error=exc.user_message)
        return stats

    def _find_bound_record(self, resource_type, odoo_model, external_id):
        if not external_id:
            return self.env[odoo_model].browse()
        binding = self.Binding.search([
            ('instance_id', '=', self.instance.id),
            ('resource_type', '=', resource_type),
            ('external_id', '=', str(external_id)),
        ], limit=1)
        if binding and binding.odoo_res_id:
            record = self.env[odoo_model].browse(binding.odoo_res_id).exists()
            if record:
                return record
        return self.env[odoo_model].browse()

    def _find_partner_by_phone(self, Partner, phone):
        digits = self.normalize_phone(phone)
        if not digits:
            return Partner.browse()
        variants = {phone, digits, '+' + digits}
        if digits.startswith('91') and len(digits) > 10:
            local = digits[2:]
            variants.update({local, '+' + digits})
        elif len(digits) == 10:
            variants.update({'91' + digits, '+91' + digits})
        partner = Partner.search([
            ('phone', 'in', list(variants)),
        ] + self._partner_company_domain(), limit=1)
        if partner and not self._is_company_entity_partner(partner):
            return partner
        return Partner.browse()

    def _partner_env(self):
        return self.env['res.partner'].with_company(self.instance.company_id).with_context(
            tracking_disable=True,
            mail_create_nolog=True,
            mail_notrack=True,
            mail_auto_subscribe_no_notify=True,
        )

    def _prepare_customer_caches(self):
        self._reserved_partner_ids = frozenset(
            self.env['res.company'].sudo().search([]).partner_id.ids
        )
        domain = [
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.instance.company_id.id),
        ]
        if self._reserved_partner_ids:
            domain = [('id', 'not in', list(self._reserved_partner_ids))] + domain
        self._cached_partner_domain = domain
        self._customer_bindings = {
            b.external_id: b.odoo_res_id
            for b in self.Binding.search([
                ('instance_id', '=', self.instance.id),
                ('resource_type', '=', RESOURCE_CUSTOMER),
            ])
        }

    def _partner_company_domain(self):
        return list(getattr(self, '_cached_partner_domain', None) or [
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.instance.company_id.id),
        ])

    def _is_company_entity_partner(self, partner):
        reserved = getattr(self, '_reserved_partner_ids', None)
        if reserved is None:
            reserved = frozenset(self.env['res.company'].sudo().search([]).partner_id.ids)
            self._reserved_partner_ids = reserved
        return bool(partner) and partner.id in reserved

    def _bind_customer(self, external_id, partner_id):
        if not external_id or not partner_id:
            return
        bindings = getattr(self, '_customer_bindings', None)
        if bindings is None:
            self._customer_bindings = {}
            bindings = self._customer_bindings
        if bindings.get(str(external_id)) == partner_id:
            return
        try:
            with self.env.cr.savepoint():
                self.Binding.create({
                    'instance_id': self.instance.id,
                    'resource_type': RESOURCE_CUSTOMER,
                    'external_id': str(external_id),
                    'odoo_model': 'res.partner',
                    'odoo_res_id': partner_id,
                })
        except Exception:
            self.Binding.upsert(
                self.instance,
                RESOURCE_CUSTOMER,
                external_id,
                'res.partner',
                partner_id,
            )
        bindings[str(external_id)] = partner_id

    def _commit_customer_progress(self, log, stats, total):
        if self.env.cr.__class__.__name__ != 'Cursor':
            return
        log.write({
            'message': (
                f"In progress: {stats['success']} ok, {stats['failed']} failed, "
                f"{stats['skipped']} already synced / {total} total."
            ),
        })
        log_id = log.id
        instance_id = self.instance.id
        self.env.cr.commit()
        self.instance = self.env['ominiflow.instance'].browse(instance_id)
        return self.Log.browse(log_id)

    @staticmethod
    def _row_error_message(prefix, exc):
        text = str(exc).strip().split('\n')[0]
        if len(text) > 180:
            text = text[:177] + '...'
        return f'{prefix}: {text}'

    @staticmethod
    def normalize_phone(phone):
        if not phone:
            return ''
        return ''.join(ch for ch in str(phone) if ch.isdigit())

    @staticmethod
    def _empty_stats(failed=0, skipped=0):
        return {
            'processed': 0,
            'created': 0,
            'updated': 0,
            'success': 0,
            'failed': failed,
            'skipped': skipped,
            'remaining': 0,
        }

    @staticmethod
    def format_stats(label, stats):
        message = (
            f"{label}: {stats.get('success', 0)} succeeded, "
            f"{stats.get('created', 0)} created, "
            f"{stats.get('updated', 0)} updated, "
            f"{stats.get('failed', 0)} failed, "
            f"{stats.get('skipped', 0)} skipped."
        )
        remaining = stats.get('remaining') or 0
        if remaining:
            message += f" {remaining} remaining — click Sync Customers again."
        return message
