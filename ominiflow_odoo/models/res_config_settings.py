from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ominiflow_auto_sync = fields.Boolean(
        string='Enable scheduled OminiFlow sync',
        config_parameter='ominiflow_odoo.auto_sync',
        default=True,
        help='When disabled, hourly product and customer crons skip all connections.',
    )
