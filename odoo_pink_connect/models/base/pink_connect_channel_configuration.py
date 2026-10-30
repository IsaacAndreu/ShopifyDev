# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import models, fields, _, api
from odoo.tools import datetime

_logger = logging.getLogger(__name__)


class PinkConnectChannelConfiguration(models.Model):
    _name = 'pink.connect.channel.configuration'
    _description = 'Pink Connect Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = "name"

    name = fields.Char(string='Name')
    code = fields.Char(string="Code")
    # shop_ids = fields.Many2one(comodel_name="pink.connect.shops", inverse_name="shop_id", string="Shop", required=True)
    state = fields.Selection(selection=[('validate', 'Validated'), ('draft', 'Draft')], default='draft')
    image = fields.Image(max_width=256, max_height=256)

    url = fields.Char('Url', required=True)
    api_key = fields.Char("API Key", required=True)
    api_record_limit = fields.Integer(
        string='API Record Limit',
        default=100,
    )
    company_id = fields.Many2one('res.company', required=True, string='Company')

    # category_id = fields.Many2one('res.partner.category', required=True, string='Category')
    country_id = fields.Many2one('res.country', string='Country')

    bb_type = fields.Selection([
        ('regular', 'Regular'),
        ('b2b', 'B2B'),
        ('b2c', 'B2C'),
        ('pos', 'POS')
    ], string="Type", store=True)

    sale_order_type = fields.Many2one(
        'sale.order.type', string='Sale Order Type', required=True)
    brand_id = fields.Many2one('product.brand', 'Product Brand', required=True)

    season_id = fields.Many2one('style.season', 'Season Code', required=True)

    warehouse_id = fields.Many2one(comodel_name='stock.warehouse', string='Warehouse',domain="[('company_id', '=', company_id)]", required=True)

    location_id = fields.Many2many(
        comodel_name='stock.location', string='Stock Location', required=True)

    location_updated = fields.Datetime(string='Location Last Updated')

    impacting_location_ids = fields.Many2many(comodel_name='stock.location', string='Impacting Location',
                                              relation='impacting_location_ids_pink_connect',
                                              domain="[('company_id', '=', company_id)]", )

    delivery_product_id = fields.Many2one(
        comodel_name='product.product', string='Delivery Product',
        domain=[('type', '=', 'service')], required=True
    )

    tax_name = fields.Many2one('account.tax', required=True,domain="[('company_id', '=', company_id)]")
    pricelist_name = fields.Many2one(
        comodel_name='product.pricelist', string='Default Pricelist',
        default=lambda self: self.env['product.pricelist'].search([], limit=1),domain="[('company_id', '=', company_id)]",
        help="""Select the same currency of pricelist used  over e-commerce store/marketplace.""",
    )

    import_order_status = fields.Selection(selection=[
        ('WAITING_ACCEPTANCE', 'Waiting Acceptance'),
        ('WAITING_INFORMATION', 'Waiting Information'),
        ('PENDING', 'pending'),
        ('CANCELLED', 'Cancelled'),
        ('PROCESSING', 'processing'),
        ('SHIPPED', 'shipped'),
        ('NOT_DELIVERED', 'not delivered'),
    ], default='PENDING', string="Import Order Status", required=True
    )
    order_feed = fields.Many2one('pink.connect.order.feed')
    cron_orders_import = fields.Many2one('ir.cron', 'Import Order', compute='compute_cron_jobs')
    # cron_order_accept = fields.Many2one('ir.cron', 'Import Order', compute='compute_cron_jobs')
    cron_orders_evaluate = fields.Many2one('ir.cron', 'Evaluate orders', compute='compute_cron_jobs')
    cron_stock_sync = fields.Many2one('ir.cron', 'Sync Orders', compute='compute_cron_jobs')
    cron_send_shipment = fields.Many2one('ir.cron', 'Send Shipment', compute='compute_cron_jobs')

    sale_journal = fields.Many2one('account.journal','Sale Journal',required=True)

    pink_threshold_qty = fields.Integer('Threshold Quantity',default= 0)

    # MODIFIED BY XAVI BRAVO 2: add auto_invoicing field
    auto_invoicing = fields.Boolean("Auto Invoicing")

    # MODIFIED BY XAVI BRAVO 2: added payment_term_id to view
    payment_term_id = fields.Many2one(
        comodel_name='account.payment.term', string='Default Payment Term',
        domain="[('company_id', '=', company_id)]", required=True
    )

    # MODIFIED BY XAVI BRAVO 2: added payment_mode_id to view
    payment_mode_id = fields.Many2one(
        comodel_name='account.payment.mode', string='Default Payment Mode',
        domain="[('company_id', '=', company_id)]", required=True
    )

    # MODIFIED BY XAVI BRAVO 2: added fiscal_position_id to view
    fiscal_position_id = fields.Many2one(
        comodel_name='account.fiscal.position', string='Default Fiscal Position',
        domain="[('company_id', '=', company_id)]", required=True
    )

    # MODIFIED BY XAVI BRAVO 3: added property_account_receivable_id to view
    property_account_receivable_id = fields.Many2one(
        comodel_name='account.account', string='Default Receivable Account',
        domain="[('company_id', '=', company_id)]", required=True
    )

    def compute_cron_jobs(self):
        self.write({'cron_orders_import': self.env.ref('odoo_pink_connect.cron_pink_connect_import_order').id,
                    'cron_orders_evaluate': self.env.ref('odoo_pink_connect.cron_pink_connect_evaluate_order').id,
                    'cron_stock_sync': self.env.ref('odoo_pink_connect.cron_pink_connect_sync_stock').id,
                    'cron_send_shipment': self.env.ref('odoo_pink_connect.cron_pink_connect_send_shipment').id,
                    # 'cron_order_accept': self.env.ref('odoo_pink_connect.cron_pink_connect_accept_order').id,
                    }
                   )

    def import_orders_cron(self):
        for rec in self.search([('state', '=', 'validate')]):
            rec.import_orders()

    # def accept_orders_cron(self):
    #     for rec in self.search([('state', '=', 'validate')]):
    #         rec.order_accept()
    def evaluate_orders_cron(self):
        for rec in self.search([('state', '=', 'validate')]):
            rec.evaluate_feed()

    def sync_stock_cron(self):
        for rec in self.search([('state', '=', 'validate')]):
            rec.stock_sync()

    def pink_send_shipment_cron(self):
        for rec in self.search([('state', '=', 'validate')]):
            rec.pink_send_shipment()

    def pink_send_shipment(self):
        # MODIFIED BY XAVI BRAVO 7: Mapping for delivery_types to Pink Connect carrier, by default Fedex
        def get_carrier_id(delivery_type):
            return {
                'gls_asm': 17,
                'gls_fr_ns': 17,
                'sending': 24,
                'nacex': 15,
                'correos_express': 8,
                'seur': 2,
                'seur_atlas': 2,
                'mrw': 6,
                'fedex': 5,
            }.get(delivery_type, 5)

        _logger.info(
            '------Pink Connect send shipment -- =============================STARTED =============================--------')
        order_feed = self.env['pink.connect.order.feed'].sudo().search([('state', '=', 'need_to_send_shipping_data')])
        for rec in order_feed:
            _logger.info('--------------------------------------------')
            _logger.info("Pink Connect order  . %r  ", str(rec.order_id))
            _logger.info('--------------------------------------------')
            url = rec.pink_connect_id.url + '/orders/' + rec.order_id + '/status/SHIPPED'
            api_key = 'Bearer ' + rec.pink_connect_id.api_key
            headers = {
                'authorization': api_key,
                'accept': "*/*",
                'content-type': "application/json",
                'cache-control': "no-cache",
            }
            # MODIFIED BY XAVI BRAVO: ONLY OUTGOING OPERATIONS IN LAMBDA
            # MODIFICATION 2: last stock.picking carrier_tracking_ref
            done_pickings = rec.sale_order_id.picking_ids.filtered(lambda l: l.state == 'done' and l.picking_type_id.code == 'outgoing').sorted(key=lambda l: l.id)

            tracking_ref = done_pickings[-1:].carrier_tracking_ref

            if tracking_ref:
                pink_carrier_id = get_carrier_id(done_pickings[-1:].carrier_id.delivery_type)

                payload = {"trackingNumber": tracking_ref, "carrierId": pink_carrier_id}

                try:
                    response = requests.request("PUT", url, headers=headers, data=json.dumps(payload))
                    if response.status_code == 204:
                        rec.write({'state': 'SHIPPED'})
                        # MODIFIED BY XAVI BRAVO 2: order_id change auto_invoice_state to 'waiting' for auto_invoice cron.
                        # rec.sale_order_id.write({'auto_invoice_state': 'waiting'})
                        sale_id = rec.sale_order_id.sudo()
                        if sale_id and sale_id.pink_connect_mapping_id and sale_id.auto_invoice_state == 'deferred':
                            sale_id.write({'auto_invoice_state': 'waiting'})

                except ConnectionError as e:
                    _logger.info('--------------------------------------------')
                    _logger.info(" Error In Connection. %r  ", str(e))
                    _logger.info('--------------------------------------------')
                    return False, str(e)

        _logger.info(
        '------Pink Connect send shipment -- =============================ENDED =============================--------')

    def evaluate_feed(self):
        pending_order_feed_ids = self.env['pink.connect.order.feed'].sudo().search([('state', '=', 'PENDING')])
        _logger.info('------Pink Connect evaluate_feed-- =============================STARTED =============================--------')

        for rec in pending_order_feed_ids[0:self.api_record_limit]:
            _logger.info('--------------------------------------------')
            
            _logger.info(" Pink Connect db ID  . %r  ", str(rec.id))
            _logger.info(" Pink Connect ORDER ID  . %r  ", str(rec.order_id))
            
            _logger.info('--------------------------------------------')

            url = self.url + '/orders/' + rec.order_id + '/status/' + "PROCESSING"

            headers = {
                'authorization': 'Bearer ' + self.api_key,
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
        
        

    def compute_stock_locations(self):
        self.location_updated = datetime.now()
        multi_loc_obj = self.location_id.sudo()
        location_ids = multi_loc_obj.ids + (multi_loc_obj.search([('id', 'child_of', multi_loc_obj.ids)])).filtered(
            lambda x: not (x.scrap_location or x.unavailable_for_reservation or x.deactivated)).ids
        self.impacting_location_ids = [(6, 0, location_ids)]

    @api.onchange('warehouse_id')
    def _onchange_warehouse_id(self):
        if self.warehouse_id:
            location_id = self.env['stock.location'].search(
                [('location_id', '=', self.warehouse_id.view_location_id.id), ('usage', '=', 'internal')])
            location_ids = location_id.mapped(
                'id') + location_id.mapped('child_ids.id')
            return {'domain': {'location_id': [('id', 'in', location_ids)]}}

    def confirm(self):
        self.state = 'validate'

    def set_to_draft(self):
        self.state = 'draft'

    def button_wizard(self):
        return {
            'name': 'Import Wizard',
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'import.operation.order',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_pink_connect': self.id,
            }
        }

    def import_orders(self, filter_by=None, order_ids=None, order_create_date=None, filter_state=None):

        _logger.info("==========================================================> ", )
        _logger.info("======== PinkConnect cron import order started ============================", )
        _logger.info("==========================================================> ", )

        gtins = []
        url = self.url + '/orders'
        # params = None
        # if filter_by:
        #     if filter_by == 'order_id':
        #         url += '/{}'.format(order_ids)
        #
        #     elif filter_by == 'create_date':
        #         url += '?creationDateGTE={}'.format(order_create_date.strftime('%Y-%m-%dT%H:%M:%S'))
        #
        #     if filter_state:
        #         params = {"orderStatusCodes": filter_state,
        #                   "limit": self.api_record_limit
        #                   } if filter_by != 'order_id' else False
        # else:
        params = {"orderStatusCodes": self.import_order_status,
                      "limit": self.api_record_limit
                      }
        headers = {
            'authorization': 'Bearer ' + self.api_key,
            'accept': "*/*",
            'cache-control': "no-cache",
        }
        try:
            response = requests.request("GET", url, headers=headers, params=params)
            json_data1 = json.loads(response.text)
            if type(json_data1) != list:
                json_data1 = [json_data1]
            order_feed = self.env['pink.connect.order.feed'].search_read([], ['order_id'])
            list_order_id = list(map(lambda l: l['order_id'], order_feed))
            orderFeed = []
            for orders in json_data1:
                if str(orders['orderId']) not in list_order_id :
                    orderFeed = self.order_feed.create({
                        "pink_connect_id": self.id,
                        "company_id": self.company_id,
                        "order_id": orders['orderId'],
                        "market_place_name": orders['marketplaceName'],
                        "market_place_code": orders['marketplaceCode'],
                        "market_place_order_code": orders['marketplaceOrderCode'],
                        "shop_channel_id": orders['shopChannelId'],
                        "shop_channel_name": orders['shopChannelName'],
                        "state": orders['status'],
                        "create_order_date": orders['createOrderDate'],
                        "total_price": orders['totalPrice'],
                        "currency": orders['currency'],
                        "shipping_cost": orders['shippingCosts'],
                        "shipping_name": orders['shippingInformation']['name'],
                        "shipping_company": orders['shippingInformation']['company'],
                        "shipping_address": orders['shippingInformation']['address'],
                        "shipping_city": orders['shippingInformation']['city'],
                        "shipping_state": orders['shippingInformation']['state'],
                        "shipping_zip_code": orders['shippingInformation']['zipCode'],
                        "shipping_country": orders['shippingInformation']['country'],
                        "shipping_country_iso_code": orders['shippingInformation']['countryIsoCode'],
                        "shipping_email": orders['shippingInformation']['email'],
                        "shipping_phone": orders['shippingInformation']['phone'],
                        "billing_name": orders['billingInformation']['name'],
                        "billing_company": orders['billingInformation']['company'],
                        "billing_address": orders['billingInformation']['address'],
                        "billing_city": orders['billingInformation']['city'],
                        "billing_state": orders['billingInformation']['state'],
                        "billing_zip_code": orders['billingInformation']['zipCode'],
                        "billing_country": orders['billingInformation']['country'],
                        "billing_country_iso_code": orders['billingInformation']['countryIsoCode'],
                        "billing_email": orders['billingInformation']['email'],
                        "billing_phone": orders['billingInformation']['phone'],
                        "carrier_id": orders['deliveryDetails'][0]['carrierId'] if len(
                            orders['deliveryDetails']) != 0 else False,
                        "carrier_name": orders['deliveryDetails'][0]['carrierName'] if len(
                            orders['deliveryDetails']) != 0 else False,
                        "tracking_number": orders['deliveryDetails'][0]['trackingNumber'] if len(
                            orders['deliveryDetails']) != 0 else False,
                        "tracking_url": orders['deliveryDetails'][0]['trackingUrl'] if len(
                            orders['deliveryDetails']) != 0 else False
                    }, )

                def _get_order_line_vals(lines):
                    return {
                        'order_line_id': lines.get('id', False),
                        'gtin': lines.get('gtin', False),
                        'sku': lines.get('sku', False),
                        'product_name': lines.get('name', False),
                        'price': lines.get('price', False),
                        'tax_rate': lines.get('taxRate', False),
                        'quantity': lines.get('quantity', False),
                        'total_price': lines.get('totalPrice', False),
                        'brand_name': lines.get('brandName', False)
                    }

                order_line_vals = []
                skus = []
                for lines in orders['orderLines']:
                    gtins.append(lines['gtin'])
                    skus.append(lines['sku'])
                    order_line_vals.append((0, 0, _get_order_line_vals(lines)))
                if orderFeed:
                    orderFeed.order_line_ids = order_line_vals

            _logger.info("==========================================================> ", )
            _logger.info("======== PinkConnect orders imported and feed creation complete ============================", )
            _logger.info("==========================================================> ", )

        except ConnectionError as e:
            _logger.info('--------------------------------------------')
            _logger.info(" Error In PinkConnect Connection. %r  ", str(e))
            _logger.info('--------------------------------------------')
            return False, str(e)

        self.env['pink.synchronization'].sudo().create({
            'action_on': 'order',
            'log_id': self.env['ir.sequence'].next_by_code('pink.log') or _('New'),
            'pink_connect_id': self.id,
            'action_type': 'import',
            'status': 'success' if response.status_code == 200 else 'error',
            'summary': response.text
        })

    def stock_sync(self):
        _logger.info(
            '------Pink Connect stock sync  ------------- =============================STARTED =============================--------')
        api_fetch_limit = self.api_record_limit
        url = self.url + '/stock'
        key = self.api_key

        domain = [
            ('pink_connect_channel_mapping', '=', self.id),
            ('sync_with_pink', '=', True),
        ]
        products_to_sync = self.env['product.product'].sudo().search(domain, limit=api_fetch_limit)

        headers = {
            'Authorization': 'Bearer ' + key,
            'Accept': '*/*',
            'Content-Type': 'application/json',
        }
        payload = None
        for rec in products_to_sync:
            stock = max(0, (rec.free_qty_for_reservation - self.pink_threshold_qty))
            payload = [{
                "gtin": rec.barcode, "stock": stock
            }]
        try:
            response = requests.request("POST", url, headers=headers, data=payload)
            self.sync_summary(status='success', response=response.text)
            _logger.info(
                '------Pink Connect Stock Sync File Upload ---------- =============================COMPLETED =============================--------')
        except ConnectionError as e:
            _logger.info('--------------------------------------------')
            _logger.info(" Error In PinkConnect Connection. %r  ", str(e))
            _logger.info('--------------------------------------------')
            return False, str(e)

    def sync_summary(self, status, response):
        self.env['pink.synchronization'].sudo().create({
            'action_on': 'stock',
            'log_id': self.env['ir.sequence'].next_by_code('pink.log') or _('New'),
            'pink_connect_id': self.id,
            'action_type': 'stock',
            'status': status,
            'summary': response
        })

    # def order_accept(self):
    #     # TODO: order accept rework
    #     order_feed_ids = self.env['pink.connect.order.feed'].sudo().search([('state', '=', 'WAITING_ACCEPTANCE')])
    #
    #     for rec in order_feed_ids:
    #         # rec.stock_checking()
    #         # for lines in order_feed_ids.order_line_ids:
    #         #     line_status = True if lines.stock_state == 'available' else False
    #         # if line_status:
    #         url = self.url + '/orders/' + rec.order_id + '/status/' + "PENDING"
    #
    #         headers = {
    #             'authorization': 'Bearer ' + self.api_key,
    #             'accept': "*/*",
    #             'content-type': "application/json",
    #             'cache-control': "no-cache",
    #         }
    #         try:
    #             response = requests.request("PUT", url, headers=headers)
    #             if response.status_code == 204:
    #                 rec.write({'state': "PENDING"})
    #
    #         except ConnectionError as e:
    #             _logger.info('--------------------------------------------')
    #             _logger.info(" Error In PinkConnect Connection. %r  ", str(e))
    #             _logger.info('--------------------------------------------')
    #             return False, str(e)

    # MODIFIED BY XAVI BRAVO 2: auto_invoicing cron func.
    def cron_auto_invoicing(self):
        veepee_instances = self.env['pink.connect.channel.configuration'].search(
            [("state", "=", "validate")]).filtered(lambda x: x.auto_invoicing)

        for config_id in veepee_instances:
            sales_to_process = self.env['sale.order'].search([
                ("auto_invoice_state", "=", "waiting"),
                ("company_id", "=", config_id.company_id.id),
                ("invoice_status", "=", 'to invoice'),
                ('pink_connect_mapping_id.pink_connect_id.id', "=", config_id.id),
                ('pink_connect_mapping_id.pink_connect_id.auto_invoicing', "=", True),
            ]).filtered(lambda x: x.pink_connect_mapping_id != False and x.pink_connect_mapping_id.pink_connect_id.payment_mode_id != False)

            sales_to_process = sales_to_process.filtered(lambda x: x.pink_connect_mapping_id.pink_connect_id.auto_invoicing and x.brand_id)

            for order in sales_to_process:
                invoiceable_lines = order.order_line.filtered(
                    lambda l: l.qty_to_invoice != 0 and l.product_id.type == 'product')

                # _logger.error(f'{invoiceable_lines} - length: {len(invoiceable_lines)}')

                if len(invoiceable_lines) > 0:
                    _logger.info('--------------------------------------------')
                    _logger.info(" PINK CONNECT MAPPING ID: , %r  ", str(order.pink_connect_mapping_id.id))
                    _logger.info('--------------------------------------------')

                    _logger.info('--------------------------------------------')
                    _logger.info(" Saler Order : , %r  ", str(order.id))
                    _logger.info('--------------------------------------------')
                    _logger.info(" Saler Name : , %r  ", str(order.name))
                    _logger.info('--------------------------------------------')

                    payment_modes = order.pink_connect_mapping_id.pink_connect_id.payment_mode_id

                    try:
                        move = order._create_invoices(final=True)
                        move.write(
                            {
                                'journal_id': order.pink_connect_mapping_id.pink_connect_id.sale_journal.id,
                                'presta_transaction_id': order.ref_remarks,
                                'payment_mode_id': order.pink_connect_mapping_id.pink_connect_id.payment_mode_id.id,
                                'invoice_payment_term_id': order.pink_connect_mapping_id.pink_connect_id.payment_term_id.id,
                                # MODIFIED BY XAVI BRAVO 4: change fiscal_position_id after creating invoice.
                                # 'fiscal_position_id': order.pink_connect_mapping_id.pink_connect_id.fiscal_position_id.id,
                                'fiscal_position_id': order.fiscal_position_id.id,
                            }
                        )
                        if move.type == 'out_invoice':
                            move.action_post()
                        _logger.info('--------------------------------------------')
                        _logger.info(
                            "PINK CONNECT Auto Invoice Invoice created, Invoice: {inv_name}, Payment Mode: {pay_mode}, Shop Id: {shop_id}, Shop Name: {shop_name}".format(
                                inv_name=move.name, pay_mode=payment_modes.name, shop_id=config_id.id,
                                shop_name=config_id.name))
                        _logger.info('--------------------------------------------')
                        if order.invoice_status == 'invoiced':
                            order.write({
                                'auto_invoice_state': 'accounted'
                            })
                            _logger.info(" Accounted Order: , %r  ", str(order.name))
                    except Exception as e:
                        _logger.info('--------------------------------------------')
                        _logger.info("PINK CONNECT Auto Invoice Exception {msg}".format(msg=e))
                        _logger.info('--------------------------------------------')

