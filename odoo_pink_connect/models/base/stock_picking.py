# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import fields, models


_logger = logging.getLogger(__name__)
class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        res = super(StockPicking, self).button_validate()
        for rec in self:
            order_feed = rec.sudo().sale_id.pink_connect_mapping_id.odoo_feed
            
            if order_feed:
                 order_feed.write({'state': 'need_to_send_shipping_data'})

            # MODIFIED BY XAVI BRAVO 2: add same update to sale_order as in Prestashop
            sale_id = rec.sale_id.sudo()
            origin_returned_moves = rec.mapped('move_ids_without_package.origin_returned_move_id')
            if sale_id and sale_id.pink_connect_mapping_id and origin_returned_moves:
                sale_id.update({
                    'auto_invoice_state': 'waiting',
                })
            if sale_id and sale_id.pink_connect_mapping_id:
                sale_id.update({
                    'auto_invoice_state': 'waiting',
                })
        
        return res

    def action_done(self):
        res = super(StockPicking, self).action_done()
        for rec in self:
            order_feed = rec.sudo().sale_id.pink_connect_mapping_id.odoo_feed

            if order_feed:
                order_feed.write({'state': 'need_to_send_shipping_data'})

            # MODIFIED BY XAVI BRAVO 2: add same update to sale_order as in Prestashop
            sale_id = rec.sale_id.sudo()
            origin_returned_moves = rec.mapped('move_ids_without_package.origin_returned_move_id')
            if sale_id and sale_id.pink_connect_mapping_id and origin_returned_moves:
                sale_id.update({
                    'auto_invoice_state': 'waiting',
                })
            if sale_id and sale_id.pink_connect_mapping_id:
                sale_id.update({
                    'auto_invoice_state': 'waiting',
                })

        return res

    # def action_done(self):
    #     res = super(StockPicking, self).action_done()
    #     for rec in self:
    #         sale_id = rec.sale_id.sudo()
    #         origin_returned_moves = rec.mapped('move_ids_without_package.origin_returned_move_id')
    #         if sale_id and sale_id.channel_mapping_ids and origin_returned_moves:
    #             sale_id.update({
    #                 'auto_invoice_state': 'waiting',
    #             })
    #     return res
        
        #TODO
        # below process if be under a cron
        
        #     if order_feed:
        #         url = order_feed.pink_connect_id.url + '/orders/' + order_feed.order_id + '/status/SHIPPED'
        #         api = 'Bearer ' + order_feed.pink_connect_id.api_key
        #         headers = {
        #             'authorization': api,
        #             'accept': "*/*",
        #             'content-type': "application/json",
        #             'cache-control': "no-cache",
        #         }
        #         payload = {"trackingNumber": rec.carrier_tracking_ref
        #                 }

        #         try:
        #             response = requests.request("PUT", url, headers=headers, data=payload)

        #         except ConnectionError as e:
        #             _logger.info('--------------------------------------------')
        #             _logger.info(" Error In Connection. %r  ", str(e))
        #             _logger.info('--------------------------------------------')
        #             return False, str(e)
        #         if response.status_code == 204:
        #             order_feed.write({'state': 'SHIPPED'})


        # return res

    # def action_cancel(self):
    #     res = super(StockPicking, self).action_confirm()
    #     for rec in self:
    #         order_feed = rec.sale_id.pink_connect_mapping_id.odoo_feed
    #         if rec.order_feed:
    #             order_feed.write({'state': 'CANCELLED'})
    #
    #             # url = order_feed.pink_connect_id.url + '/orders/' + order_feed.order_id + '/status/CANCELLED'
    #             # api = 'Bearer' + order_feed.pink_connect_id.api_key
    #             # headers = {
    #             #     'authorization': api,
    #             #     'accept': "*/*",
    #             #     'content-type': "application/json",
    #             #     'cache-control': "no-cache",
    #             # }
    #             #
    #             #
    #             # try:
    #             #     response = requests.request("PUT", url, headers=headers)
    #             #
    #             # except ConnectionError as e:
    #             #     _logger.info('--------------------------------------------')
    #             #     _logger.info(" Error In Connection. %r  ", str(e))
    #             #     _logger.info('--------------------------------------------')
    #             #     return False, str(e)
    #
    #     return res
