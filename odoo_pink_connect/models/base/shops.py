# -*- coding: utf-8 -*-

from odoo import models,fields

class PinkConnectShops(models.Model):
    _name = 'pink.connect.shops'
    _description = 'Pink Connect Shops'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(required=True)
    default_partner = fields.Many2one('res.partner')
    country = fields.Many2one('res.country')
    shop_id = fields.Char()
    code = fields.Char()
    url = fields.Char()
    is_active = fields.Boolean()
    store_tax = fields.Many2one('account.tax',required=True)
    pricelist_name = fields.Many2one(
        comodel_name='product.pricelist', string='Default Pricelist',
        default=lambda self: self.env['product.pricelist'].search([], limit=1),
        help="""Select the same currency of pricelist used  over e-commerce store/marketplace.""",
    )