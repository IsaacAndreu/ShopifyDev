# -*- coding: utf-8 -*-
import logging

import requests

from odoo import fields, models
_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    pink_connect_mapping_id = fields.Many2one(comodel_name='pink.connect.order.mapping', copy=False, string='Mapping Id')

    # def action_confirm(self):
    #     res = super(SaleOrder, self).action_confirm()
    #
    #     for rec in self:
    #         pink_connect = rec.pink_connect_mapping_id.pink_connect_id
    #         if rec.pink_connect_mapping_id:
    #             order_feed = rec.pink_connect_mapping_id.odoo_feed
    #             url = pink_connect.url + '/orders/' + order_feed.order_id + '/status/' + "PROCESSING"
    #
    #             headers = {
    #                 'authorization': 'Bearer ' + pink_connect.api_key,
    #                 'accept': "*/*",
    #                 'content-type': "application/json",
    #                 'cache-control': "no-cache",
    #             }
    #             try:
    #                 response = requests.request("PUT", url, headers=headers)
    #
    #             except ConnectionError as e:
    #                 _logger.info('--------------------------------------------')
    #                 _logger.info(" Error In Connection. %r  ", str(e))
    #                 _logger.info('--------------------------------------------')
    #                 return False, str(e)
    #             if response.status_code == 204:
    #                 order_feed.write({'state': 'PROCESSING'})
    #
    #     return res

    # def action_cancel(self):
    #     res = super(SaleOrder, self).action_cancel()
    #     for rec in self:
    #         if rec.pink_connect_mapping_id:
    #             rec.pink_connect_mapping_id.odoo_feed.write({'state': 'NOT_DELIVERED'})
    #
    #     return res
