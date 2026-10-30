# -*- coding: utf-8 -*-

from odoo import api, fields, models


class PinkSynchronization(models.Model):
    _name = 'pink.synchronization'
    _description = 'Synchronization History'
    _rec_name = 'action_on'
    _order = "id desc"

    log_id= fields.Char(string='')

    pink_connect_id = fields.Many2one('pink.connect.channel.configuration', string='')

    summary = fields.Text('Summary', required=True)
    status = fields.Selection(
        selection=[
            ('success', 'Success'),
            ('error', 'Error')
        ],
        string='Status',
        required=True
    )

    action_on = fields.Selection(
        selection=[
            ('order', 'Order'),
            ('customer', 'Customer'),
            ('shipping', 'Shipping'),
            ('stock', 'Stock'),

        ],
        string='Action On',
        required=True
    )

    action_type = fields.Selection(
        selection=[
            ('import', 'Import Orders'),
            ('accept', 'Accept Orders'),
            ('send_shipment_status', 'Status Shipped Sent'),
            ('stock', 'Stock Sync'),
        ],
        string='Action Type'
    )