# -*- coding: utf-8 -*-


from odoo import fields,models


class ResPartner(models.Model):
	_inherit = 'res.partner'

	pink_connect_customer_id = fields.Char('PinkConnect Customer Id')