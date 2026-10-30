# -*- coding: utf-8 -*-


from odoo import models, fields, _
import time

import requests
import io
from requests.exceptions import ConnectionError
import logging
from datetime import datetime, timedelta
import requests
import json

_logger = logging.getLogger(__name__)


class OrderFeed(models.Model):
    _name = 'pink.connect.order.feed'
    _rec_name = "order_id"
    _order = 'id desc'

    order_id = fields.Char('Order Id')
    order_count = fields.Char(string='Order Lines')
    customer_id = fields.Char('Store Customer ID')
    state = fields.Selection([
        ('WAITING_ACCEPTANCE', 'Waiting Acceptance'),
        ('WAITING_INFORMATION', 'Waiting Information'),
        ('PENDING', 'pending'),#import orders from pink in this state
        ('CANCELLED', 'Cancelled'),
        ('PROCESSING', 'processing'),#sale order created in erp 
        ('EXCEPTION', 'exception'),
        ('need_to_send_shipping_data', 'Need to Send Tracking Info'),        
        ('SHIPPED', 'Shipping/Tracking info Sent'),
        ('NOT_DELIVERED', 'not delivered'),

    ], default='PENDING', string='Status')

    market_place_name = fields.Char("Market Place Name")
    market_place_code = fields.Char("Market Place Code")
    market_place_order_code = fields.Char("Market Place Order Code")
    shop_channel_id = fields.Char("Shop Channel Id")
    shop_channel_name = fields.Char("Shop Channel Name")
    create_order_date = fields.Datetime("Order Creation Date")
    total_price = fields.Char("Total Price")
    currency = fields.Char("Currency")
    pink_connect_id = fields.Many2one('pink.connect.channel.configuration', string='Pink Connect')
    company_id = fields.Many2one('res.company',string='company', related='pink_connect_id.company_id')
    order_mapping_id = fields.Many2one('pink.connect.order.mapping', string='Order Map')
    sale_order_id = fields.Many2one('sale.order',string='Sale Order')
    shipping_cost = fields.Char("Shipping Cost")
    # shipping
    shipping_name = fields.Char(string='Shipping Name')
    shipping_company = fields.Char(string='Shipping Company')
    shipping_email = fields.Char(string='Shipping Email')
    shipping_phone = fields.Char(string='Shipping Phone')
    shipping_address = fields.Char(string='Shipping Address')
    shipping_city = fields.Char(string='Shipping City')
    shipping_zip_code = fields.Char(string='Shipping Zip')
    shipping_state = fields.Char(string='Shipping State')
    shipping_country = fields.Char(string='Shipping Country')
    shipping_country_iso_code = fields.Char(string='Shipping Country Iso Code')

    # billing
    billing_name = fields.Char(string='Billing Name')
    billing_company = fields.Char(string='Billing Company')
    billing_email = fields.Char(string='Billing Email')
    billing_phone = fields.Char(string='Billing Phone')
    billing_address = fields.Char(string='Billing Address')
    billing_city = fields.Char(string='Billing City')
    billing_zip_code = fields.Char(string='Billing Zip')
    billing_state = fields.Char(string='Billing State')
    billing_country = fields.Char(string='Billing Country')
    billing_country_iso_code = fields.Char(string='Billing Country Iso Code')

    #delivery
    carrier_id = fields.Char("Carrier Id")
    carrier_name = fields.Char("Carrier Name")
    tracking_number = fields.Char("Tracking Number")
    tracking_url = fields.Char("Tracking Url")

    order_line_ids = fields.One2many(
        'pink.connect.order.line', 'order_feed_id', string='Line Ids', ondelete='cascade')

    _sql_constraints = [
        ('order_id_unique', 'UNIQUE(order_id)', 'Order feed should have unique orders')
    ]

    log_message = fields.Html('Message')
    def create_order_mappings(self):
        for rec in self:
            vals = {
                'odoo_feed': rec.id,
                'company_id': rec.company_id.id,
                'pink_connect_id': rec.pink_connect_id.id,
            }
            if rec.state == 'PROCESSING':
                order_mapping = rec.order_mapping_id.create(vals)
                rec.write({'order_mapping_id': order_mapping.id})
                so = order_mapping.create_so()
                if so:
                    rec.write({'sale_order_id': so.id})
                    so.action_confirm()
                    for picking in so.picking_ids:
                        if picking.state == 'draft':
                            picking.action_confirm()
                        # if picking.state != 'assigned':
                        #     picking.action_assign()
                        #
                else:
                    rec.log_message += '<br/>%s' % 'Sale Order not Created due to exceptions'


    def evaluate_order_feed(self):
        for rec in self:
            if rec.state == 'PENDING':
                _logger.info('------Pink Connect evaluate_feed-- =============================STARTED =============================--------')
                _logger.info('--------------------------------------------')
                _logger.info(" Pink Connect db ID  . %r  ", str(rec.id))
                _logger.info(" Pink Connect ORDER ID  . %r  ", str(rec.order_id))
                _logger.info('--------------------------------------------')

                url = rec.pink_connect_id.url + '/orders/' + rec.order_id + '/status/' + "PROCESSING"

                headers = {
                    'authorization': 'Bearer ' + rec.pink_connect_id.api_key,
                    'accept': "*/*",
                    'content-type': "application/json",
                    'cache-control': "no-cache",
                }
                try:
                    response = requests.request("PUT", url, headers=headers)

                except ConnectionError as e:
                    _logger.info('--------------------------------------------')
                    _logger.info(" Error In Connection. %r  ", str(e))
                    _logger.info('--------------------------------------------')
                    return False, str(e)
                if response.status_code == 204:
                    rec.write({'state': 'PROCESSING'})
                    rec.create_order_mappings()

                _logger.info('------Pink Connect evaluate_feed--============================== ENDED =============================--------')

class OrderLineFeed(models.Model):
    _name = 'pink.connect.order.line'
    _description = 'Order Line'

    product_id = fields.Many2one('product.product', 'Product')

    order_feed_id = fields.Many2one(
        'pink.connect.order.feed', 'Order Feed ID', store=True)

    last_updated_date = fields.Datetime(string='Last Updated')
    process_state = fields.Selection([
        ('draft', 'Draft'),
        ('not_found', 'Missing Barcode in Inventory'),
        ('ready', 'Stock Checked'),
        ('accepted', 'Requested Accept'),
        ('rejected', 'Requested Reject'),

    ], default='draft', string='Process')

    stock_state = fields.Selection([
        ('draft', 'Not Processed'),
        ('available', 'In Stock'),
        ('not_available', 'Not Available'),
    ], default='draft', string='Stock')

    order_line_id = fields.Char(string='')
    gtin = fields.Char('Gtin')
    sku = fields.Char('Sku')
    price = fields.Char(string='Price')
    product_name = fields.Char('Product Name')
    tax_rate = fields.Char('Tax Rate')
    quantity = fields.Integer('Quantity')
    brand_name = fields.Char('Brand Name')
    total_price = fields.Char('Total Price')


    company_id = fields.Many2one(related='order_feed_id.company_id', string='Company')
