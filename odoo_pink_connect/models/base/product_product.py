# -*- coding: utf-8 -*-

from odoo import api,fields,models


class ProductProduct(models.Model):
    _inherit = 'product.product'


    pink_connect_channel_mapping = fields.Many2one(
        string='Pink Connect Channel Mapping',
        comodel_name='pink.connect.channel.configuration',
        copy=False
    )

    sync_with_pink = fields.Boolean(string='Sync with PinkConnect', default=False, store=True)
    pink_connect_sku = fields.Char(string='PinkConnect sku', store=True)


