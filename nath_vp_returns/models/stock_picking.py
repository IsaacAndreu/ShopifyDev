import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_done(self):
        res = super().action_done()
        done = self.filtered(lambda p: p.state == 'done')
        if done:
            returns = self.env['vp.return'].sudo().search([
                ('dev_picking_id', 'in', done.ids), ('state', '!=', 'cancel'), ('received_date', '=', False)])
            for ret in returns:
                # Mai pot bloquejar la validació del magatzem
                try:
                    with self.env.cr.savepoint():
                        ret._on_dev_received()
                except Exception:
                    _logger.exception('Devolución VP %s: recepción', ret.name)
        return res
