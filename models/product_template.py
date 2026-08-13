from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    ominiflow_id = fields.Char(
        string='OminiFlow ID',
        index=True,
        copy=False,
        help='Stable catalog id from OminiFlow. Used before SKU when matching.',
    )
    ominiflow_instance_id = fields.Many2one(
        'ominiflow.instance',
        string='OminiFlow connection',
        ondelete='set null',
        copy=False,
        index=True,
        check_company=True,
    )
    ominiflow_last_sync = fields.Datetime(copy=False)
    ominiflow_stock_quantity = fields.Float(
        string='OminiFlow stock quantity',
        copy=False,
        help='Catalog stock_quantity from OminiFlow. Not an Odoo warehouse quantity.',
    )
