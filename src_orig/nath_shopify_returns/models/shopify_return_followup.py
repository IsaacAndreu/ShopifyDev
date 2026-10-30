# -*- coding: utf-8 -*-
"""Seguiment de les devolucions un cop aprovades:
- estat de l'enviament (Nacex / FedEx),
- paquets que no arriben (retard),
- devolucions cancel·lades pel client a Shopify,
- tancar la devolució a Shopify quan la Lorena la tanca a mà,
- resum diari per email.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.tools import html_escape

from .shopify_return_log import RETURN_CLOSE_MUTATION

_logger = logging.getLogger(__name__)

RETURN_STATUS_QUERY = """
{
  nodes(ids: [%(ids)s]) {
    ... on Return { id status }
  }
}
"""

WAITING_STATES = ('dev_created', 'nacex_ok', 'done')


class ShopifyReturnConfig(models.Model):
    _inherit = 'shopify.return.config'

    overdue_days = fields.Integer(
        'Días para considerar el paquete retrasado', default=15,
        help='Si pasados estos días desde la aprobación no ha llegado el paquete, '
             'la devolución se marca como retrasada y sale en el resumen diario.')
    check_tracking = fields.Boolean(
        'Consultar el estado del envío', default=True,
        help='El cron pregunta a Nacex / FedEx en qué estado está cada devolución pendiente de llegar.')
    sync_shopify_cancel = fields.Boolean(
        'Cancelar si el cliente la cancela en Shopify', default=True,
        help='Si la devolución se cancela o rechaza en Shopify antes de llegar, se anula la recogida '
             'y se cancela la TT/DEV.')
    summary_partner_ids = fields.Many2many(
        'res.partner', 'shopify_return_config_summary_rel', 'config_id', 'partner_id',
        string='Resumen diario a',
        help='Cada mañana se envía un email con lo pendiente de revisar, lo recibido por aceptar, '
             'los errores y los paquetes retrasados. Vacío: no se envía.')


class ShopifyReturnLog(models.Model):
    _inherit = 'shopify.return.log'

    carrier_status = fields.Char('Estado del envío', readonly=True, copy=False)
    carrier_status_date = fields.Datetime('Estado consultado el', readonly=True, copy=False)
    carrier_delivered = fields.Boolean('Entregado por el transportista', readonly=True, copy=False)
    overdue = fields.Boolean('Retrasada', readonly=True, copy=False, index=True)

    # ------------------------------------------------------------------
    # Estat de l'enviament
    # ------------------------------------------------------------------
    def action_update_tracking(self):
        self._update_tracking()
        return True

    def _tracking_ref(self):
        """Referència per consultar: Nacex = codi d'expedició, FedEx = tracking."""
        if self.return_carrier == 'fedex':
            return self.nacex_albaran
        return self.nacex_cod_exp

    def _update_tracking(self):
        """:return: False si alguna consulta ha fallat."""
        all_ok = True
        for log in self:
            ref = log._tracking_ref()
            config = log.config_id
            simulated = config.simulate_fedex if log.return_carrier == 'fedex' else config.simulate_nacex
            if not ref or (ref or '').startswith('TEST') or simulated:
                continue
            carrier = config.fedex_carrier_id if log.return_carrier == 'fedex' else config.carrier_id
            try:
                if log.return_carrier == 'fedex':
                    status, delivered = carrier.fedex_get_status(ref)
                else:
                    status, delivered = carrier.nacex_get_status(ref)
            except Exception as e:
                _logger.info('Estado envío %s: %s', log.remarks, e)
                log.carrier_status_date = fields.Datetime.now()   # no reintentar fins d'aquí 3 h
                all_ok = False
                continue
            vals = {'carrier_status_date': fields.Datetime.now(), 'carrier_delivered': delivered}
            if status and status != log.carrier_status:
                vals['carrier_status'] = status
                log.message_post(body=_('Estado del envío: %s') % html_escape(status))
            log.write(vals)
        return all_ok

    # ------------------------------------------------------------------
    # Retards
    # ------------------------------------------------------------------
    @api.model
    def _update_overdue(self, config):
        limit = fields.Datetime.now() - timedelta(days=max(config.overdue_days, 0))
        waiting = self.search([('config_id', '=', config.id), ('state', '=', 'done')])
        late = waiting.filtered(lambda l: l.approved_date and l.approved_date < limit)
        (waiting - late).filtered('overdue').write({'overdue': False})
        for log in late.filtered(lambda l: not l.overdue):
            log.overdue = True
            log.message_post(body=_('Han pasado %s desde la aprobación y el paquete no ha llegado.')
                             % self._days(log.days_waiting))
        self.search([('config_id', '=', config.id), ('state', '!=', 'done'), ('overdue', '=', True)]).write(
            {'overdue': False})

    # ------------------------------------------------------------------
    # Cancel·lades a Shopify
    # ------------------------------------------------------------------
    @api.model
    def _sync_shopify_status(self, config):
        if config.simulate_shopify or not config.sync_shopify_cancel:
            return
        logs = self.search([('config_id', '=', config.id), ('state', 'in', WAITING_STATES),
                            ('shopify_return_id', '=like', 'gid://%')])
        for i in range(0, len(logs), 50):
            chunk = logs[i:i + 50]
            ids = ', '.join('"%s"' % l.shopify_return_id for l in chunk)
            data = self._shopify_graphql(config, RETURN_STATUS_QUERY % {'ids': ids})
            status = {n['id']: n.get('status') for n in (data.get('nodes') or []) if n}
            for log in chunk:
                st = status.get(log.shopify_return_id)
                if st in ('CANCELED', 'DECLINED'):
                    try:
                        log._cancel_from_shopify(st)
                    except Exception as e:
                        self.env.cr.rollback()
                        _logger.exception('Cancelar devolución %s', log.remarks)
                        log.write({'issue': 'error', 'error_msg': _('Cancelada en Shopify, error al anular: %s') % e})
                    self.env.cr.commit()

    def _cancel_from_shopify(self, shopify_status):
        self.ensure_one()
        label = _('cancelada') if shopify_status == 'CANCELED' else _('rechazada')
        dev = self.dev_picking_id
        if dev.state == 'done':
            self.write({'issue': 'review', 'error_msg': _(
                'La devolución está %s en Shopify, pero la TT/DEV ya se ha validado.') % label})
            return
        notes = []
        config = self.config_id
        ref = self._tracking_ref()
        if ref and not ref.startswith('TEST'):
            try:
                if self.return_carrier == 'fedex' and not config.simulate_fedex:
                    config.fedex_carrier_id.fedex_return_cancel(self.nacex_albaran)
                    notes.append(_('envío FedEx anulado'))
                elif self.return_carrier != 'fedex' and not config.simulate_nacex:
                    config.carrier_id.nacex_cancel_return(self.nacex_cod_exp)
                    notes.append(_('recogida Nacex anulada'))
            except Exception as e:
                notes.append(_('NO se ha podido anular la recogida (anúlala a mano): %s') % e)
        if dev and dev.state not in ('done', 'cancel'):
            dev.action_cancel()
            notes.append(_('TT/DEV %s cancelada') % dev.name)
        self.write({'state': 'cancel', 'overdue': False})
        self.message_post(body=_('El cliente ha %s la devolución en Shopify: %s.') % (
            label, ', '.join(notes) or _('no había nada que anular')))

    # ------------------------------------------------------------------
    # Tancar a Shopify quan es tanca a mà
    # ------------------------------------------------------------------
    def action_close_manual(self):
        res = super().action_close_manual()
        for log in self.filtered(lambda l: l.state == 'closed'):
            log._shopify_close_return()
        return res

    def _shopify_close_return(self):
        if self.config_id.simulate_shopify or not (self.shopify_return_id or '').startswith('gid://'):
            return
        try:
            data = self._shopify_graphql(self.config_id, RETURN_CLOSE_MUTATION % {'id': self.shopify_return_id})
            errors = (data.get('returnClose') or {}).get('userErrors') or []
            if errors:
                # Normalment: ja està tancada (la Lorena ha reemborsat a Shopify)
                _logger.info('returnClose %s: %s', self.remarks, errors)
            else:
                self.message_post(body=_('Devolución cerrada también en Shopify.'))
        except Exception as e:
            _logger.info('returnClose %s: %s', self.remarks, e)

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def cron_process_returns(self):
        res = super().cron_process_returns()
        for config in self.env['shopify.return.config'].search([]):
            for step in ('_sync_shopify_status', '_update_overdue', '_cron_tracking'):
                try:
                    getattr(self, step)(config)
                    self.env.cr.commit()
                except Exception:
                    self.env.cr.rollback()
                    _logger.exception('Devoluciones Shopify [%s]: error en %s', config.name, step)
        return res

    @api.model
    def _cron_tracking(self, config):
        if not config.check_tracking:
            return
        recent = fields.Datetime.now() - timedelta(hours=3)
        logs = self.search([('config_id', '=', config.id), ('state', '=', 'done'),
                            ('nacex_albaran', '!=', False), ('carrier_delivered', '=', False),
                            '|', ('carrier_status_date', '=', False), ('carrier_status_date', '<', recent)],
                           order='id', limit=100)
        failures = 0
        for log in logs:
            if not log._update_tracking():
                failures += 1
                if failures >= 5:     # el transportista no respon: ja es tornarà a provar la propera hora
                    _logger.info('Devoluciones Shopify [%s]: el transportista no responde, se para el seguimiento.',
                                 config.name)
                    break
            self.env.cr.commit()

    # ------------------------------------------------------------------
    # Resum diari
    # ------------------------------------------------------------------
    @api.model
    def cron_daily_summary(self):
        for config in self.env['shopify.return.config'].search([('summary_partner_ids', '!=', False)]):
            try:
                self._send_summary(config)
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception('Resumen devoluciones %s', config.name)

    @staticmethod
    def _short(text, size=220):
        text = ' '.join((text or '').split())
        if len(text) <= size:
            return text
        return text[:size].rsplit(' ', 1)[0] + '…'

    def _money(self, amount, code):
        txt = ('%.2f' % (amount or 0.0)).replace('.', ',')
        symbol = {'EUR': '€', 'GBP': '£', 'USD': '$'}.get(code or 'EUR', code or '')
        return '%s %s' % (txt, symbol)

    @staticmethod
    def _days(n):
        return _('1 día') if n == 1 else _('%d días') % n

    def _summary_rows(self, title, logs, extra):
        if not logs:
            return ''
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        rows = ''.join(
            '<tr><td style="padding:2px 8px"><a href="%s/web#id=%d&amp;model=shopify.return.log&amp;view_type=form">%s</a></td>'
            '<td style="padding:2px 8px">%s</td><td style="padding:2px 8px">%s</td></tr>' % (
                base, l.id, html_escape(l.remarks or ''), html_escape(l.partner_name or ''), html_escape(extra(l) or ''))
            for l in logs[:50])
        more = '<p>... y %d más.</p>' % (len(logs) - 50) if len(logs) > 50 else ''
        return '<h3>%s (%d)</h3><table>%s</table>%s' % (title, len(logs), rows, more)

    @api.model
    def _send_summary(self, config):
        Log = self.search
        base = [('config_id', '=', config.id)]
        review = Log(base + [('issue', '=', 'review'), ('state', 'not in', ('cancel', 'refunded', 'closed'))])
        errors = Log(base + [('issue', '=', 'error'), ('state', 'not in', ('cancel', 'refunded', 'closed'))])
        to_accept = Log(base + [('state', '=', 'received'), ('issue', '=', 'none')])
        delivered = Log(base + [('state', '=', 'done'), ('carrier_delivered', '=', True)])
        overdue = Log(base + [('state', '=', 'done'), ('overdue', '=', True)])
        pending = Log(base + [('state', 'in', ('pending', 'validated')), ('issue', '=', 'none')])
        waiting = Log(base + [('state', '=', 'done')])

        body = ''.join([
            self._summary_rows(_('A revisar'), review, lambda l: self._short(l.error_msg)),
            self._summary_rows(_('Errores técnicos'), errors, lambda l: self._short(l.error_msg)),
            self._summary_rows(_('Recibidas: pendientes de aceptar'), to_accept,
                               lambda l: self._money(l.amount_to_refund, l.currency_code)),
            self._summary_rows(_('Entregadas por el transportista pero la TT/DEV no está validada'), delivered,
                               lambda l: '%s · %s' % (l.dev_picking_id.name or '', l.carrier_status or '')),
            self._summary_rows(_('Paquetes retrasados (más de %s)') % self._days(max(config.overdue_days, 0)), overdue,
                               lambda l: '%s · %s' % (self._days(l.days_waiting), l.carrier_status or _('sin estado del envío'))),
            self._summary_rows(_('Pendientes de procesar'), pending, lambda l: l.shopify_return_name or ''),
        ])
        if not body:
            return
        intro = '<p>%s</p>' % (_('Devoluciones Shopify %s: %d esperando el paquete, %d por revisar, %d por aceptar.') % (
            html_escape(config.name), len(waiting), len(review) + len(errors), len(to_accept)))
        self.env['mail.mail'].sudo().create({
            'subject': _('Devoluciones Shopify %s: resumen del %s') % (
                config.name, fields.Date.context_today(self).strftime('%d/%m/%Y')),
            'body_html': intro + body,
            'recipient_ids': [(6, 0, config.summary_partner_ids.ids)],
            'email_from': config.company_id.email or self.env.user.email or False,
            'auto_delete': True,
        })
