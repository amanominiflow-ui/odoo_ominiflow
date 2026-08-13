from odoo import api, fields, models


class OminiFlowSyncLog(models.Model):
    _name = 'ominiflow.sync.log'
    _description = 'OminiFlow Sync Log'
    _order = 'started_at desc, id desc'
    _check_company_auto = True

    instance_id = fields.Many2one(
        'ominiflow.instance',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        related='instance_id.company_id',
        store=True,
        index=True,
    )
    resource_type = fields.Selection(
        [
            ('product', 'Products'),
            ('customer', 'Customers'),
            ('order', 'Orders'),
            ('inventory', 'Inventory'),
            ('connection', 'Connection'),
            ('webhook', 'Webhook'),
        ],
        required=True,
        index=True,
    )
    operation = fields.Char(required=True)
    direction = fields.Selection(
        [
            ('from_ominiflow', 'OminiFlow → Odoo'),
            ('to_ominiflow', 'Odoo → OminiFlow'),
            ('inbound', 'Inbound webhook'),
        ],
        required=True,
        default='from_ominiflow',
    )
    external_id = fields.Char(index=True)
    odoo_model = fields.Char()
    odoo_record_id = fields.Integer()
    status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('success', 'Success'),
            ('failed', 'Failed'),
        ],
        default='pending',
        required=True,
        index=True,
    )
    message = fields.Text()
    error = fields.Text()
    started_at = fields.Datetime(default=fields.Datetime.now, index=True)
    finished_at = fields.Datetime()

    @api.model
    def create_log(self, instance, **values):
        vals = {
            'instance_id': instance.id,
            'status': values.pop('status', 'running'),
            'started_at': fields.Datetime.now(),
        }
        vals.update(values)
        return self.create(vals)

    def finish(self, status, message=None, error=None, odoo_model=None, odoo_record_id=None):
        self.write({
            'status': status,
            'message': message or False,
            'error': error or False,
            'odoo_model': odoo_model or self.odoo_model,
            'odoo_record_id': odoo_record_id or self.odoo_record_id,
            'finished_at': fields.Datetime.now(),
        })
        return self
