from odoo import fields, models, _
from odoo.exceptions import UserError

from ..services.sync_service import OminiFlowSyncService


class OminiFlowSyncWizard(models.TransientModel):
    _name = 'ominiflow.sync.wizard'
    _description = 'OminiFlow Sync Wizard'

    instance_id = fields.Many2one(
        'ominiflow.instance',
        string='Connection',
        required=True,
        default=lambda self: self.env.context.get('active_id')
        if self.env.context.get('active_model') == 'ominiflow.instance'
        else False,
    )
    resource_type = fields.Selection(
        [
            ('products', 'Products'),
            ('customers', 'Customers'),
            ('all', 'Products and customers'),
        ],
        required=True,
        default='all',
    )
    direction = fields.Selection(
        [
            ('pull', 'OminiFlow → Odoo'),
            ('push', 'Odoo → OminiFlow'),
        ],
        required=True,
        default='pull',
        help='Push is supported for products (create/update catalog) and contacts with a phone number.',
    )

    def action_run(self):
        self.ensure_one()
        instance = self.instance_id
        if not instance.active:
            raise UserError(_('Activate the connection before synchronizing.'))
        service = OminiFlowSyncService(self.env, instance)
        if self.resource_type == 'products':
            stats = service.sync_products(direction=self.direction)
            message = OminiFlowSyncService.format_stats(_('Products'), stats)
            failed = stats.get('failed')
        elif self.resource_type == 'customers':
            stats = service.sync_customers(direction=self.direction)
            message = OminiFlowSyncService.format_stats(_('Customers'), stats)
            failed = stats.get('failed')
        else:
            if self.direction == 'push':
                products = service.sync_products(direction='push')
                customers = service.sync_customers(direction='push')
            else:
                result = service.sync_all()
                products = result['products']
                customers = result['customers']
            message = '%s\n%s' % (
                OminiFlowSyncService.format_stats(_('Products'), products),
                OminiFlowSyncService.format_stats(_('Customers'), customers),
            )
            failed = products.get('failed', 0) + customers.get('failed', 0)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('OminiFlow sync'),
                'message': message,
                'type': 'success' if not failed else 'warning',
                'sticky': bool(failed),
            },
        }
