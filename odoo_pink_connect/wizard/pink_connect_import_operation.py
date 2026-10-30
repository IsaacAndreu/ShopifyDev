# -*- coding: utf-8 -*-
import json

from odoo import fields,models,exceptions



class ImportOperation(models.TransientModel):
	_name  = 'import.operation.order'
	_description = 'Import Operation'


	object = fields.Selection(selection=[
		('sale.order', 'Order'),
	],default = 'sale.order')

	operation = fields.Selection(
		selection = [
			('import',"Import"),
			('update','Update')
		],
		default ='import',
		required = True
	)
	order_ids = fields.Char('Order Id',copy=False)
	order_create_date = fields.Datetime("Creation Date",copy=False)
	pink_connect = fields.Many2one('pink.connect.channel.configuration')
	filter_by = fields.Selection(
		selection=[
			('all','All'),
			('order_id','Order ID(s)'),
			('create_date', 'Creation Date')
		],
		required = True
	)
	filter_state = fields.Selection(
		selection=[
		('WAITING_ACCEPTANCE', 'Waiting Acceptance'),
		('WAITING_INFORMATION', 'Waiting Information'),
		('PENDING', 'pending'),
		('CANCELLED', 'Cancelled'),
		('PROCESSING', 'processing'),
		('SHIPPED', 'shipped'),
		('NOT_DELIVERED', 'not delivered'),
		]
	)

	def import_button(self):
		return self.pink_connect.import_orders(filter_by=self.filter_by,order_ids=self.order_ids,order_create_date=self.order_create_date,filter_state=self.filter_state)