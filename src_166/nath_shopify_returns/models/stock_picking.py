# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    return_incident_note = fields.Text(
        'Nota de incidencia (devolución)',
        help='El departamento de devoluciones puede escribir qué ha pasado (artículo dañado, '
             'no es el que tocaba...). Sale en la ficha de la devolución Shopify.')

    # Odoo 13: el botó Validar acaba cridant action_done() del picking
    # (el mètode _action_done del picking no existeix fins a Odoo 14).
    def action_done(self):
        res = super().action_done()
        logs = self.env['shopify.return.log'].search([
            ('dev_picking_id', 'in', self.ids), ('state', '=', 'done')])
        for log in logs:
            # Mai pot bloquejar la validació del magatzem: si falla, queda marcat a la devolució
            try:
                with self.env.cr.savepoint():
                    log._on_dev_received()
            except Exception as e:
                _logger.exception('Recepción devolución %s', log.remarks)
                log.write({'state': 'received', 'issue': 'error',
                           'error_msg': 'Error al registrar la recepción: %s' % e})
        return res

    def to_export_format_multi(self, integration):
        # Shopify no coneix Nacex: si no li enviem la URL, el seguiment surt sense enllaç.
        # Es busca pel número de seguiment perquè el squash() del connector el pot moure d'albarà.
        tracking_data = super().to_export_format_multi(integration)
        urls = {
            p.carrier_tracking_ref: p.carrier_tracking_url
            for p in self
            if p.carrier_id.delivery_type == 'nacex'
            and p.carrier_tracking_ref and p.carrier_tracking_url
        }
        for data in tracking_data:
            if data.get('tracking') in urls:
                data['url'] = urls[data['tracking']]
        return tracking_data
