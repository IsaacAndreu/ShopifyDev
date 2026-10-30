# -*- coding: utf-8 -*-
import base64
import json
import logging
import time

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ORDERS_QUERY = """
{
  orders(first: 25%(after)s, query: "return_status:return_requested") {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        name
        email
        phone
        customer { displayName email phone }
        shippingAddress { name address1 address2 zip city countryCodeV2 phone }
        returns(first: 5) {
          edges {
            node {
              id
              name
              status
              returnLineItems(first: 50) {
                edges {
                  node {
                    quantity
                    ... on ReturnLineItem {
                      id
                      returnReason
                      customerNote
                      fulfillmentLineItem { lineItem {
                        id sku quantity
                        originalUnitPriceSet { shopMoney { amount currencyCode } }
                        discountAllocations { allocatedAmountSet { shopMoney { amount } } }
                      } }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

APPROVE_MUTATION = """
mutation {
  returnApproveRequest(input: { id: "%(id)s"%(notify)s }) {
    return { id status }
    userErrors { field message }
  }
}
"""

RFO_QUERY = """
{
  return(id: "%(id)s") {
    reverseFulfillmentOrders(first: 5) {
      edges { node { id lineItems(first: 100) { edges { node { id totalQuantity } } } } }
    }
  }
}
"""

REVERSE_DELIVERY_MUTATION = """
mutation {
  reverseDeliveryCreateWithShipping(
    reverseFulfillmentOrderId: "%(rfo)s",
    reverseDeliveryLineItems: [%(lines)s],
    trackingInput: { number: "%(number)s", url: "%(url)s" }%(label)s,
    notifyCustomer: %(notify)s
  ) {
    reverseDelivery { id }
    userErrors { field message }
  }
}
"""

SUGGESTED_REFUND_QUERY = """
{
  order(id: "%(order)s") {
    suggestedRefund(refundLineItems: [%(lines)s]) {
      amountSet { shopMoney { amount currencyCode } }
      suggestedTransactions {
        parentTransaction { id }
        amountSet { shopMoney { amount currencyCode } }
      }
    }
  }
}
"""

RETURN_REFUND_MUTATION = """
mutation {
  returnRefund(returnRefundInput: {
    returnId: "%(id)s",
    returnRefundLineItems: [%(lines)s],
    orderTransactions: [%(tx)s],
    notifyCustomer: %(notify)s
  }) {
    refund { id totalRefundedSet { shopMoney { amount currencyCode } } }
    userErrors { field message }
  }
}
"""

REFUND_QUERY = """
{
  node(id: "%(id)s") {
    ... on Refund {
      id
      totalRefundedSet { shopMoney { amount currencyCode } }
      refundLineItems(first: 100) { edges { node {
        quantity
        subtotalSet { shopMoney { amount } }
        lineItem { id sku }
      } } }
    }
  }
}
"""

RETURN_CLOSE_MUTATION = """
mutation {
  returnClose(id: "%(id)s") {
    return { id status }
    userErrors { field message }
  }
}
"""

RETURN_REASONS = {
    'SIZE_TOO_LARGE': 'Demasiado grande', 'SIZE_TOO_SMALL': 'Demasiado pequeño', 'COLOR': 'Color',
    'DEFECTIVE': 'Defectuoso', 'NOT_AS_DESCRIBED': 'No es como se describía',
    'STYLE': 'Estilo', 'UNWANTED': 'Ya no lo quiere', 'WRONG_ITEM': 'Artículo equivocado',
    'OTHER': 'Otros', 'UNKNOWN': 'Desconocido',
}

STAGED_UPLOAD_MUTATION = """
mutation {
  stagedUploadsCreate(input: [{ resource: RETURN_LABEL, filename: "%(filename)s",
                                mimeType: "application/pdf", httpMethod: POST, fileSize: "%(size)d" }]) {
    stagedTargets { url resourceUrl parameters { name value } }
    userErrors { field message }
  }
}
"""

STATES = [
    ('pending', 'Pendiente'),
    ('validated', 'Validada en Odoo'),
    ('dev_created', 'TT/DEV creada'),
    ('nacex_ok', 'Recogida creada'),
    ('done', 'Aprobada en Shopify'),
    ('received', 'Recibida: pendiente de revisión'),
    ('refunded', 'Reembolsada'),
    ('closed', 'Cerrada (hecha a mano)'),
    ('cancel', 'Cancelada'),
]


class ShopifyReturnLog(models.Model):
    _name = 'shopify.return.log'
    _description = 'Devolución Shopify'
    _inherit = ['mail.thread']
    _order = 'id desc'
    _rec_name = 'remarks'

    config_id = fields.Many2one('shopify.return.config', 'Configuración', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='config_id.company_id', store=True)

    # --- Shopify ---
    shopify_return_id = fields.Char('ID devolución Shopify', required=True, index=True, readonly=True)
    shopify_return_name = fields.Char('Devolución', readonly=True)
    shopify_order_id = fields.Char('ID pedido Shopify', readonly=True)
    remarks = fields.Char('Remarks', index=True, readonly=True)
    partner_name = fields.Char('Cliente')
    email = fields.Char('Email')
    phone = fields.Char('Teléfono')
    street = fields.Char('Dirección')
    zip = fields.Char('C.P.')
    city = fields.Char('Población')
    country_code = fields.Char('País')
    line_ids = fields.One2many('shopify.return.log.line', 'log_id', string='Artículos')

    # --- Odoo ---
    sale_id = fields.Many2one('sale.order', 'Pedido de venta', readonly=True, index=True)
    out_picking_id = fields.Many2one('stock.picking', 'OUT', readonly=True)
    dev_picking_id = fields.Many2one('stock.picking', 'TT/DEV', readonly=True, index=True)

    # --- Nacex ---
    return_carrier = fields.Selection([('nacex', 'Nacex'), ('fedex', 'FedEx')],
                                      string='Transportista', readonly=True)
    fedex_pickup = fields.Boolean(
        'Recogida a domicilio (FedEx)',
        help='Se decide sola según el país (y si hay puntos FedEx cerca). '
             'Se puede marcar a mano antes de procesar la devolución.')
    fedex_dropoff_point = fields.Char('Punto FedEx más cercano', readonly=True)
    nacex_return_method = fields.Selection(related='config_id.nacex_return_method', string='Tipo devolución Nacex')
    nacex_shop_code = fields.Char(
        'Punto NACEX.shop', help='Código del punto NACEX.shop. Vacío: el de la configuración.')
    nacex_cod_exp = fields.Char('Código expedición / recogida', readonly=True)
    nacex_albaran = fields.Char('Albarán / nº seguimiento', readonly=True)
    label_attachment_id = fields.Many2one('ir.attachment', 'Etiqueta', readonly=True)

    # --- Aprovació / reemborsament ---
    shopify_approved = fields.Boolean('Aprobada en Shopify', readonly=True, copy=False)
    shopify_tracking_done = fields.Boolean('Seguimiento subido a Shopify', readonly=True, copy=False)
    refund_invoice_id = fields.Many2one('account.move', 'Rectificativa', readonly=True, copy=False)
    shopify_refund_id = fields.Char('ID reembolso Shopify', readonly=True, copy=False)
    refund_amount = fields.Char('Importe reembolsado', readonly=True, copy=False)
    shopify_refunded_total = fields.Float('Reembolsado en Shopify', digits=(16, 2), readonly=True, copy=False)
    discrepancy = fields.Boolean('Hay diferencias', readonly=True, copy=False)

    # --- Dates ---
    approved_date = fields.Datetime('Aprobada el', readonly=True, copy=False)
    received_date = fields.Datetime('Recibida el', readonly=True, copy=False)
    closed_date = fields.Datetime('Cerrada el', readonly=True, copy=False)
    days_waiting = fields.Integer('Días esperando el paquete', compute='_compute_days_waiting')

    # --- Imports ---
    currency_code = fields.Char('Moneda', readonly=True)
    amount_expected = fields.Float('Importe solicitado', compute='_compute_amounts', digits=(16, 2))
    amount_to_refund = fields.Float('Importe a reembolsar', compute='_compute_amounts', digits=(16, 2))

    # --- Magatzem ---
    incident_note = fields.Text(related='dev_picking_id.return_incident_note', string='Nota del almacén')

    # --- Enllaços ---
    shopify_admin_url = fields.Char('Shopify', compute='_compute_urls')
    nacex_tracking_url = fields.Char('Seguimiento transportista', compute='_compute_urls')

    @api.depends('approved_date', 'received_date', 'state')
    def _compute_days_waiting(self):
        now = fields.Datetime.now()
        for log in self:
            end = log.received_date or now
            log.days_waiting = (end - log.approved_date).days if log.approved_date else 0

    @api.depends('line_ids.amount_expected', 'line_ids.amount_to_refund')
    def _compute_amounts(self):
        for log in self:
            log.amount_expected = sum(log.line_ids.mapped('amount_expected'))
            log.amount_to_refund = sum(log.line_ids.mapped('amount_to_refund'))

    def _shop_handle(self):
        try:
            url = self.config_id.integration_id.get_settings_value('url') or ''
        except Exception:
            url = ''
        return url.split('//')[-1].split('.myshopify.com')[0].strip('/')

    @api.depends('shopify_order_id', 'nacex_albaran')
    def _compute_urls(self):
        for log in self:
            log.shopify_admin_url = False
            handle = log._shop_handle() if log.shopify_order_id else ''
            if handle and log.shopify_order_id and 'gid://' in log.shopify_order_id:
                log.shopify_admin_url = 'https://admin.shopify.com/store/%s/orders/%s' % (
                    handle, log.shopify_order_id.split('/')[-1])
            log.nacex_tracking_url = log._nacex_tracking_url() if log.nacex_albaran and not (log.nacex_albaran or '').startswith('TEST') else False

    def action_open_shopify(self):
        self.ensure_one()
        if not self.shopify_admin_url:
            raise UserError(_('Esta devolución no tiene pedido de Shopify (es de prueba).'))
        return {'type': 'ir.actions.act_url', 'url': self.shopify_admin_url, 'target': 'new'}

    def action_open_nacex(self):
        self.ensure_one()
        if not self.nacex_tracking_url:
            raise UserError(_('No hay seguimiento real del transportista.'))
        return {'type': 'ir.actions.act_url', 'url': self.nacex_tracking_url, 'target': 'new'}

    def _find_manual_refund(self):
        """Rectificativa feta a mà: abonament de la comanda, posterior a l'aprovació
        de la devolució i que no estigui enllaçada a cap altra devolució."""
        self.ensure_one()
        since = self.approved_date or self.create_date
        refunds = self.sale_id.invoice_ids.filtered(
            lambda m: m.type == 'out_refund' and m.state != 'cancel'
            and (not since or m.create_date >= since))
        if refunds:
            used = self.search([('refund_invoice_id', 'in', refunds.ids), ('id', '!=', self.id)])
            refunds -= used.mapped('refund_invoice_id')
        return refunds.sorted('create_date', reverse=True)[:1]

    def action_close_manual(self):
        """La Lorena ha fet la rectificativa i el reemborsament a mà."""
        self.ensure_one()
        if self.state != 'received':
            return True
        refund = self.refund_invoice_id or self._find_manual_refund()
        if not refund and not self.env.context.get('force_close'):
            return {
                'type': 'ir.actions.act_window',
                'name': _('Cerrar devolución'),
                'res_model': 'shopify.return.close.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_log_id': self.id},
            }
        vals = {'state': 'closed', 'closed_date': fields.Datetime.now(),
                'issue': 'none', 'error_msg': False}
        msgs = []
        if refund:
            vals['refund_invoice_id'] = refund.id
            msgs.append(_('Rectificativa %s enlazada (%.2f %s).') % (
                refund.name or refund.display_name, refund.amount_total, refund.currency_id.name or ''))
            ref_amount = self.shopify_refunded_total or self.amount_to_refund
            if ref_amount and abs(refund.amount_total - ref_amount) > 0.02:
                warning = _('La rectificativa (%.2f) no coincide con lo que dice Shopify (%.2f). '
                            'Revisa los descuentos.') % (refund.amount_total, ref_amount)
                vals.update({'issue': 'review', 'error_msg': warning})
                msgs.append(warning)
        else:
            msgs.append(_('Cerrada sin rectificativa enlazada.'))
        self.write(vals)
        self.message_post(body=_('Cerrada a mano. ') + ' '.join(msgs))
        return True

    # --- Control ---
    state = fields.Selection(STATES, string='Estado', default='pending', required=True, tracking=True, index=True)
    issue = fields.Selection(
        [('none', 'Ninguna'), ('review', 'Revisión manual'), ('error', 'Error técnico')], string='Incidencia',
        default='none', required=True, tracking=True)
    error_msg = fields.Text('Mensaje', readonly=True)
    attempts = fields.Integer('Intentos', readonly=True)

    _sql_constraints = [
        ('uniq_return', 'unique(shopify_return_id)', 'Esta devolución de Shopify ya está registrada.'),
    ]

    # ==================================================================
    # 1. LLEGIR DEVOLUCIONS DE SHOPIFY
    # ==================================================================
    @staticmethod
    def _is_throttled(err):
        text = str(err)
        return '429' in text or 'THROTTLED' in text.upper() or 'Exceeded' in text

    @api.model
    def _shopify_graphql(self, config, query, tries=5):
        """Crida GraphQL amb reintents quan Shopify diu que anem massa ràpid (429 / THROTTLED):
        el connector de VentorTech ja gasta bona part del límit de peticions de la botiga."""
        adapter = config.integration_id._build_adapter()
        for attempt in range(tries):
            last = attempt == tries - 1
            try:
                res = adapter.execute_graphql(query)
            except Exception as e:
                if not last and self._is_throttled(e):
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
            if isinstance(res, (str, bytes)):
                res = json.loads(res)
            errors = res.get('errors')
            if errors and not last and self._is_throttled(errors):
                time.sleep(2 * (attempt + 1))
                continue
            if errors:
                raise Exception('Shopify GraphQL: %s' % errors)
            return res.get('data') or {}

    @api.model
    def _fetch_for_config(self, config):
        created = self.browse()
        if config.simulate_shopify:
            return created
        after, pages = '', 0
        while pages < 40:
            pages += 1
            data = self._shopify_graphql(config, ORDERS_QUERY % {'after': after})
            orders = data.get('orders') or {}
            for edge in orders.get('edges', []):
                created |= self._create_from_order(config, edge['node'])
            info = orders.get('pageInfo') or {}
            if not info.get('hasNextPage'):
                break
            after = ', after: "%s"' % info['endCursor']
        if created:
            _logger.info('Devoluciones Shopify [%s]: %s nuevas', config.name, len(created))
        return created

    @api.model
    def _create_from_order(self, config, order):
        created = self.browse()
        customer = order.get('customer') or {}
        address = order.get('shippingAddress') or {}
        for ret_edge in (order.get('returns') or {}).get('edges', []):
            ret = ret_edge['node']
            if ret.get('status') != 'REQUESTED':
                continue
            if self.with_context(active_test=False).search_count(
                    [('shopify_return_id', '=', ret['id'])]):
                continue
            lines = []
            currency = None
            for li_edge in (ret.get('returnLineItems') or {}).get('edges', []):
                li = li_edge['node']
                order_line = (li.get('fulfillmentLineItem') or {}).get('lineItem') or {}
                money = ((order_line.get('originalUnitPriceSet') or {}).get('shopMoney') or {})
                unit = float(money.get('amount') or 0.0)
                currency = currency or money.get('currencyCode')
                line_qty = order_line.get('quantity') or 1
                disc_total = sum(float(((d.get('allocatedAmountSet') or {}).get('shopMoney') or {}).get('amount') or 0)
                                 for d in order_line.get('discountAllocations') or [])
                unit_disc = disc_total / line_qty if line_qty else 0.0
                lines.append((0, 0, {
                    'sku': order_line.get('sku') or '',
                    'quantity': li.get('quantity') or 0,
                    'shopify_line_id': li.get('id'),
                    'shopify_order_line_id': order_line.get('id'),
                    'unit_price': unit,
                    'unit_discount': unit_disc,
                    'return_reason': RETURN_REASONS.get(li.get('returnReason'), li.get('returnReason') or ''),
                    'customer_note': li.get('customerNote') or '',
                }))
            created |= self.create({
                'config_id': config.id,
                'shopify_return_id': ret['id'],
                'shopify_return_name': ret.get('name'),
                'shopify_order_id': order.get('id'),
                'remarks': order.get('name'),
                'partner_name': customer.get('displayName') or address.get('name'),
                'email': order.get('email') or customer.get('email'),
                'phone': address.get('phone') or order.get('phone') or customer.get('phone'),
                'street': ' '.join(filter(None, [address.get('address1'), address.get('address2')])),
                'zip': address.get('zip'),
                'city': address.get('city'),
                'country_code': address.get('countryCodeV2'),
                'currency_code': currency or 'EUR',
                'line_ids': lines,
            })
        return created

    # ==================================================================
    # 2. PROCESSAR
    # ==================================================================
    def _try_lock(self):
        """Bloqueja la fila mentre es processa: si el cron i una persona (o dues persones)
        la processen alhora, el segon se la salta. Així mai es fan dues recollides
        ni dos reemborsaments."""
        try:
            self.env.cr.execute('SELECT id FROM shopify_return_log WHERE id = %s FOR UPDATE NOWAIT', (self.id,))
        except Exception:
            self.env.cr.rollback()
            _logger.info('Devolución %s: ya se está procesando, se salta.', self.remarks)
            return False
        self.invalidate_cache()
        return True

    def action_process(self):
        for log in self:
            if log.state in ('done', 'received', 'refunded', 'closed', 'cancel') or log.issue == 'review':
                continue
            if not log._try_lock():
                continue
            if log.state in ('done', 'received', 'refunded', 'closed', 'cancel'):
                continue
            try:
                log._process_one()
                if log.state != 'received':      # la recepció ja posa la seva incidència
                    log.write({'issue': 'none', 'error_msg': False})
            except UserError as e:
                self.env.cr.rollback()
                log.write({'issue': 'review', 'error_msg': e.name if hasattr(e, 'name') else str(e)})
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception('Devolución %s', log.remarks)
                log.write({'issue': 'error', 'error_msg': str(e), 'attempts': log.attempts + 1})
            self.env.cr.commit()
        return True

    def action_retry(self):
        self.write({'issue': 'none', 'error_msg': False, 'attempts': 0})
        return self.action_process()

    def action_cancel(self):
        # Si ja s'havia creat la TT/DEV i encara no s'ha rebut, també es cancel·la
        for log in self:
            dev = log.dev_picking_id
            if dev and dev.state not in ('done', 'cancel'):
                dev.action_cancel()
        self.write({'state': 'cancel'})

    def _process_one(self):
        """Cada pas guarda l'estat i fa commit: si falla a mitges, el
        següent intent continua on s'havia quedat i mai es crea dues
        vegades la recollida de Nacex."""
        self.ensure_one()
        if self.state == 'pending':
            self._step_validate()
            self.state = 'validated'
            self.env.cr.commit()
        if self.state == 'validated':
            # La TT/DEV va primer perquè el seu nom surti a l'etiqueta de Nacex
            if not self.dev_picking_id:
                self._step_create_dev()
            self.state = 'dev_created'
            self.env.cr.commit()
        if self.state == 'dev_created':
            dev = self.dev_picking_id
            if dev.state == 'done' or (dev.carrier_tracking_ref and self.nacex_albaran == dev.carrier_tracking_ref):
                # DEV adoptada que ja té recollida o que ja s'ha rebut: no es crea cap recollida
                self.message_post(body=_('No se crea recogida: la TT/DEV ya %s.') % (
                    _('está validada') if dev.state == 'done' else _('tiene el seguimiento %s') % dev.carrier_tracking_ref))
            elif self.return_carrier == 'fedex':
                self._step_fedex()
            else:
                self._step_nacex()
            self.state = 'nacex_ok'
            self.env.cr.commit()
            if not self.label_attachment_id and self.nacex_cod_exp:
                self._step_label()          # no bloqueja si falla
            self.env.cr.commit()
        if self.state == 'nacex_ok':
            self._step_approve()
            self.write({'state': 'done', 'approved_date': fields.Datetime.now()})
            if self.dev_picking_id.state == 'done':
                # El paquet ja havia arribat (DEV adoptada ja validada)
                self._on_dev_received()

    # ------------------------------------------------------------------
    def _step_validate(self):
        remarks = (self.remarks or '').strip()
        Sale = self.env['sale.order']
        sales = Sale.search([('ref_remarks', '=', remarks), ('company_id', '=', self.company_id.id)])
        if not sales and remarks.startswith('#'):
            sales = Sale.search([('ref_remarks', '=', remarks[1:]), ('company_id', '=', self.company_id.id)])
        if len(sales) != 1:
            raise UserError(_('Se han encontrado %s pedidos con remarks %s.') % (len(sales), remarks))

        outs = sales.picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p.state == 'done')
        if not outs:
            raise UserError(_('El pedido %s no tiene ningún OUT validado.') % remarks)
        if len(outs) > 1:
            raise UserError(_('El pedido %s tiene %s OUT validados: hay que elegirlo a mano.') % (remarks, len(outs)))

        pending_outs = sales.picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p.state not in ('done', 'cancel'))
        if pending_outs or outs.backorder_id:
            raise UserError(_('El pedido %s tiene entregas parciales (%s): se gestiona aparte.')
                            % (remarks, ', '.join((pending_outs | outs.backorder_id).mapped('name'))))

        existing = self.env['stock.picking'].search([
            ('move_lines.origin_returned_move_id', 'in', outs.move_lines.ids),
            ('state', '!=', 'cancel'),
        ])
        adopt = self.env['stock.picking']
        if existing:
            # Una TT/DEV feta a mà (p. ex. amb "Devs masivas ONLINE"): s'aprofita en lloc
            # d'aturar-se, sempre que sigui una sola i no la faci servir cap altra devolució.
            used = self.search([('dev_picking_id', 'in', existing.ids), ('id', '!=', self.id)])
            if len(existing) > 1 or used:
                raise UserError(_('El OUT %s ya tiene devoluciones creadas (%s).')
                                % (outs.name, ', '.join(existing.mapped('name'))))
            adopt = existing

        lines = self.line_ids.filtered(lambda l: not l.ignore)
        if not lines:
            raise UserError(_('La devolución de Shopify no tiene artículos.'))
        for line in lines:
            mapped = self._product_from_mapping(line.sku)
            move = outs.move_lines.filtered(
                lambda m: line.sku and (m.product_id == mapped
                                        or line.sku in (m.product_id.default_code, m.product_id.barcode)))
            if not move:
                raise UserError(_('El SKU %s no está en el OUT %s.') % (line.sku, outs.name))
            if line.quantity > sum(move.mapped('quantity_done')):
                raise UserError(_('Se devuelven %s u. de %s pero solo se enviaron %s.')
                                % (line.quantity, line.sku, sum(move.mapped('quantity_done'))))
            line.product_id = move[0].product_id

        config = self.config_id
        country = (self.country_code or '').upper()
        if not config.nacex_country_ids or country in config.nacex_country_ids.mapped('code'):
            carrier = 'nacex'
        elif config.fedex_carrier_id:
            carrier = 'fedex'
        else:
            raise UserError(_('No hay transportista configurado para devoluciones de %s.') % (country or '?'))
        vals = {'sale_id': sales.id, 'out_picking_id': outs.id, 'return_carrier': carrier,
                'fedex_pickup': carrier == 'fedex' and (
                    self.fedex_pickup or country in config.fedex_pickup_country_ids.mapped('code'))}
        if adopt:
            vals['dev_picking_id'] = adopt.id
            if adopt.carrier_tracking_ref:
                # Ja hi ha recollida feta a mà: no se'n crea una altra
                vals['nacex_albaran'] = adopt.carrier_tracking_ref
        self.write(vals)
        if adopt:
            self.message_post(body=_('Ya existía la TT/DEV %s (%s): se aprovecha%s.') % (
                adopt.name, dict(adopt._fields['state']._description_selection(self.env)).get(adopt.state, adopt.state),
                _(' con el seguimiento %s') % adopt.carrier_tracking_ref if adopt.carrier_tracking_ref else ''))

    def _product_from_mapping(self, sku):
        """Producte d'Odoo enllaçat al connector amb aquest SKU de Shopify.
        El SKU de Shopify no sempre és el default_code (p. ej. 21118499_7Y -> 21118499_7-8Y)."""
        if not sku or not self.config_id.integration_id:
            return self.env['product.product']
        ext = self.env['integration.product.product.external'].search([
            ('integration_id', '=', self.config_id.integration_id.id), ('external_reference', '=', sku)], limit=1)
        if not ext:
            return self.env['product.product']
        return self.env['integration.product.product.mapping'].search(
            [('external_product_id', '=', ext.id), ('product_id', '!=', False)], limit=1).product_id

    # ------------------------------------------------------------------
    def _step_nacex(self):
        config = self.config_id
        carrier = config.carrier_id
        if config.simulate_nacex:
            if config.nacex_return_method == 'label':
                self.message_post(body=_('[SIMULACIÓN] genEtiquetaDevolucion: eDevolución SHOP abierta, ref. %s')
                                  % (self.dev_picking_id.name or self.remarks))
            else:
                data = carrier.nacex_build_return_data(self)
                self.message_post(body=_('[SIMULACIÓN] putExpedicion data:<br/><code>%s</code>')
                                  % data.replace('|', ' | '))
            cod_exp, albaran = 'TEST', 'TEST/%s' % self.id
        elif config.nacex_return_method == 'label':
            cod_exp, pdf = carrier.nacex_gen_return_label(self)
            albaran = cod_exp
            try:
                albaran = carrier.nacex_get_status(cod_exp)[2] or cod_exp
            except Exception as e:
                # Sense albarà de moment: el cron de seguiment el corregirà
                _logger.info('Albarán Nacex %s: %s', self.remarks, e)
            att = self.env['ir.attachment'].create({
                'name': 'Nacex devolucion %s.pdf' % (self.remarks or '').lstrip('#'),
                'datas': base64.b64encode(pdf),
                'res_model': self._name, 'res_id': self.id, 'mimetype': 'application/pdf',
            })
            self.label_attachment_id = att
            self._send_label_email(att)
        else:
            cod_exp, albaran = carrier.nacex_put_return_expedicion(self)
        self.write({'nacex_cod_exp': cod_exp, 'nacex_albaran': albaran})
        self.dev_picking_id.write({'carrier_tracking_ref': albaran})
        msg = _('Recogida Nacex creada: %s (exp. %s)') % (albaran, cod_exp)
        self.message_post(body=msg)
        self.dev_picking_id.message_post(body=msg)

    def _step_fedex(self):
        config = self.config_id
        carrier = config.fedex_carrier_id
        pickup = self.fedex_pickup
        if not pickup and config.fedex_check_locations and not self.nacex_albaran:
            if config.simulate_fedex:
                self.message_post(body=_('[SIMULACIÓN] Aquí se comprobaría si hay puntos FedEx a %s km del cliente.')
                                  % config.fedex_location_radius)
            else:
                has_point, point = carrier.fedex_has_dropoff_location(self, config.fedex_location_radius or 20)
                if point:
                    self.fedex_dropoff_point = point
                if has_point is False:
                    pickup = True
                    self.fedex_pickup = True
                    self.message_post(body=_('No hay puntos FedEx a %s km del cliente: se programa recogida a domicilio.')
                                      % (config.fedex_location_radius or 20))
                elif has_point is None:
                    self.message_post(body=_('No se ha podido comprobar si hay puntos FedEx cerca '
                                             '(¿API de ubicaciones no activada?). Se hace con entrega en punto.'))
        if config.simulate_fedex:
            payload = carrier.fedex_return_payload(self, pickup)
            body = _('[SIMULACIÓN] FedEx /ship/v1/shipments:<br/><pre>%s</pre>') % json.dumps(payload, indent=1)[:6000]
            if pickup:
                body += _('<br/>[SIMULACIÓN] FedEx /pickup/v1/pickups:<br/><pre>%s</pre>') % json.dumps(
                    carrier.fedex_return_pickup_payload(self, 'TESTFX'), indent=1)[:3000]
            self.message_post(body=body)
            tracking, label, pickup_code = 'TESTFX/%s' % self.id, False, ('TESTPICKUP' if pickup else '')
        else:
            if self.nacex_albaran and not self.nacex_albaran.startswith('TEST'):
                # Reintent: l'enviament ja existeix a FedEx, no se'n crea un altre
                tracking, label = self.nacex_albaran, False
            else:
                tracking, label = carrier.fedex_return_create(self, pickup)
                if label:
                    att = self.env['ir.attachment'].create({
                        'name': 'FedEx devolucion %s.pdf' % (self.remarks or '').lstrip('#'),
                        'datas': label, 'res_model': self._name, 'res_id': self.id,
                        'mimetype': 'application/pdf',
                    })
                    self.write({'label_attachment_id': att.id})
                    label = False
                self.write({'nacex_albaran': tracking})
                self.env.cr.commit()     # l'enviament ja existeix a FedEx: que no es perdi
            pickup_code = ''
            if pickup:
                try:
                    pickup_code = carrier.fedex_return_pickup(self, tracking)
                except UserError as e:
                    if not config.fedex_pickup_fallback:
                        raise
                    # P. ex. FORBIDDEN si el compte no té l'API de recollides: l'etiqueta ja és vàlida,
                    # el client la porta a un punt FedEx i no s'atura la devolució
                    pickup = False
                    self.fedex_pickup = False
                    self.message_post(body=_('FedEx no ha aceptado la recogida a domicilio: el cliente '
                                             'llevará el paquete a un punto FedEx.<br/>%s')
                                      % (e.name if hasattr(e, 'name') else e))
        vals = {'nacex_albaran': tracking, 'nacex_cod_exp': pickup_code}
        if label:
            att = self.env['ir.attachment'].create({
                'name': 'FedEx devolucion %s.pdf' % (self.remarks or '').lstrip('#'),
                'datas': label, 'res_model': self._name, 'res_id': self.id,
                'mimetype': 'application/pdf',
            })
            vals['label_attachment_id'] = att.id
        self.write(vals)
        self.dev_picking_id.write({'carrier_tracking_ref': tracking})
        msg = _('Envío FedEx creado: %s') % tracking
        msg += (_(' · Recogida a domicilio %s') % pickup_code) if pickup else (
            _(' · El cliente lo lleva a un punto FedEx') + ((': %s' % self.fedex_dropoff_point) if self.fedex_dropoff_point else ''))
        self.message_post(body=msg)
        self.dev_picking_id.message_post(body=msg)

    def _send_label_email(self, att):
        """Envia l'etiqueta al client amb la plantilla de la config (send_label_email). No bloqueja si falla."""
        config = self.config_id
        if not (config.send_label_email and config.mail_template_id and self.email):
            return
        try:
            config.mail_template_id.send_mail(
                self.id, force_send=True,
                email_values={'attachment_ids': [(4, att.id)]})
        except Exception as e:
            _logger.warning('Email etiqueta %s: %s', self.remarks, e)
            self.message_post(body=_('No se ha podido enviar la etiqueta por email: %s') % e)

    def _step_label(self):
        if self.config_id.simulate_nacex or self.return_carrier == 'fedex':
            return
        try:
            pdf = self.config_id.carrier_id.nacex_get_label_pdf(self.nacex_cod_exp)
            att = self.env['ir.attachment'].create({
                'name': 'Nacex devolucion %s.pdf' % (self.remarks or '').lstrip('#'),
                'datas': base64.b64encode(pdf),
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
            self.label_attachment_id = att
            self._send_label_email(att)
        except Exception as e:
            _logger.warning('Etiqueta Nacex %s: %s', self.remarks, e)
            self.message_post(body=_('No se ha podido obtener/enviar la etiqueta: %s') % e)

    # ------------------------------------------------------------------
    def _step_approve(self):
        config = self.config_id
        if config.simulate_shopify:
            self.message_post(body=_('[SIMULACIÓN] Aquí se aprobaría la devolución %s en Shopify '
                                     'y se subiría el seguimiento %s.')
                              % (self.shopify_return_id, self.nacex_albaran or _('(sin seguimiento)')))
            return
        # 1) Aprovar (una sola vegada, encara que després falli el seguiment)
        with_label = bool(config.shopify_add_tracking and config.shopify_upload_label and self.label_attachment_id)
        if not self.shopify_approved:
            # Amb etiqueta, l'email al client l'envia Shopify en penjar-la (com fa la Lorena amb FedEx)
            notify = ', notifyCustomer: true' if (config.shopify_notify_customer and not with_label) else ''
            data = self._shopify_graphql(config, APPROVE_MUTATION % {'id': self.shopify_return_id, 'notify': notify})
            result = data.get('returnApproveRequest') or {}
            errors = result.get('userErrors') or []
            if errors:
                raise UserError(_('Shopify no ha aprobado la devolución: %s')
                                % '; '.join(e.get('message', '') for e in errors))
            self.shopify_approved = True
            self.message_post(body=_('Devolución aprobada en Shopify (%s).')
                              % ((result.get('return') or {}).get('status')))
            self.env.cr.commit()
        # 2) Penjar el seguiment de Nacex (així no cal "No se requiere envío")
        if config.shopify_add_tracking and not self.shopify_tracking_done and self.nacex_albaran:
            self._shopify_add_tracking()
            self.shopify_tracking_done = True

    def _nacex_tracking_url(self):
        if self.return_carrier == 'fedex':
            return 'https://www.fedex.com/fedextrack/?trknbr=%s' % (self.nacex_albaran or '')
        return 'https://www.nacex.es/seguimientoFormularioExterno.do?intcli=%s' % (self.nacex_albaran or '')

    def _shopify_upload_label(self):
        """Puja el PDF a Shopify (staged upload RETURN_LABEL) i retorna la URL per a labelInput."""
        att = self.label_attachment_id
        pdf = base64.b64decode(att.datas)
        data = self._shopify_graphql(self.config_id, STAGED_UPLOAD_MUTATION % {
            'filename': (att.name or 'etiqueta.pdf').replace('"', ''), 'size': len(pdf)})
        res = data.get('stagedUploadsCreate') or {}
        if res.get('userErrors'):
            raise Exception('stagedUploadsCreate: %s' % res['userErrors'])
        target = (res.get('stagedTargets') or [{}])[0]
        params = {p['name']: p['value'] for p in target.get('parameters') or []}
        up = requests.post(target['url'], data=params,
                           files={'file': (att.name or 'etiqueta.pdf', pdf, 'application/pdf')}, timeout=60)
        if up.status_code >= 300:
            raise Exception('Subida etiqueta HTTP %s %s' % (up.status_code, up.text[:300]))
        return target.get('resourceUrl')

    def _shopify_add_tracking(self):
        config = self.config_id
        data = self._shopify_graphql(config, RFO_QUERY % {'id': self.shopify_return_id})
        rfos = ((data.get('return') or {}).get('reverseFulfillmentOrders') or {}).get('edges', [])
        if not rfos:
            raise UserError(_('Shopify no ha creado la orden de devolución (reverse fulfillment).'))
        rfo = rfos[0]['node']
        lines = ', '.join(
            '{ reverseFulfillmentOrderLineItemId: "%s", quantity: %d }' % (e['node']['id'], e['node']['totalQuantity'])
            for e in (rfo.get('lineItems') or {}).get('edges', []))
        label = ''
        if config.shopify_upload_label and self.label_attachment_id:
            try:
                label = ', labelInput: { fileUrl: "%s" }' % self._shopify_upload_label()
            except Exception as e:
                _logger.warning('Etiqueta a Shopify %s: %s', self.remarks, e)
                self.message_post(body=_('No se ha podido subir la etiqueta a Shopify (se sube solo el seguimiento): %s') % e)
        mutation = REVERSE_DELIVERY_MUTATION % {
            'rfo': rfo['id'], 'lines': lines,
            'number': self.nacex_albaran or '', 'url': self._nacex_tracking_url(),
            'label': label, 'notify': 'true' if (config.shopify_notify_tracking or label) else 'false',
        }
        result = self._shopify_graphql(config, mutation).get('reverseDeliveryCreateWithShipping') or {}
        errors = result.get('userErrors') or []
        if errors:
            raise UserError(_('Shopify no ha aceptado el seguimiento: %s')
                            % '; '.join(e.get('message', '') for e in errors))
        self.message_post(body=_('Seguimiento %s (%s) subido a Shopify%s.') % (
            self.nacex_albaran, dict(self._fields['return_carrier'].selection).get(self.return_carrier, ''),
            _(' con la etiqueta') if label else ''))

    # ------------------------------------------------------------------
    def _step_create_dev(self):
        """Mateixa lògica que l'acció de servidor 'Devs masivas ONLINE'."""
        out = self.out_picking_id
        if self.config_id.return_full_order:
            moves = [(0, 0, {
                'product_id': m.product_id.id,
                'quantity': m.product_uom_qty,
                'move_id': m.id,
                'to_refund': True,   # perquè la comanda pugui generar la rectificativa
            }) for m in out.move_lines]
        else:
            moves = []
            for line in self.line_ids.filtered(lambda l: not l.ignore):
                move = out.move_lines.filtered(lambda m: m.product_id == line.product_id)[:1]
                moves.append((0, 0, {
                    'product_id': line.product_id.id,
                    'quantity': line.quantity,
                    'move_id': move.id,
                    'to_refund': True,
                }))

        ctx = {'active_model': 'stock.picking', 'active_id': out.id, 'active_ids': [out.id]}
        wizard = self.env['stock.return.picking'].with_context(ctx).create({
            'picking_id': out.id,
            'location_id': self.config_id.return_location_id.id,
            'product_return_moves': moves,
        })
        res = wizard.create_returns()
        dev = self.env['stock.picking'].browse(res.get('res_id'))
        self.dev_picking_id = dev
        msg = _('Devolución Shopify %s') % (self.shopify_return_name or self.remarks)
        dev.message_post(body=msg)
        out.message_post(body=_('Creada la devolución %s. %s') % (dev.name, msg))

    # ==================================================================
    # 3. RECEPCIÓ (validació de la TT/DEV) I ACCEPTACIÓ
    # ==================================================================
    def _on_dev_received(self):
        """Es crida quan el departament de devolucions valida la TT/DEV."""
        for log in self:
            done_moves = log.dev_picking_id.move_lines.filtered(lambda m: m.state == 'done')
            received = {}
            for m in done_moves:
                received[m.product_id.id] = received.get(m.product_id.id, 0.0) + m.quantity_done
            problems = []
            for line in log.line_ids.filtered(lambda l: not l.ignore):
                qty = received.pop(line.product_id.id, 0.0) if line.product_id else 0.0
                line.qty_received = qty
                if qty < line.quantity:
                    problems.append(_('%s: esperadas %s, recibidas %s') % (line.sku, line.quantity, qty))
                elif qty > line.quantity:
                    problems.append(_('%s: esperadas %s, recibidas %s (de más)') % (line.sku, line.quantity, qty))
            if log.incident_note:
                problems.append(_('Nota del almacén: %s') % log.incident_note)
            extra = {k: v for k, v in received.items() if v}
            if extra and not log.config_id.return_full_order:
                names = self.env['product.product'].browse(list(extra)).mapped('display_name')
                problems.append(_('Han llegado artículos que no estaban en la devolución: %s') % ', '.join(names))
            vals = {'state': 'received', 'discrepancy': bool(problems),
                    'received_date': fields.Datetime.now()}
            if problems:
                vals.update({'issue': 'review', 'error_msg': _('Diferencias en la recepción:\n') + '\n'.join(problems)})
            else:
                vals.update({'issue': 'none', 'error_msg': False})
            log.write(vals)
            log.message_post(body=_('TT/DEV %s validada por el almacén.') % log.dev_picking_id.name)
            # L'acceptació automàtica la fa el cron: aquí som dins la validació
            # del magatzem i no es pot fer commit/rollback.

    def action_accept(self):
        """Botó de la Lorena (o cron si tot quadra):
        1) reemborsament a Shopify (Shopify calcula l'import amb descomptes)
        2) rectificativa a Odoo amb els imports que ha reemborsat Shopify."""
        for log in self.filtered(lambda l: l.state == 'received'):
            if not log._try_lock() or log.state != 'received':
                continue
            try:
                log._accept_one()
            except UserError as e:
                self.env.cr.rollback()
                msg = e.name if hasattr(e, 'name') else str(e)
                if log.shopify_refund_id:
                    msg = _('Reembolso ya hecho en Shopify (%s). Falta la rectificativa: %s') % (log.refund_amount, msg)
                log.write({'issue': 'review', 'error_msg': msg})
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception('Aceptar devolución %s', log.remarks)
                log.write({'issue': 'error', 'error_msg': str(e)})
            self.env.cr.commit()
        return True

    def _accept_one(self):
        self.ensure_one()
        if not self.shopify_refund_id:
            self._shopify_refund()
            self.env.cr.commit()   # el reemborsament ja és fet: que no es repeteixi mai
        if not self.refund_invoice_id:
            self._create_refund_invoice()
        vals = {'state': 'refunded', 'issue': 'none', 'error_msg': False,
                'closed_date': fields.Datetime.now()}
        refund = self.refund_invoice_id
        if abs(refund.amount_total - self.shopify_refunded_total) > 0.02:
            vals.update({'issue': 'review', 'error_msg': _(
                'La rectificativa (%.2f) no coincide con el reembolso de Shopify (%.2f).')
                % (refund.amount_total, self.shopify_refunded_total)})
        self.write(vals)

    def _original_invoice(self):
        invs = self.sale_id.invoice_ids.filtered(lambda i: i.type == 'out_invoice' and i.state == 'posted')
        return invs.sorted('invoice_date', reverse=True)[:1]

    @staticmethod
    def _price_excluded(gross, taxes):
        """Preu sense impostos a partir del preu amb IVA (si l'impost no és 'incluido en el precio')."""
        if not taxes or all(taxes.mapped('price_include')):
            return gross
        rate = sum(t.amount for t in taxes if t.amount_type == 'percent' and not t.price_include)
        return gross / (1 + rate / 100.0)

    def _create_refund_invoice(self):
        """Rectificativa amb el que ha reemborsat Shopify (preu amb descompte i IVA inclòs),
        enllaçada a la factura original i a les línies de venda. Sense línies de descompte
        ni ports: només els articles reemborsats."""
        sale = self.sale_id
        inv = self._original_invoice()
        if not inv:
            raise UserError(_('El pedido %s no tiene ninguna factura validada: la rectificativa se tiene que hacer a mano.') % sale.name)
        lines = self.line_ids.filtered(lambda l: l.qty_refund > 0 and l.refunded_subtotal)
        if not lines:
            raise UserError(_('No hay importes reembolsados por línea para hacer la rectificativa.'))
        inv_lines = []
        for line in lines:
            sl = sale.order_line.filtered(lambda s: s.product_id == line.product_id and not s.display_type
                                          and s.price_unit > 0)[:1]
            if not sl:
                raise UserError(_('El artículo %s no está en el pedido %s.') % (line.sku, sale.name))
            vals = sl._prepare_invoice_line()
            gross_unit = line.refunded_subtotal / line.qty_refund
            vals.update({
                'quantity': line.qty_refund,
                'discount': 0.0,
                'price_unit': self._price_excluded(gross_unit, sl.tax_id),
            })
            inv_lines.append((0, 0, vals))
        move_vals = {
            'type': 'out_refund',
            'partner_id': inv.partner_id.id,
            'partner_shipping_id': inv.partner_shipping_id.id,
            'journal_id': (self.config_id.refund_journal_id or inv.journal_id).id,
            'currency_id': inv.currency_id.id,
            'fiscal_position_id': inv.fiscal_position_id.id,
            'invoice_user_id': inv.invoice_user_id.id,
            'team_id': inv.team_id.id if 'team_id' in inv._fields else False,
            'invoice_origin': sale.name,
            'reversed_entry_id': inv.id,
            'ref': _('Devolución %s (%s)') % (self.remarks, self.shopify_return_name or ''),
            'invoice_line_ids': inv_lines,
        }
        if 'team_id' not in inv._fields:
            move_vals.pop('team_id')
        # account_ext no deixa validar sense termini i mode de pagament: els de la factura original
        if inv.invoice_payment_term_id:
            move_vals['invoice_payment_term_id'] = inv.invoice_payment_term_id.id
        if 'payment_mode_id' in inv._fields and inv.payment_mode_id:
            move_vals['payment_mode_id'] = inv.payment_mode_id.id
        refund = self.env['account.move'].with_context(default_type='out_refund').create(move_vals)
        if self.config_id.auto_post_refund:
            refund.action_post()
        self.refund_invoice_id = refund
        self.message_post(body=_('Rectificativa <a href="#" data-oe-model="account.move" data-oe-id="%d">%s</a> '
                                 'creada (%s, %.2f %s) sobre la factura %s.') % (
            refund.id, refund.name if refund.name not in (False, '/') else _('borrador'),
            _('validada') if refund.state == 'posted' else _('en borrador'),
            refund.amount_total, refund.currency_id.name or '', inv.name))

    def _shopify_refund(self):
        config = self.config_id
        lines = self.line_ids.filtered(lambda l: l.qty_refund > 0)
        if not lines:
            raise UserError(_('No ha llegado ningún artículo de la devolución: no hay nada que reembolsar.'))
        if config.simulate_shopify:
            for l in lines:
                l.refunded_subtotal = l.amount_to_refund
            total = sum(lines.mapped('refunded_subtotal'))
            self.write({'shopify_refund_id': 'TEST', 'shopify_refunded_total': total,
                        'refund_amount': '%.2f %s (simulado)' % (total, self.currency_code or 'EUR')})
            self.message_post(body=_('[SIMULACIÓN] Aquí se reembolsarían en Shopify %.2f: %s')
                              % (total, ', '.join('%s x%s' % (l.sku, l.qty_refund) for l in lines)))
            return
        if not all(l.shopify_line_id and l.shopify_order_line_id for l in lines):
            raise UserError(_('Faltan los identificadores de Shopify de las líneas.'))
        order_lines = ', '.join('{ lineItemId: "%s", quantity: %d }' % (l.shopify_order_line_id, int(l.qty_refund)) for l in lines)
        data = self._shopify_graphql(config, SUGGESTED_REFUND_QUERY % {'order': self.shopify_order_id, 'lines': order_lines})
        suggested = (data.get('order') or {}).get('suggestedRefund') or {}
        txs = []
        for t in suggested.get('suggestedTransactions') or []:
            money = t['amountSet']['shopMoney']
            txs.append('{ transactionAmount: { amount: "%s", currencyCode: %s }, parentId: "%s" }'
                       % (money['amount'], money['currencyCode'], t['parentTransaction']['id']))
        if not txs:
            raise UserError(_('Shopify no propone ninguna transacción para reembolsar.'))
        return_lines = ', '.join('{ returnLineItemId: "%s", quantity: %d }' % (l.shopify_line_id, int(l.qty_refund)) for l in lines)
        mutation = RETURN_REFUND_MUTATION % {
            'id': self.shopify_return_id, 'lines': return_lines, 'tx': ', '.join(txs),
            'notify': 'true' if config.refund_notify_customer else 'false',
        }
        result = self._shopify_graphql(config, mutation).get('returnRefund') or {}
        errors = result.get('userErrors') or []
        if errors:
            raise UserError(_('Shopify no ha hecho el reembolso: %s') % '; '.join(e.get('message', '') for e in errors))
        refund = result.get('refund') or {}
        money = ((refund.get('totalRefundedSet') or {}).get('shopMoney') or {})
        total = float(money.get('amount') or 0.0)
        self.write({'shopify_refund_id': refund.get('id') or 'OK',
                    'shopify_refunded_total': total,
                    'refund_amount': '%.2f %s' % (total, money.get('currencyCode', ''))})
        self.message_post(body=_('Reembolso hecho en Shopify: %s') % self.refund_amount)
        self._read_shopify_refund_lines()
        try:
            self._shopify_graphql(config, RETURN_CLOSE_MUTATION % {'id': self.shopify_return_id})
        except Exception as e:
            _logger.info('returnClose %s: %s', self.remarks, e)

    def _read_shopify_refund_lines(self):
        """Llegeix de Shopify l'import reemborsat per línia (ja amb descomptes)."""
        if not self.shopify_refund_id or not self.shopify_refund_id.startswith('gid://'):
            return
        data = self._shopify_graphql(self.config_id, REFUND_QUERY % {'id': self.shopify_refund_id})
        node = data.get('node') or {}
        by_line = {}
        for e in ((node.get('refundLineItems') or {}).get('edges') or []):
            n = e['node']
            lid = (n.get('lineItem') or {}).get('id')
            by_line[lid] = by_line.get(lid, 0.0) + float(n['subtotalSet']['shopMoney']['amount'])
        for line in self.line_ids:
            if line.shopify_order_line_id in by_line:
                line.refunded_subtotal = by_line[line.shopify_order_line_id]
        missing = self.line_ids.filtered(lambda l: l.qty_refund > 0 and not l.refunded_subtotal)
        if missing:
            raise UserError(_('Shopify no devuelve el importe de: %s') % ', '.join(missing.mapped('sku')))

    # ==================================================================
    # 4. CRON
    # ==================================================================
    @api.model
    def cron_process_returns(self):
        for config in self.env['shopify.return.config'].search([]):
            try:
                self._fetch_for_config(config)
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception('Devoluciones Shopify: error leyendo %s', config.name)
                continue
            if config.auto_accept_if_ok:
                self.search([
                    ('config_id', '=', config.id), ('state', '=', 'received'),
                    ('issue', '=', 'none'), ('discrepancy', '=', False),
                ]).action_accept()
            if config.auto_process and not config.simulate_shopify:
                self.search([
                    ('config_id', '=', config.id),
                    ('state', 'not in', ('done', 'received', 'refunded', 'closed', 'cancel')),
                    ('issue', '!=', 'review'),
                    ('attempts', '<', config.max_attempts),
                ]).action_process()


class ShopifyReturnCloseWizard(models.TransientModel):
    _name = 'shopify.return.close.wizard'
    _description = 'Confirmar cierre de devolución sin rectificativa'

    log_id = fields.Many2one('shopify.return.log', 'Devolución', required=True)
    message = fields.Text(compute='_compute_message')

    @api.depends('log_id')
    def _compute_message(self):
        for w in self:
            w.message = _('No se ha encontrado ninguna rectificativa para el pedido %s. '
                          '¿La has hecho? Si la cierras igualmente, quedará sin rectificativa enlazada.') % (
                w.log_id.sale_id.name or w.log_id.remarks)

    def action_force_close(self):
        self.log_id.with_context(force_close=True).action_close_manual()
        return {'type': 'ir.actions.act_window_close'}


class ShopifyReturnLogLine(models.Model):
    _name = 'shopify.return.log.line'
    _description = 'Artículo de devolución Shopify'

    log_id = fields.Many2one('shopify.return.log', 'Devolución', required=True, ondelete='cascade')
    ignore = fields.Boolean(
        'No se devuelve',
        help='El cliente pide devolver algo que no recibió (o que se gestiona aparte): '
             'no se busca en el OUT, no se espera en la TT/DEV ni se reembolsa.')
    sku = fields.Char('SKU')
    quantity = fields.Float('Esperadas')
    product_id = fields.Many2one('product.product', 'Producto')
    qty_received = fields.Float('Recibidas', readonly=True)
    qty_refund = fields.Float('A reembolsar', compute='_compute_qty_refund')
    shopify_line_id = fields.Char('ID línea devolución', readonly=True)
    shopify_order_line_id = fields.Char('ID línea pedido', readonly=True)
    return_reason = fields.Char('Motivo', readonly=True)
    customer_note = fields.Char('Nota del cliente', readonly=True)
    unit_price = fields.Float('Precio', digits=(16, 2), readonly=True)
    unit_discount = fields.Float('Descuento/u.', digits=(16, 2), readonly=True)
    amount_expected = fields.Float('Importe solicitado', compute='_compute_line_amounts', digits=(16, 2))
    amount_to_refund = fields.Float('Importe a reembolsar', compute='_compute_line_amounts', digits=(16, 2))
    refunded_subtotal = fields.Float('Reembolsado (Shopify)', digits=(16, 2), readonly=True, copy=False)

    @api.depends('unit_price', 'unit_discount', 'quantity', 'qty_received', 'ignore')
    def _compute_line_amounts(self):
        for line in self:
            net = 0.0 if line.ignore else (line.unit_price or 0.0) - (line.unit_discount or 0.0)
            line.amount_expected = net * line.quantity
            line.amount_to_refund = net * min(line.quantity, line.qty_received)

    @api.depends('quantity', 'qty_received', 'ignore')
    def _compute_qty_refund(self):
        for line in self:
            line.qty_refund = 0.0 if line.ignore else min(line.quantity, line.qty_received)
