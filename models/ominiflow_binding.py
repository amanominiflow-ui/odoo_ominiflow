from odoo import api, fields, models


class OminiFlowBinding(models.Model):
    _name = 'ominiflow.binding'
    _description = 'OminiFlow External ID Binding'
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
            ('product', 'Product'),
            ('customer', 'Customer'),
            ('webhook_event', 'Webhook event'),
        ],
        required=True,
        index=True,
    )
    external_id = fields.Char(required=True, index=True)
    odoo_model = fields.Char(required=True)
    odoo_res_id = fields.Integer(required=True, index=True)
    last_sync = fields.Datetime(default=fields.Datetime.now)

    _uniq_external = models.Constraint(
        'unique(instance_id, resource_type, external_id)',
        'This OminiFlow record is already linked.',
    )
    _uniq_odoo = models.Constraint(
        'unique(instance_id, odoo_model, odoo_res_id)',
        'This Odoo record is already linked to OminiFlow.',
    )

    @api.model
    def upsert(self, instance, resource_type, external_id, odoo_model, odoo_res_id):
        if not external_id or not odoo_res_id:
            return self.browse()
        domain = [
            ('instance_id', '=', instance.id),
            ('resource_type', '=', resource_type),
            ('external_id', '=', str(external_id)),
        ]
        binding = self.search(domain, limit=1)
        values = {
            'instance_id': instance.id,
            'resource_type': resource_type,
            'external_id': str(external_id),
            'odoo_model': odoo_model,
            'odoo_res_id': odoo_res_id,
            'last_sync': fields.Datetime.now(),
        }
        if binding:
            binding.write(values)
            return binding
        existing_odoo = self.search([
            ('instance_id', '=', instance.id),
            ('odoo_model', '=', odoo_model),
            ('odoo_res_id', '=', odoo_res_id),
        ], limit=1)
        if existing_odoo:
            existing_odoo.write(values)
            return existing_odoo
        return self.create(values)
