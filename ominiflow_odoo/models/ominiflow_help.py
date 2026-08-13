from odoo import fields, models, _


class OminiFlowHelp(models.TransientModel):
    _name = 'ominiflow.help'
    _description = 'OminiFlow Unsupported Resource Help'

    title = fields.Char(readonly=True)
    message = fields.Html(readonly=True)

    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        topic = self.env.context.get('ominiflow_help_topic', 'orders')
        if topic == 'inventory':
            values['title'] = _('Inventory sync is not available')
            values['message'] = _(
                '<p>OminiFlow does not publish a warehouse inventory API '
                '(no location, movement type, or stock.quant contract).</p>'
                '<p>Catalog quantity is the product field <code>stock_quantity</code> '
                'and is stored on the Odoo product as <strong>OminiFlow stock quantity</strong> '
                'during product sync. Odoo warehouse quantities are not changed.</p>'
            )
        else:
            values['title'] = _('Order sync is not available')
            values['message'] = _(
                '<p>OminiFlow ecommerce orders exist in the PHP web UI only. '
                'There is no public REST endpoint such as '
                '<code>GET /api/wpbox/ecommerce/orders</code>.</p>'
                '<p>This connector will not create Odoo sales orders until that API exists.</p>'
            )
        return values
