import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class ExchangePlan(models.Model):
    _name = 'nath.exchange.plan'
    _description = 'Facturación controlada de cambios y salidas manuales'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char('Referencia', required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    sale_id = fields.Many2one('sale.order', string='Pedido (si existe)')
    partner_id = fields.Many2one('res.partner', string='Cliente de facturación', required=True)
    currency_id = fields.Many2one('res.currency', required=True, default=lambda s: s.env.company.currency_id)
    journal_id = fields.Many2one('account.journal', string='Diario', required=True,
                                 domain="[('type','=','sale'),('company_id','=',company_id)]")
    original_invoice_id = fields.Many2one('account.move', string='Factura original (para rectificativa)',
                                          domain="[('type','=','out_invoice'),('state','=','posted'),('company_id','=',company_id)]")
    picking_ids = fields.Many2many('stock.picking', string='Albaranes del cambio / salida manual',
                                   domain="[('company_id','=',company_id),('state','=','done')]")
    line_ids = fields.One2many('nath.exchange.line', 'plan_id', string='Cobertura por movimiento')
    state = fields.Selection([('draft', 'Preparación'), ('prepared', 'Revisión'),
                              ('done', 'Documentos preparados')], default='draft', readonly=True, tracking=True)
    checked = fields.Boolean('He revisado facturas existentes, precios netos, descuentos e impuestos')
    preview = fields.Text('Previsualización', readonly=True)
    review_snapshot = fields.Text(readonly=True, copy=False)
    document_inventory = fields.Text('Documentos existentes del cliente', readonly=True)
    invoice_ids = fields.One2many('account.move', 'nath_exchange_plan_id', string='Documentos generados')

    def write(self, vals):
        header = {'company_id', 'sale_id', 'partner_id', 'currency_id', 'journal_id',
                  'original_invoice_id', 'picking_ids', 'name'}
        if header.intersection(vals) and any(p.state != 'draft' for p in self):
            raise UserError(_('La cabecera preparada no se modifica. Crear un expediente correcto antes de preparar.'))
        return super().write(vals)

    def _access(self):
        self.ensure_one()
        self.check_access_rights('write')
        self.check_access_rule('write')
        if not self.env.user.has_group('nath_exchange_billing.group_exchange_billing'):
            raise UserError(_('Se requiere el grupo Facturación de cambios: revisión.'))
        if self.company_id not in self.env.companies:
            raise UserError(_('Selecciona la compañía del expediente.'))

    def _lock(self):
        # Lock order first, shared with the standard-invoicing guard.
        if self.sale_id:
            self.env.cr.execute('SELECT id FROM sale_order WHERE id = %s FOR UPDATE', (self.sale_id.id,))
            self.sale_id.invalidate_cache()
        self.env.cr.execute('SELECT id FROM nath_exchange_plan WHERE id = %s FOR UPDATE', (self.id,))
        self.invalidate_cache()

    def _validate_header(self):
        if self.journal_id.company_id != self.company_id or self.journal_id.type != 'sale':
            raise UserError(_('Diario de venta incompatible.'))
        if self.sale_id and (self.sale_id.company_id != self.company_id or
                self.sale_id.partner_invoice_id.commercial_partner_id != self.partner_id.commercial_partner_id or
                self.sale_id.currency_id != self.currency_id):
            raise UserError(_('Pedido, cliente, moneda o compañía incompatibles.'))
        if self.journal_id.currency_id and self.journal_id.currency_id != self.currency_id:
            raise UserError(_('Moneda del diario incompatible.'))
        if self.original_invoice_id:
            inv = self.original_invoice_id
            if (inv.company_id != self.company_id or inv.type != 'out_invoice' or inv.state != 'posted' or
                    inv.commercial_partner_id != self.partner_id.commercial_partner_id or
                    inv.currency_id != self.currency_id):
                raise UserError(_('Factura original incompatible.'))

    def action_prepare(self):
        self._access()
        self._lock()
        if self.state != 'draft':
            raise UserError(_('El expediente ya está preparado; no se regeneran sus líneas.'))
        self._validate_header()
        if not self.picking_ids:
            raise UserError(_('Selecciona los albaranes concretos, excluyendo la salida original ya facturada.'))
        moves = self.env['stock.move']
        for picking in self.picking_ids:
            if picking.state != 'done' or picking.company_id != self.company_id:
                raise UserError(_('Solo se admiten albaranes hechos de esta compañía.'))
            if picking.partner_id.commercial_partner_id != self.partner_id.commercial_partner_id:
                raise UserError(_('El cliente del albarán no coincide con el expediente.'))
            linked_orders = picking.move_lines.mapped('sale_line_id.order_id')
            if linked_orders and (not self.sale_id or any(o != self.sale_id for o in linked_orders)):
                raise UserError(_('Los movimientos tienen pedido de venta: selecciona ese mismo pedido '
                                  'para proteger su facturación. No se mezclan pedidos.'))
            if picking.picking_type_id.code not in ('incoming', 'outgoing'):
                raise UserError(_('No se facturan transferencias internas.'))
            moves |= picking.move_lines.filtered(lambda m: m.state == 'done' and m.quantity_done > 0)
        if not moves:
            raise UserError(_('No hay cantidades hechas.'))
        self.env.cr.execute('SELECT id FROM stock_move WHERE id IN %s ORDER BY id FOR UPDATE', (tuple(moves.ids),))
        if self.env['nath.exchange.line'].search_count([('stock_move_id', 'in', moves.ids)]):
            raise UserError(_('Algún movimiento ya pertenece a otro expediente. Abrir el existente.'))
        for move in moves:
            incoming = move.picking_id.picking_type_id.code == 'incoming'
            if incoming and not move.origin_returned_move_id:
                raise UserError(_('La entrada debe tener movimiento de devolución original.'))
            if incoming and not self.original_invoice_id:
                raise UserError(_('Selecciona la factura original para la devolución.'))
            # Conservative detection: do not equate a wrongly inherited sale line
            # with billing of the replacement product.
            matches = move.sale_line_id.invoice_lines.filtered(lambda l:
                l.move_id.state != 'cancel' and l.product_id == move.product_id and
                l.move_id.type == ('out_refund' if incoming else 'out_invoice'))
            self.env['nath.exchange.line'].create({
                'plan_id': self.id, 'stock_move_id': move.id,
                'quantity': move.quantity_done,
                'kind': 'out_refund' if incoming else 'out_invoice',
                'existing_candidates': ', '.join(matches.mapped('move_id.name')) or False,
            })
        if self.sale_id:
            self.sale_id.nath_exchange_hold = True
        self.write({'state': 'prepared', 'checked': False})
        self.message_post(body=_('Expediente preparado. No se han creado facturas ni reembolsos. '
                                 'Si hay pedido vinculado, su facturación ordinaria queda bloqueada.'))

    def _snapshot(self):
        # Any invoice added/edited since preview invalidates the review, even
        # if it was manually created without sale-line or stock-move links.
        documents = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('commercial_partner_id', '=', self.partner_id.commercial_partner_id.id),
            ('type', 'in', ('out_invoice', 'out_refund'))], order='id')
        return json.dumps([self.company_id.id, self.sale_id.id, self.partner_id.id,
            self.currency_id.id, self.journal_id.id, self.original_invoice_id.id, self.picking_ids.ids,
            [(d.id, str(d.write_date), d.state,
              [(l.id, str(l.write_date)) for l in d.invoice_line_ids]) for d in documents],
            [(l.id, l.stock_move_id.id, l.stock_move_id.state, l.stock_move_id.quantity_done,
              l.quantity, l.kind, l.price_unit, l.account_id.id, l.tax_ids.ids,
              l.existing_line_id.id, l.existing_line_id.move_id.state,
              l.existing_line_id.quantity) for l in self.line_ids.sorted('id')]], sort_keys=True)

    def _validate_lines(self):
        if not self.line_ids:
            raise UserError(_('Faltan líneas.'))
        for line in self.line_ids:
            move = line.stock_move_id
            if (move.state != 'done' or move.company_id != self.company_id or
                    move.picking_id not in self.picking_ids or
                    line.kind != ('out_refund' if move.picking_id.picking_type_id.code == 'incoming' else 'out_invoice') or
                    float_compare(line.quantity, move.quantity_done,
                                  precision_rounding=move.product_uom.rounding) != 0):
                raise UserError(_('Las cantidades o los movimientos han cambiado; revisar.'))
            if line.kind == 'out_refund' and (not self.original_invoice_id or not move.origin_returned_move_id):
                raise UserError(_('Falta la factura o el movimiento original de la devolución.'))
            if line.kind == 'out_refund' and not self.original_invoice_id.invoice_line_ids.filtered(
                    lambda l: l.product_id == move.product_id):
                raise UserError(_('El artículo devuelto no aparece en la factura original seleccionada.'))
            if line.existing_line_id:
                line._validate_existing()
            else:
                candidates = move.sale_line_id.invoice_lines.filtered(lambda l:
                    l.move_id.state != 'cancel' and l.product_id == move.product_id and l.move_id.type == line.kind)
                if line.existing_candidates or candidates:
                    raise UserError(_('Hay documentos candidatos. Vincula la línea existente o revisa el caso fuera del piloto.'))
                if not line.account_id or line.account_id.company_id != self.company_id or line.account_id.deprecated:
                    raise UserError(_('Selecciona una cuenta contable válida de la compañía en cada línea nueva.'))
                if line.price_unit < 0:
                    raise UserError(_('Introduce precio neto no negativo; el tipo de documento determina el signo.'))
                if any(t.company_id != self.company_id or t.type_tax_use != 'sale' for t in line.tax_ids):
                    raise UserError(_('Impuestos incompatibles.'))

    def action_preview(self):
        self._access()
        self._validate_header()
        self._validate_lines()
        if self.state != 'prepared':
            raise UserError(_('Primero prepara el expediente.'))
        text = [_('Solo borradores Odoo. Sin validación, conciliación, pagos ni llamadas a Shopify.')]
        for line in self.line_ids:
            action = ('EXISTENTE: %s' % line.existing_line_id.move_id.display_name if line.existing_line_id
                      else 'NUEVO BORRADOR: %s; precio neto/u. %s; impuestos %s' %
                      (line.kind, line.price_unit, ', '.join(line.tax_ids.mapped('name'))))
            text.append('%s | %s | %s %s | %s' % (line.stock_move_id.picking_id.name,
                line.product_id.display_name, line.quantity, line.stock_move_id.product_uom.name, action))
        documents = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id),
            ('commercial_partner_id', '=', self.partner_id.commercial_partner_id.id),
            ('type', 'in', ('out_invoice', 'out_refund')), ('state', '!=', 'cancel')], order='id')
        inventory = '\n'.join('%s | %s | %s | %s | %s' %
            (d.display_name, d.type, d.state, d.invoice_origin or '', d.amount_total) for d in documents)
        self.write({'preview': '\n'.join(text), 'document_inventory': inventory,
                    'review_snapshot': self._snapshot(), 'checked': False})

    def action_create_drafts(self):
        self._access()
        self._lock()
        if self.state == 'done':
            return self.action_open_documents()
        self._validate_header()
        self._validate_lines()
        if self.state != 'prepared' or not self.checked or self.review_snapshot != self._snapshot():
            raise UserError(_('Previsualiza de nuevo y confirma la revisión de precios y documentos existentes.'))
        if self.sale_id and not self.sale_id.nath_exchange_hold:
            raise UserError(_('El pedido debe conservar el bloqueo de facturación ordinaria.'))
        if self.invoice_ids:
            raise UserError(_('Ya hay documentos generados; no se repite la creación.'))
        # Group by picking and document type: two manual OUTs have their own
        # invoices; the return has a separate credit note.
        pending = self.line_ids.filtered(lambda l: not l.existing_line_id)
        for picking in pending.mapped('stock_move_id.picking_id').sorted('id'):
            items = pending.filtered(lambda l: l.stock_move_id.picking_id == picking)
            kind = items[0].kind
            vals = {
                'type': kind, 'company_id': self.company_id.id,
                'partner_id': self.partner_id.id, 'journal_id': self.journal_id.id,
                'currency_id': self.currency_id.id, 'invoice_date': fields.Date.context_today(self),
                'invoice_origin': '%s / %s' % (self.name, picking.name),
                'ref': self.name, 'nath_exchange_plan_id': self.id,
                'invoice_line_ids': [(0, 0, {
                    'product_id': l.product_id.id, 'name': l.product_id.display_name,
                    'quantity': l.quantity, 'product_uom_id': l.stock_move_id.product_uom.id,
                    'price_unit': l.price_unit, 'account_id': l.account_id.id,
                    'tax_ids': [(6, 0, l.tax_ids.ids)], 'nath_exchange_line_id': l.id,
                }) for l in items],
            }
            if self.sale_id:
                vals['fiscal_position_id'] = self.sale_id.fiscal_position_id.id
                vals['invoice_payment_term_id'] = self.sale_id.payment_term_id.id
                if 'payment_mode_id' in self.sale_id._fields and 'payment_mode_id' in self.env['account.move']._fields:
                    vals['payment_mode_id'] = self.sale_id.payment_mode_id.id
            if kind == 'out_refund':
                vals['reversed_entry_id'] = self.original_invoice_id.id
            invoice = self.env['account.move'].with_context(default_type=kind, force_company=self.company_id.id).create(vals)
            for item in items:
                item.existing_line_id = invoice.invoice_line_ids.filtered(lambda l: l.nath_exchange_line_id == item)
        self.state = 'done'
        self.message_post(body=_('Documentos preparados en borrador. No se han validado ni conciliado. '
                                 'No se ha realizado ningún reembolso Shopify.'))
        return self.action_open_documents()

    def action_open_documents(self):
        self.check_access_rights('read')
        self.check_access_rule('read')
        return {'type': 'ir.actions.act_window', 'name': _('Documentos del cambio'),
                'res_model': 'account.move', 'view_mode': 'tree,form',
                'domain': [('id', 'in', self.line_ids.mapped('existing_line_id.move_id').ids)]}


class ExchangeLine(models.Model):
    _name = 'nath.exchange.line'
    _description = 'Cobertura de facturación por movimiento'

    plan_id = fields.Many2one('nath.exchange.plan', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    stock_move_id = fields.Many2one('stock.move', required=True, ondelete='restrict')
    product_id = fields.Many2one(related='stock_move_id.product_id')
    quantity = fields.Float('Cantidad', required=True)
    kind = fields.Selection([('out_invoice', 'Factura'), ('out_refund', 'Rectificativa')], required=True)
    price_unit = fields.Float('Precio neto/u. (en UdM del movimiento)', digits='Product Price')
    account_id = fields.Many2one('account.account', string='Cuenta')
    tax_ids = fields.Many2many('account.tax', string='Impuestos')
    existing_candidates = fields.Char('Documentos candidatos', readonly=True)
    existing_line_id = fields.Many2one('account.move.line', string='Línea ya facturada / generada', ondelete='restrict')

    _sql_constraints = [
        ('move_unique', 'unique(stock_move_id)', 'Este movimiento ya tiene cobertura en otro expediente.'),
        ('invoice_line_unique', 'unique(existing_line_id)', 'Esta línea contable ya cubre otro movimiento.'),
    ]

    def _validate_existing(self):
        self.ensure_one()
        line = self.existing_line_id
        plan = self.plan_id
        if not line.product_uom_id:
            raise UserError(_('La línea existente no tiene unidad de medida de producto.'))
        qty = line.product_uom_id._compute_quantity(line.quantity, self.stock_move_id.product_uom)
        if (line.move_id.state == 'cancel' or line.move_id.type != self.kind or
                line.company_id != self.company_id or line.product_id != self.product_id or
                line.move_id.commercial_partner_id != plan.partner_id.commercial_partner_id or
                line.move_id.currency_id != plan.currency_id or
                float_compare(qty, self.quantity, precision_rounding=self.stock_move_id.product_uom.rounding) != 0):
            raise UserError(_('La línea existente no coincide con producto, cantidad, cliente, moneda o tipo. '
                              'La cobertura parcial o agrupada requiere revisión fuera del piloto.'))

    def write(self, vals):
        if any(l.plan_id.state == 'done' for l in self):
            raise UserError(_('La cobertura ya finalizada no se modifica.'))
        if {'plan_id', 'stock_move_id', 'quantity', 'kind'}.intersection(vals):
            raise UserError(_('No se modifica la identidad o cantidad del movimiento preparado.'))
        return super().write(vals)

    def unlink(self):
        raise UserError(_('No se elimina la cobertura; evita duplicar facturas.'))


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    nath_exchange_hold = fields.Boolean('Facturación controlada de cambio / manual', copy=False,
        help='Bloquea facturación ordinaria y reembolso del módulo de devoluciones Shopify. '
             'No modifica el estado de la comanda ni Shopify.')

    def write(self, vals):
        if 'nath_exchange_hold' in vals:
            if not self.env.user.has_group('nath_exchange_billing.group_exchange_billing'):
                raise UserError(_('Solo el grupo de revisión puede cambiar la protección contable.'))
            if not vals['nath_exchange_hold'] and self.env['nath.exchange.plan'].search_count([
                    ('sale_id', 'in', self.ids), ('state', '!=', 'draft')]):
                raise UserError(_('Hay un expediente preparado. Mantener la protección para evitar refacturación.'))
        return super().write(vals)

    def _create_invoices(self, grouped=False, final=False):
        if self:
            self.env.cr.execute('SELECT id FROM sale_order WHERE id IN %s ORDER BY id FOR UPDATE', (tuple(self.ids),))
            self.invalidate_cache(['nath_exchange_hold'])
        if any(self.mapped('nath_exchange_hold')):
            raise UserError(_('Pedido gestionado por facturación de cambios. Abrir su expediente para evitar duplicados.'))
        return super()._create_invoices(grouped=grouped, final=final)


class AccountMove(models.Model):
    _inherit = 'account.move'

    nath_exchange_plan_id = fields.Many2one('nath.exchange.plan', copy=False, ondelete='restrict')


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    nath_exchange_line_id = fields.Many2one('nath.exchange.line', copy=False, ondelete='restrict')

    _sql_constraints = [('exchange_coverage_unique', 'unique(nath_exchange_line_id)',
                         'Ya existe una línea contable para este movimiento de cambio.')]

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        orders = lines.mapped('sale_line_ids.order_id')
        if orders:
            self.env.cr.execute('SELECT id FROM sale_order WHERE id IN %s ORDER BY id FOR UPDATE', (tuple(orders.ids),))
            orders.invalidate_cache(['nath_exchange_hold'])
            if any(orders.mapped('nath_exchange_hold')):
                raise UserError(_('No se añaden líneas contables por el circuito ordinario a un pedido '
                                  'protegido. Utiliza el expediente de cambios.'))
        return lines


class ShopifyReturn(models.Model):
    _inherit = 'shopify.return.log'

    def _exchange_refund_guard(self):
        self.ensure_one()
        if self.sale_id:
            self.env.cr.execute('SELECT id FROM sale_order WHERE id = %s FOR UPDATE', (self.sale_id.id,))
            self.sale_id.invalidate_cache(['nath_exchange_hold'])
        if self.sale_id.nath_exchange_hold:
            raise UserError(_('Cambio con facturación controlada: reembolso Shopify bloqueado.'))

    def _shopify_refund(self):
        self._exchange_refund_guard()
        return super()._shopify_refund()

    def _accept_one(self):
        self._exchange_refund_guard()
        return super()._accept_one()
