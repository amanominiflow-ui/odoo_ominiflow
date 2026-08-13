from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ominiflow_id = fields.Char(
        string='OminiFlow ID',
        index=True,
        copy=False,
        help='Stable WhatsApp contact id from OminiFlow. Used before phone when matching.',
    )
    ominiflow_instance_id = fields.Many2one(
        'ominiflow.instance',
        string='OminiFlow connection',
        ondelete='set null',
        copy=False,
        index=True,
        # WhatsApp contacts often match shared partners (company_id empty).
        # Odoo 19 forbids linking those to a company-specific instance.
        check_company=False,
    )
    ominiflow_last_sync = fields.Datetime(copy=False)
