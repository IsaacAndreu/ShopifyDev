# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class ShopifyReturnTestWizard(models.TransientModel):
    """Simula una devolució sol·licitada a Shopify a partir d'una comanda
    d'Odoo (per provar a la demo, on no hi ha Shopify)."""
    _name = 'shopify.return.test.wizard'
    _description = 'Crear devolución de prueba'

    config_id = fields.Many2one('shopify.return.config', 'Configuración', required=True)
    remarks = fields.Char('Remarks', required=True, help='p. ej. #347753')
    email = fields.Char(
        'Email del cliente', help='Pon tu email para que ningún cliente real reciba nada.')

    def action_create(self):
        self.ensure_one()
        remarks = self.remarks.strip()
        sale = self.env['sale.order'].search([('ref_remarks', '=', remarks)], limit=1)
        if not sale:
            raise UserError(_('No hay ningún pedido con remarks %s.') % remarks)
        out = sale.picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p.state == 'done')[:1]
        if not out:
            raise UserError(_('El pedido %s no tiene ningún OUT Hecho.') % remarks)

        partner = sale.partner_shipping_id or sale.partner_id
        lines = []
        for m in out.move_lines.filtered(lambda x: x.quantity_done):
            sl = m.sale_line_id
            unit = sl.price_unit if sl else 0.0
            net = (sl.price_reduce_taxinc if sl and 'price_reduce_taxinc' in sl._fields else unit)
            lines.append((0, 0, {
                'sku': m.product_id.default_code or m.product_id.barcode,
                'quantity': m.quantity_done,
                'unit_price': unit,
                'unit_discount': max(unit - net, 0.0) if sl and sl.discount else 0.0,
                'return_reason': 'Prueba',
            }))

        log = self.env['shopify.return.log'].create({
            'config_id': self.config_id.id,
            'shopify_return_id': 'TEST-%s-%s' % (remarks, fields.Datetime.now()),
            'shopify_return_name': '%s-R-TEST' % remarks,
            'remarks': remarks,
            'partner_name': partner.name,
            'email': self.email or partner.email,
            'phone': partner.phone or partner.mobile,
            'street': ' '.join(filter(None, [partner.street, partner.street2])),
            'zip': partner.zip,
            'city': partner.city,
            'country_code': partner.country_id.code,
            'line_ids': lines,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'shopify.return.log',
            'res_id': log.id,
            'view_mode': 'form',
        }
