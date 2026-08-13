import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services.api_client import OminiFlowClient
from ..services.exceptions import (
    OminiFlowAPIError,
    OminiFlowAuthenticationError,
    OminiFlowConnectionError,
    OminiFlowError,
    OminiFlowValidationError,
)
from ..services.sync_service import CUSTOMER_HTTP_BUDGET_SECONDS, OminiFlowSyncService

_logger = logging.getLogger(__name__)


class OminiFlowInstance(models.Model):
    _name = 'ominiflow.instance'
    _description = 'OminiFlow Connection'
    _check_company_auto = True
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    api_base_url = fields.Char(
        string='API Base URL',
        required=True,
        help='OminiFlow origin only, for example https://whatsapp.ominiflow.com',
    )
    api_key = fields.Char(
        string='API Key',
        copy=False,
        groups='ominiflow_odoo.group_ominiflow_manager',
        help='Developer Portal key starting with OMINI_. Never shown in lists or logs.',
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    connection_status = fields.Selection(
        [
            ('unknown', 'Not tested'),
            ('connected', 'Connected'),
            ('error', 'Error'),
        ],
        default='unknown',
        required=True,
        copy=False,
    )
    last_connection_test = fields.Datetime(copy=False)
    last_error = fields.Text(copy=False)
    sync_products = fields.Boolean(string='Sync products', default=True)
    sync_customers = fields.Boolean(string='Sync customers', default=True)
    sync_orders = fields.Boolean(
        string='Sync orders',
        default=False,
        readonly=True,
        help='Disabled: OminiFlow does not publish a public orders REST API.',
    )
    sync_inventory = fields.Boolean(
        string='Sync inventory',
        default=False,
        readonly=True,
        help='Disabled: OminiFlow only exposes catalog stock_quantity on products, not warehouse stock.',
    )
    webhook_secret = fields.Char(
        string='Webhook signing secret',
        copy=False,
        groups='ominiflow_odoo.group_ominiflow_manager',
        help='HMAC secret from the OminiFlow Developer Portal webhook. Shown once when created there.',
    )
    company_external_id = fields.Char(string='OminiFlow company ID', copy=False, readonly=True)
    last_sync = fields.Datetime(compute='_compute_sync_stats', store=False)
    sync_success_count = fields.Integer(compute='_compute_sync_stats')
    sync_failed_count = fields.Integer(compute='_compute_sync_stats')
    log_ids = fields.One2many('ominiflow.sync.log', 'instance_id', string='Sync logs')
    binding_count = fields.Integer(compute='_compute_sync_stats')

    _uniq_name_company = models.Constraint(
        'unique(name, company_id)',
        'A connection with this name already exists for the company.',
    )

    @api.depends('log_ids.status', 'log_ids.finished_at')
    def _compute_sync_stats(self):
        Log = self.env['ominiflow.sync.log']
        Binding = self.env['ominiflow.binding']
        for rec in self:
            logs = Log.search([('instance_id', '=', rec.id)])
            rec.sync_success_count = len(logs.filtered(lambda l: l.status == 'success'))
            rec.sync_failed_count = len(logs.filtered(lambda l: l.status == 'failed'))
            finished = logs.filtered('finished_at').sorted('finished_at', reverse=True)
            rec.last_sync = finished[:1].finished_at if finished else False
            rec.binding_count = Binding.search_count([('instance_id', '=', rec.id)])

    def _get_client(self):
        self.ensure_one()
        creds = self.sudo()
        return OminiFlowClient(creds.api_base_url, creds.api_key)

    def action_test_connection(self):
        self.ensure_one()
        try:
            OminiFlowClient.validate_base_url(self.api_base_url)
            if not self.sudo().api_key:
                raise UserError(_('Enter an OminiFlow API key before testing the connection.'))
            payload = self._get_client().test_connection()
            company = payload.get('company') or {}
            self.write({
                'connection_status': 'connected',
                'last_connection_test': fields.Datetime.now(),
                'last_error': False,
                'company_external_id': str(company.get('id') or ''),
            })
            company_name = company.get('name') or _('OminiFlow')
            return self._notify(
                _('Connected'),
                _('Successfully connected to %(name)s.', name=company_name),
                'success',
            )
        except OminiFlowAuthenticationError as exc:
            return self._mark_error(_('Authentication failed: %s') % exc.user_message)
        except OminiFlowConnectionError as exc:
            return self._mark_error(exc.user_message)
        except OminiFlowValidationError as exc:
            return self._mark_error(exc.user_message)
        except OminiFlowAPIError as exc:
            return self._mark_error(exc.user_message)
        except OminiFlowError as exc:
            return self._mark_error(exc.user_message)

    def _mark_error(self, message):
        self.write({
            'connection_status': 'error',
            'last_connection_test': fields.Datetime.now(),
            'last_error': message,
        })
        return self._notify(_('Connection failed'), message, 'danger')

    def action_sync_products(self):
        self.ensure_one()
        self._assert_can_sync('products')
        stats = OminiFlowSyncService(self.env, self).sync_products()
        return self._notify(_('Product sync'), OminiFlowSyncService.format_stats(_('Products'), stats), 'success' if not stats.get('failed') else 'warning')

    def action_sync_customers(self):
        self.ensure_one()
        self._assert_can_sync('customers')
        stats = OminiFlowSyncService(self.env, self).sync_customers(
            time_budget=CUSTOMER_HTTP_BUDGET_SECONDS,
        )
        ntype = 'warning' if stats.get('failed') or stats.get('remaining') else 'success'
        return self._notify(_('Customer sync'), OminiFlowSyncService.format_stats(_('Customers'), stats), ntype)

    def action_sync_all(self):
        self.ensure_one()
        self._assert_can_sync('all')
        result = OminiFlowSyncService(self.env, self).sync_all(
            customer_time_budget=CUSTOMER_HTTP_BUDGET_SECONDS,
        )
        message = '%s\n%s' % (
            OminiFlowSyncService.format_stats(_('Products'), result['products']),
            OminiFlowSyncService.format_stats(_('Customers'), result['customers']),
        )
        failed = result['products'].get('failed', 0) + result['customers'].get('failed', 0)
        return self._notify(_('Sync all'), message, 'success' if not failed else 'warning')

    def action_open_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sync Logs'),
            'res_model': 'ominiflow.sync.log',
            'view_mode': 'list,form',
            'domain': [('instance_id', '=', self.id)],
            'context': {'default_instance_id': self.id},
        }

    def _assert_can_sync(self, what):
        if not self.active:
            raise UserError(_('Activate the connection before synchronizing.'))
        if what in ('products', 'all') and not self.sync_products:
            raise UserError(_('Enable product sync on this connection first.'))
        if what in ('customers', 'all') and not self.sync_customers:
            raise UserError(_('Enable customer sync on this connection first.'))

    def _notify(self, title, message, ntype):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': ntype,
                'sticky': ntype != 'success',
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    @api.model
    def _cron_sync_products(self):
        self._cron_sync('products')

    @api.model
    def _cron_sync_customers(self):
        self._cron_sync('customers')

    @api.model
    def _cron_sync(self, resource):
        auto = self.env['ir.config_parameter'].sudo().get_param('ominiflow_odoo.auto_sync', 'True')
        if str(auto).lower() in ('false', '0', 'off'):
            return
        field = 'sync_products' if resource == 'products' else 'sync_customers'
        instances = self.search([('active', '=', True), (field, '=', True)])
        for instance in instances:
            try:
                service = OminiFlowSyncService(self.env, instance)
                if resource == 'products':
                    service.sync_products()
                else:
                    service.sync_customers()
            except Exception:
                _logger.exception(
                    'OminiFlow scheduled %s sync failed for instance %s',
                    resource,
                    instance.id,
                )
