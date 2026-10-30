# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.http import request


class PinkConnectOrderMapping(models.Model):
    _name = 'pink.connect.order.mapping'
    _description = 'Pink Connect Order Mapping'

    pink_connect_id = fields.Many2one('pink.connect.channel.configuration', string='')
    company_id = fields.Many2one('res.company', string='Company Id')

    _rec_name = "store_order_id"

    odoo_feed = fields.Many2one('pink.connect.order.feed', 'Order Feed', )

    store_order_id = fields.Char('Pink Connect Order ID', related='odoo_feed.order_id')

    sale_order = fields.Many2one('sale.order', 'Odoo Order')
    partner_id = fields.Many2one(comodel_name='res.partner',string="Partner")
    
    #TODO
    # add brand 
    
    def get_so_order_lines(self):
        order_line_vals = []

        # MODIFIED BY XAVI BRAVO 4: taxes differ by country_id
        # tax = self.pink_connect_id.tax_name
        if self.odoo_feed.market_place_name == 'Veepee France':
            tax = self.env['account.tax'].search([
                ('name','=', 'IVA FRANCIA 20% - OSS'),
                ('company_id', '=', self.pink_connect_id.company_id.id),
                # ('oss_country_id', '=', self.partner_id.country_id.id)
            ])
        elif self.odoo_feed.market_place_name == 'Veepee Italy':
            tax = self.env['account.tax'].search([
                ('name','=', 'IVA ITALIA 22% - OSS'),
                ('company_id', '=', self.pink_connect_id.company_id.id),
                # ('oss_country_id', '=', self.partner_id.country_id.id)
            ])
        else:
            tax = self.pink_connect_id.tax_name

        for lines in self.odoo_feed.order_line_ids:
            # MODIFIED BY XAVI BRAVO: request.env => self.env
            product = self.env['product.product'].sudo().search([('barcode', '=', lines.gtin)])
            if product:
                product.sync_with_pink = True
                product.pink_connect_channel_mapping = self.pink_connect_id.id
            else:
                self.odoo_feed.state = 'EXCEPTION'
                self.odoo_feed.log_message = '<br/>%s' % 'Product Not Found In System , BarCode ' + str(lines.gtin)
                return False
            
            if tax.price_include:
                tax_exclusive_price = float(lines.price)
            else:
                tax_exclusive_price = round((float(lines.price)*100) / (tax.amount+100), 2)

            order_line_vals.append((0, 0, {
                'product_id': product.id,
                'price_unit': tax_exclusive_price,
                'name': lines.product_name,
                # 'brand_id': lines.brand_name,
                'product_uom_qty': lines.quantity,
                'tax_id': [(6, 0, [tax.id])]
            }))
        #for delivery product
        if tax.price_include:
            shipping_cost = float(self.odoo_feed.shipping_cost)
        else:
            shipping_cost = round((float(self.odoo_feed.shipping_cost)*100) / (tax.amount+100), 2)

        order_line_vals.append((0, 0, {
            'product_id': self.pink_connect_id.delivery_product_id.id,
            'price_unit': shipping_cost,
            'name': self.pink_connect_id.delivery_product_id.name,
            'product_uom_qty': 1,
            'tax_id': [(6, 0, [tax.id])]
        }))

        return order_line_vals

    def get_partner_create_vals(self,odoo_feed,pink_connect_id):
        p_type = 'contact'
        name = odoo_feed.shipping_name

        phone = odoo_feed.shipping_phone
        country = self.env['res.country'].sudo().search([('code','=',odoo_feed.shipping_country_iso_code)])
        state = self.env['res.country.state'].sudo().search([('name','=',odoo_feed.shipping_state)])

        vals = dict(
            type=p_type,
            country_id=country.id or False,
            # category_id=[(6, 0, pink_connect_id.category_id.ids)],
            bb_type=pink_connect_id.bb_type,
            name=name,
            email=odoo_feed.shipping_email or False,
            phone=phone,
            street=odoo_feed.shipping_address,
            state_id = state.id or False,
            city=odoo_feed.shipping_city,
            zip=odoo_feed.shipping_zip_code,
            lang='es_ES',
            ac_journal_id_sale = pink_connect_id.sale_journal.id,
            # subchannels = 'marketplace'
            # MODIFIED BY XAVI BRAVO
            x_studio_canal_de_venta='Online',
            x_studio_subcanal='Veepe',
            sii_simplified_invoice=True,
            aeat_anonymous_cash_customer=True,
            # property_account_position_id=pink_connect_id.fiscal_position_id.id,
            mobile=phone,
            company_id=self.company_id.id,
            # MODIFIED BY XAVI BRAVO: account 4300010000
            property_account_receivable_id = pink_connect_id.property_account_receivable_id.id,
        )
        return vals

    def create_so(self):

        shipping_name = self.odoo_feed.shipping_name
        shipping_phone = self.odoo_feed.shipping_phone
        shipping_address = self.odoo_feed.shipping_address
        shipping_state = self.odoo_feed.shipping_state

        # match_name = self.env['res.partner'].search_read([('name', '=', shipping_name)])
        # match_address = self.env['res.partner'].search_read([('phone','=',shipping_phone),('street','=',shipping_address)])
        # if match_name:
        #     if match_address:
        #         partner = match_address[0]['id']
        #     else:
        #         val = self.get_partner_create_vals(self.odoo_feed,self.pink_connect_id)
        #         val['parent_id'] = match_name[0]['id']
        #         val['type'] = 'delivery'
        #         partner = self.env['res.partner'].create(val).id
        # else:
        #     partner = self.env['res.partner'].sudo().create(self.get_partner_create_vals(self.odoo_feed,self.pink_connect_id)).id

        partner = self.env['res.partner'].sudo().create(self.get_partner_create_vals(self.odoo_feed,self.pink_connect_id))
        
        if partner:
            # MODIFIED BY XAVI BRAVO 4: add fiscal_position to partner depending on country_id
            # if partner.country_id.code == 'FR':
            #     fiscal_position = self.env['account.fiscal.position'].search([
            #         ('country_id', '=', partner.country_id.id),
            #         ('name', '=', 'FRANCIA - OSS'),
            #         ('company_id', '=', self.company_id.id)
            #     ])

            #     partner.with_context(force_company=self.company_id.id).write({
            #         'property_account_position_id': fiscal_position.id,
            #     })

            #     fiscal_pisition_id = fiscal_position.id
            # elif partner.country_id.code == 'IT':
            #     fiscal_position = self.env['account.fiscal.position'].search([
            #         ('country_id', '=', partner.country_id.id),
            #         ('name', '=', 'ITALIA - OSS'),
            #         ('company_id', '=', self.company_id.id)
            #     ])

            #     partner.with_context(force_company=self.company_id.id).write({
            #         'property_account_position_id': fiscal_position.id,
            #     })

            #     fiscal_pisition_id = fiscal_position.id
            # else:
            #     partner.with_context(force_company=self.company_id.id).write({
            #         'property_account_position_id': self.pink_connect_id.fiscal_position_id.id,
            #     })

            #     fiscal_pisition_id = self.pink_connect_id.fiscal_position_id.id

            # partner.with_context(force_company=self.company_id.id).write({
            #     'property_account_receivable_id': self.pink_connect_id.property_account_receivable_id.id,
            # })
            country_fiscal_positions = {
                'FR': 'FRANCIA - OSS',
                'IT': 'ITALIA - OSS'
            }

            country_code = partner.country_id.code
            fiscal_position = None

            if country_code in country_fiscal_positions:
                fiscal_position = self.env['account.fiscal.position'].search([
                    ('country_id', '=', partner.country_id.id),
                    ('name', '=', country_fiscal_positions[country_code]),
                    ('company_id', '=', self.company_id.id)
                ])
            else:
                fiscal_position = self.pink_connect_id.fiscal_position_id

            partner.with_context(force_company=self.company_id.id).write({
                'property_account_position_id': fiscal_position.id,
                'property_account_receivable_id': self.pink_connect_id.property_account_receivable_id.id,
            })

            data = self.get_so_create_dic()
            if data:
                data['partner_id'] = partner.id
                sale_id = self.env['sale.order'].create(data)
                if sale_id:
                    # MODIFIED BY XAVI BRAVO 4: change fiscal_position_id after creating SO.
                    # sale_id.write({'pink_connect_mapping_id': self.id})
                    # sale_id.write({'pink_connect_mapping_id': self.id, 'fiscal_position_id': fiscal_pisition_id})
                    sale_id.write({'pink_connect_mapping_id': self.id, 'fiscal_position_id': fiscal_position.id})
                    self.write({'sale_order': sale_id.id,
                                'partner_id': partner.id}
                            )
                    return sale_id
        return False

    def get_so_create_dic(self):
        order_lines = self.get_so_order_lines()
        configuration = self.pink_connect_id
        order_feed = self.odoo_feed
        return {
            's_order_type_id': configuration.sale_order_type.id,
            'company_id': self.company_id.id,
            'date_order': order_feed.create_order_date,
            'name': order_feed.env['ir.sequence'].next_by_code('pink.order') or False,
            'order_line': order_lines,
            'ref_remarks': order_feed.market_place_order_code,
            # MODIFIED BY XAVI BRAVO
            'presta_transaction_id': order_feed.market_place_order_code,
            'pricelist_id': configuration.pricelist_name.id,
            'season_id': configuration.season_id.id,
            'brand_id': configuration.brand_id.id,
            'warehouse_id': configuration.warehouse_id.id,
            # MODIFIED BY XAVI BRAVO 2: add from channel config
            'payment_term_id': configuration.payment_term_id.id,
            'payment_mode_id': configuration.payment_mode_id.id,
            # 'fiscal_position_id': configuration.fiscal_position_id.id,
        } if order_lines else False


