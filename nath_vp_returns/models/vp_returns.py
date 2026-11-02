import json
import logging
from datetime import datetime
from urllib.parse import urlsplit

import pytz
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MADRID = pytz.timezone('Europe/Madrid')
PAGE_SIZE = 50
OPEN_STATES = ('pending', 'validated', 'review')
IN_PROGRESS = ('dev_created', 'label', 'notified', 'accepted')


class VPReturnConfig(models.Model):
    _name = 'vp.return.config'
    _description = 'Configuración devoluciones VP'

    name = fields.Char(required=True)
    connection_id = fields.Many2one('pink.connect.channel.configuration', required=True)
    company_id = fields.Many2one(related='connection_id.company_id', store=True)
    order_id_filter = fields.Char('ID pedido PinkConnect (una comanda)',
                                  help='Solo para «Leer API (solo lectura)» de una comanda concreta.')
    sample_response = fields.Text('Respuesta de ejemplo (JSON)')
    last_response = fields.Text('Última respuesta API', readonly=True)
    last_read = fields.Datetime('Última lectura', readonly=True)

    # Circuit: llegir les PENDING i crear la TT/DEV
    auto_fetch = fields.Boolean(
        'Leer pendientes automáticamente',
        help='El cron lee de PinkConnect todas las solicitudes PENDING y crea/actualiza las devoluciones.')
    auto_create_dev = fields.Boolean(
        'Crear TT/DEV automáticamente',
        help='Desmarcado: las devoluciones se validan y alguien crea la TT/DEV con el botón.')
    simulate = fields.Boolean(
        'Simular (no crea nada)', default=True,
        help='No crea TT/DEV, transporte ni mensaje, ni acepta en VP: escribe en el chat lo que haría.')
    return_full_order = fields.Boolean(
        'TT/DEV con todo el pedido', default=True,
        help='Marcado: como se hace ahora a mano (todas las líneas del OUT); el almacén valida solo lo '
             'que llega y anula el resto, y la rectificativa de PinkConnect sale solo de lo validado. '
             'Desmarcado: solo los artículos que pide VP.')
    return_location_id = fields.Many2one(
        'stock.location', 'Ubicación de devolución',
        help='p. ej. WH-OR/Stock/DEVOLUCION_ONLINE')
    max_pages = fields.Integer('Máximo de páginas por lectura', default=10,
                               help='%s solicitudes por página.' % PAGE_SIZE)
    last_fetch = fields.Datetime('Última lectura de pendientes', readonly=True)
    last_fetch_result = fields.Text('Resultado de la última lectura', readonly=True)

    def _check_access(self, need_order=True):
        self.ensure_one()
        self.check_access_rights('write')
        self.check_access_rule('write')
        if not self.env.user.has_group('nath_vp_returns.group_vp_manager') and not self.env.su:
            raise UserError(_('Se requiere el grupo Devoluciones VP: configuración.'))
        if self.company_id not in self.env.companies and not self.env.su:
            raise UserError(_('La compañía no está seleccionada.'))
        if need_order and not (self.order_id_filter or '').strip().isdigit():
            raise UserError(_('Introduce el ID numérico interno del pedido PinkConnect.'))

    def _pink_base(self):
        """URL base i capçaleres de la connexió PinkConnect (només l'API oficial HTTPS v4)."""
        connection = self.connection_id
        parts = urlsplit(connection.url or '')
        if (parts.scheme != 'https' or parts.netloc not in
                ('api.pink-connect.com', 'api-pinkstaging.pink-connect.com') or
                parts.path.rstrip('/') != '/v4' or parts.query or parts.fragment):
            raise UserError(_('La URL debe ser la API oficial HTTPS v4 de PinkConnect.'))
        if not connection.api_key:
            raise UserError(_('Falta la clave en la conexión PinkConnect.'))
        return connection.url.rstrip('/'), {'Authorization': 'Bearer ' + connection.api_key,
                                            'Accept': 'application/json'}

    def _api_get(self, params):
        """Un sol GET a /return-requests, sense reintents ni redireccions. Mai modifica PinkConnect."""
        base, headers = self._pink_base()
        try:
            response = requests.get(
                base + '/return-requests', headers=headers,
                params=params, timeout=(10, 45), allow_redirects=False)
        except requests.RequestException:
            raise UserError(_('No se ha podido leer PinkConnect. No se ha modificado la plataforma.'))
        if response.status_code != 200:
            raise UserError(_('PinkConnect ha respondido HTTP %s.') % response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise UserError(_('PinkConnect no ha devuelto JSON.'))
        if not isinstance(data, list):
            raise UserError(_('PinkConnect no ha devuelto una lista: %s') % str(data)[:300])
        return data

    def action_read(self):
        self._check_access()
        data = self._api_get({'orderId': self.order_id_filter.strip(), 'limit': PAGE_SIZE})
        self.write({'last_response': json.dumps(data, ensure_ascii=False, indent=2),
                    'last_read': fields.Datetime.now()})
        return self._open_config()

    # ------------------------------------------------------------------
    def action_fetch_pending(self):
        self._check_access(need_order=False)
        self._fetch_pending()
        return {'type': 'ir.actions.act_window', 'name': _('Devoluciones VP'),
                'res_model': 'vp.return', 'view_mode': 'tree,form',
                'domain': [('config_id', '=', self.id)]}

    def _fetch_pending(self):
        """Llegeix totes les PENDING (per pàgines), les guarda i les agrupa per comanda.
        Després rellegeix les comandes obertes que ja no surten com a PENDING."""
        self.ensure_one()
        rows, seen, notes = [], set(), []
        complete = False
        for page in range(max(self.max_pages, 1)):
            data = self._api_get({'status': 'PENDING', 'limit': PAGE_SIZE, 'offset': page * PAGE_SIZE})
            new = [r for r in data if isinstance(r, dict) and r.get('returnRequestId') not in seen]
            if data and not new:
                # L'API ha tornat la mateixa pàgina: no pagina amb 'offset'
                notes.append(_('La paginación no avanza: solo se ha leído la primera página.'))
                break
            for r in new:
                seen.add(r.get('returnRequestId'))
            rows += new
            if len(data) < PAGE_SIZE:
                complete = True
                break
        else:
            notes.append(_('Se ha llegado al máximo de %s páginas.') % self.max_pages)
        requests_ = self._upsert_rows(rows)
        returns = self._group_requests()
        refreshed = self._refresh_open(seen) if complete else 0
        result = _('%s solicitudes PENDING leídas, %s devoluciones nuevas o actualizadas, '
                   '%s comandas releídas.') % (len(rows), len(returns), refreshed)
        self.write({'last_fetch': fields.Datetime.now(),
                    'last_fetch_result': '\n'.join([result] + notes)})
        returns.filtered(lambda r: r.state == 'pending')._validate_all()
        return requests_

    def _refresh_open(self, pending_ids):
        """Les sol·licituds que tenim com a PENDING però ja no hi surten (p. ex. la Lorena les ha
        acceptades a VP): es rellegeix la comanda per tenir l'estat bo. Com a molt 20 per lectura."""
        stale = self.env['vp.return.request'].search([
            ('config_id', '=', self.id), ('simulated', '=', False),
            ('remote_status', '=', 'PENDING'), ('remote_id', 'not in', list(pending_ids))])
        orders = list(dict.fromkeys(stale.mapped('order_id')))[:20]
        for order in orders:
            self._upsert_rows(self._api_get({'orderId': order, 'limit': PAGE_SIZE}))
        return len(orders)

    def _upsert_rows(self, rows, simulated=False):
        Request = self.env['vp.return.request']
        result = Request
        for row in rows:
            if not isinstance(row, dict) or not all(row.get(k) for k in ('returnRequestId', 'orderId', 'status')):
                _logger.warning('VP: solicitud sin returnRequestId/orderId/status: %s', row)
                continue
            vals = {'remote_status': str(row['status']),
                    'order_line_id': str(row.get('orderLineId') or ''),
                    'marketplace_return_id': row.get('marketplaceReturnId') or False,
                    'marketplace_order_number': row.get('marketplaceOrderNumber') or False,
                    'sku': row.get('sku') or False,
                    'gtin': row.get('gtin') or False,
                    'quantity': float(row.get('quantity') or 1),
                    'return_type': row.get('type') or False,
                    'reason': row.get('reason') or False,
                    'payload': json.dumps(row, ensure_ascii=False, indent=2)}
            existing = Request.search([('config_id', '=', self.id),
                                       ('remote_id', '=', str(row['returnRequestId'])),
                                       ('simulated', '=', simulated)])
            if existing:
                existing.write(vals)
                result |= existing
                continue
            vals.update({'config_id': self.id, 'remote_id': str(row['returnRequestId']),
                         'order_id': str(row['orderId']), 'simulated': simulated,
                         'sale_id': self._sale_for(str(row['orderId'])).id})
            result |= Request.create(vals)
        return result

    def _sale_for(self, order_id):
        feeds = self.env['pink.connect.order.feed'].search([
            ('pink_connect_id', '=', self.connection_id.id), ('order_id', '=', order_id)])
        sale = feeds.sale_order_id if len(feeds) == 1 else self.env['sale.order']
        return sale if len(sale) == 1 and sale.company_id == self.company_id else self.env['sale.order']

    def _group_requests(self):
        """Cada sol·licitud sense devolució va a la devolució oberta de la seva comanda
        (o se'n crea una). Les de prova no s'agrupen."""
        Return = self.env['vp.return']
        touched = Return
        orphans = self.env['vp.return.request'].search([
            ('config_id', '=', self.id), ('return_id', '=', False), ('simulated', '=', False)])
        for order_id in dict.fromkeys(orphans.mapped('order_id')):
            reqs = orphans.filtered(lambda r: r.order_id == order_id)
            ret = Return.search([('config_id', '=', self.id), ('order_id', '=', order_id),
                                 ('state', 'in', OPEN_STATES + IN_PROGRESS)], limit=1)
            if not ret:
                ret = Return.create({'config_id': self.id, 'order_id': order_id,
                                     'sale_id': reqs.mapped('sale_id')[:1].id})
            elif ret.state in IN_PROGRESS:
                # La TT/DEV ja hi és (amb tota la comanda normalment): només s'avisa
                ret.message_post(body=_('Nuevas solicitudes de VP (%s) para una devolución que ya tiene '
                                        'la TT/DEV %s: revisar si están incluidas.')
                                 % (', '.join(reqs.mapped('display_name')), ret.dev_picking_id.name))
            reqs.write({'return_id': ret.id})
            touched |= ret
        return touched

    @api.model
    def cron_run(self):
        for config in self.search([('auto_fetch', '=', True)]):
            try:
                config._fetch_pending()
                self.env.cr.commit()
                if config.auto_create_dev and not config.simulate:
                    self.env['vp.return'].search([
                        ('config_id', '=', config.id), ('state', '=', 'validated'),
                        ('dev_picking_id', '=', False)]).action_process()
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception('Devoluciones VP: %s', config.name)
                config.write({'last_fetch': fields.Datetime.now(), 'last_fetch_result': 'ERROR: %s' % e})
            self.env.cr.commit()

    def _open_config(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name,
                'res_id': self.id, 'view_mode': 'form', 'target': 'current'}

    def action_import_sample(self):
        self._check_access()
        return self._import_response(self.sample_response, simulated=True)

    def action_import_response(self):
        self._check_access()
        return self._import_response(self.last_response, simulated=False)

    def _import_response(self, raw, simulated):
        try:
            data = json.loads(raw or '')
        except ValueError:
            raise UserError(_('Introduce una respuesta JSON válida.'))
        # Do not guess wrapper names or silently discard unknown fields.
        if not isinstance(data, list):
            raise UserError(_('Este piloto espera una lista JSON. Conserva la respuesta '
                              'para adaptar el formato real antes de importar.'))
        if len(data) > PAGE_SIZE:
            raise UserError(_('Máximo %s líneas por prueba.') % PAGE_SIZE)
        for row in data:
            if not isinstance(row, dict) or not all(row.get(k) for k in ('returnRequestId', 'orderId', 'status')):
                raise UserError(_('Faltan returnRequestId, orderId o status. No se importa la respuesta.'))
            if str(row['orderId']) != self.order_id_filter.strip():
                raise UserError(_('La respuesta contiene otra comanda; no se importa.'))
        self._upsert_rows(data, simulated=simulated)
        if not simulated:
            self._group_requests()
        return {'type': 'ir.actions.act_window', 'name': _('Solicitudes VP'),
                'res_model': 'vp.return.request', 'view_mode': 'tree,form',
                'domain': [('config_id', '=', self.id)]}


class VPReturnRequest(models.Model):
    _name = 'vp.return.request'
    _description = 'Solicitud de devolución VP'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'id desc'

    name = fields.Char('Solicitud', compute='_compute_name', store=True)
    product_id = fields.Many2one('product.product', 'Producto', compute='_compute_product', store=True)
    partner_id = fields.Many2one(related='sale_id.partner_id', string='Cliente', store=True)
    country_id = fields.Many2one(related='sale_id.partner_shipping_id.country_id', string='País', store=True)
    request_date = fields.Datetime('Fecha', compute='_compute_request_date', store=True)
    config_id = fields.Many2one('vp.return.config', required=True, ondelete='restrict')
    return_id = fields.Many2one('vp.return', 'Devolución', ondelete='set null', index=True)
    quantity = fields.Float('Cantidad', default=1, readonly=True)
    company_id = fields.Many2one(related='config_id.company_id', store=True)
    remote_id = fields.Char('ID solicitud', required=True, readonly=True)
    order_id = fields.Char('ID pedido PinkConnect', required=True, readonly=True)
    remote_status = fields.Char('Estado leído de VP', readonly=True)
    order_line_id = fields.Char('ID línea de pedido VP', readonly=True)
    marketplace_return_id = fields.Char('ID devolución marketplace', readonly=True)
    marketplace_order_number = fields.Char('Referencia marketplace', readonly=True)
    sku = fields.Char('SKU', readonly=True)
    gtin = fields.Char('GTIN', readonly=True)
    return_type = fields.Char('Tipo original VP', readonly=True)
    reason = fields.Char('Motivo', readonly=True)
    simulated = fields.Boolean('Datos de prueba', readonly=True)
    sale_id = fields.Many2one('sale.order', string='Pedido Odoo', readonly=True)
    payload = fields.Text('JSON original', readonly=True)
    preview = fields.Text('Previsualización', readonly=True)

    _sql_constraints = [('request_unique', 'unique(config_id, remote_id, simulated)',
                         'Esta solicitud ya está importada en esta configuración.')]

    @api.depends('gtin', 'sku')
    def _compute_product(self):
        # El GTIN sempre porta l'EAN; el SKU de vegades és l'EAN i de vegades la referència.
        Product = self.env['product.product'].with_context(active_test=False)
        for rec in self:
            product = Product
            for code in filter(None, (rec.gtin, rec.sku)):
                product = Product.search([('barcode', '=', code)], limit=1) or \
                    Product.search([('default_code', '=', code)], limit=1)
                if product:
                    break
            rec.product_id = product

    @api.depends('payload')
    def _compute_request_date(self):
        # PinkConnect envia «29/10/2026 10:35:06» en hora local; Odoo la guarda en UTC.
        for rec in self:
            rec.request_date = False
            try:
                raw = (json.loads(rec.payload or '{}').get('requestDate') or '').strip()
            except ValueError:
                continue
            for fmt in ('%d/%m/%Y %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
                try:
                    local = MADRID.localize(datetime.strptime(raw[:19], fmt))
                except ValueError:
                    continue
                rec.request_date = local.astimezone(pytz.utc).replace(tzinfo=None)
                break

    @api.depends('sale_id', 'order_id', 'partner_id')
    def _compute_name(self):
        # Com a Shopify: comanda i clienta, sense l'ID tècnic de la sol·licitud.
        for rec in self:
            order = rec.sale_id.name or rec.order_id
            rec.name = ' · '.join(filter(None, (order, rec.partner_id.name))) or rec.remote_id


class VPReturn(models.Model):
    """Una devolució VP = una comanda de PinkConnect amb les seves sol·licituds (una per peça)."""
    _name = 'vp.return'
    _description = 'Devolución VP'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char('Devolución', compute='_compute_name', store=True)
    config_id = fields.Many2one('vp.return.config', required=True, ondelete='restrict', readonly=True)
    company_id = fields.Many2one(related='config_id.company_id', store=True)
    order_id = fields.Char('ID pedido PinkConnect', required=True, readonly=True, index=True)
    sale_id = fields.Many2one('sale.order', 'Pedido Odoo', readonly=True)
    partner_id = fields.Many2one(related='sale_id.partner_id', string='Cliente', store=True)
    country_id = fields.Many2one(related='sale_id.partner_shipping_id.country_id', string='País', store=True)
    request_ids = fields.One2many('vp.return.request', 'return_id', 'Artículos')
    request_date = fields.Datetime('Fecha', compute='_compute_summary', store=True)
    n_items = fields.Float('Artículos VP', compute='_compute_summary', store=True)
    remote_status = fields.Char('Estado VP', compute='_compute_summary', store=True)
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('validated', 'Validada'),
        ('dev_created', 'TT/DEV creada'),
        ('label', 'Etiqueta creada'),
        ('notified', 'Mensaje enviado'),
        ('accepted', 'Aceptada en VP'),
        ('received', 'Recibida'),
        ('review', 'Revisar'),
        ('cancel', 'Cancelada'),
    ], default='pending', required=True, readonly=True, tracking=True)
    error_msg = fields.Text('Incidencia', readonly=True)
    out_picking_ids = fields.Many2many('stock.picking', 'vp_return_out_rel', 'return_id', 'picking_id',
                                       string='OUT', readonly=True)
    dev_picking_id = fields.Many2one('stock.picking', 'TT/DEV', readonly=True)
    dev_state = fields.Selection(related='dev_picking_id.state', string='Estado TT/DEV')
    preview = fields.Text('Previsualización', readonly=True)

    _sql_constraints = [('dev_unique', 'unique(dev_picking_id)',
                         'Esta TT/DEV ya está asignada a otra devolución VP.')]

    @api.depends('sale_id', 'order_id', 'partner_id')
    def _compute_name(self):
        for rec in self:
            rec.name = ' · '.join(filter(None, (rec.sale_id.name or rec.order_id, rec.partner_id.name)))

    @api.depends('request_ids.request_date', 'request_ids.quantity', 'request_ids.remote_status')
    def _compute_summary(self):
        for rec in self:
            reqs = rec.request_ids
            dates = [d for d in reqs.mapped('request_date') if d]
            rec.request_date = min(dates) if dates else False
            rec.n_items = sum(reqs.mapped('quantity'))
            rec.remote_status = ', '.join(sorted(set(filter(None, reqs.mapped('remote_status')))))

    # ------------------------------------------------------------------
    def _try_lock(self):
        """Com a Shopify: si el cron i una persona la processen alhora, el segon se la salta."""
        try:
            self.env.cr.execute('SELECT id FROM vp_return WHERE id = %s FOR UPDATE NOWAIT', (self.id,))
        except Exception:
            self.env.cr.rollback()
            return False
        self.invalidate_cache()
        return True

    def _validate_all(self):
        for rec in self:
            try:
                rec._step_validate()
                rec.write({'state': rec._progress_state(), 'error_msg': False})
            except UserError as e:
                self.env.cr.rollback()
                rec.write({'state': 'review', 'error_msg': e.name if hasattr(e, 'name') else str(e)})
            self.env.cr.commit()

    def action_validate(self):
        self.filtered(lambda r: r.state in ('pending', 'review', 'validated'))._validate_all()
        return True

    def action_process(self):
        """Tot el circuit (vp_flow.py): TT/DEV, etiqueta, missatge i acceptació a VP.
        Cada pas fet queda desat: si un falla, la devolució queda a Revisar i en reintentar
        es continua pel pas que faltava, sense repetir els que ja s'han fet."""
        for rec in self:
            if rec.state in ('accepted', 'received', 'cancel') or not rec._try_lock():
                continue
            try:
                rec._run_flow()
            except UserError as e:
                self.env.cr.rollback()
                rec.write({'state': 'review', 'error_msg': e.name if hasattr(e, 'name') else str(e)})
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception('Devolución VP %s', rec.name)
                rec.write({'state': 'review', 'error_msg': str(e)})
            self.env.cr.commit()
        return True

    def action_cancel(self):
        for rec in self:
            if rec.tracking_ref or rec.notification_state != 'none':
                rec.message_post(body=_('Cancelada con transporte %s y mensaje a VP ya hechos: '
                                        'anular el envío en el transportista a mano si hace falta.')
                                 % (rec.tracking_ref or '-'))
        self.write({'state': 'cancel'})

    def action_reset(self):
        self.filtered(lambda r: r.state in ('review', 'cancel')).write({'state': 'pending', 'error_msg': False})

    # ------------------------------------------------------------------
    def _step_validate(self):
        """Comprova comanda, OUT i peces. Si ja hi ha una TT/DEV feta a mà, s'aprofita.
        No crea res: només escriu la previsualització."""
        self.ensure_one()
        reqs = self.request_ids
        if not reqs:
            raise UserError(_('La devolución no tiene artículos.'))
        sale = self.sale_id or reqs.mapped('sale_id')[:1] or self.config_id._sale_for(self.order_id)
        if not sale:
            raise UserError(_('No hay un pedido Odoo inequívoco para el pedido PinkConnect %s.') % self.order_id)
        if sale.company_id != self.company_id:
            raise UserError(_('El pedido %s es de otra compañía.') % sale.name)
        outs = sale.picking_ids.filtered(lambda p: p.picking_type_code == 'outgoing' and p.state == 'done')
        if not outs:
            raise UserError(_('El pedido %s no tiene ningún OUT validado.') % sale.name)
        pending_outs = sale.picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p.state not in ('done', 'cancel'))
        if pending_outs:
            raise UserError(_('El pedido %s tiene entregas pendientes (%s): se gestiona aparte.')
                            % (sale.name, ', '.join(pending_outs.mapped('name'))))
        if len(set((p.picking_type_id.id, p.location_id.id) for p in outs)) != 1:
            raise UserError(_('Los OUT tienen distintos almacenes o tipos de operación; revisar manualmente.'))

        moves = outs.mapped('move_lines').filtered(lambda m: m.state == 'done' and m.quantity_done > 0)
        for req in reqs:
            if not req.product_id:
                raise UserError(_('No se encuentra el producto %s (GTIN %s).') % (req.sku, req.gtin))
            if not moves.filtered(lambda m: m.product_id == req.product_id):
                raise UserError(_('%s no está en el OUT %s.')
                                % (req.product_id.display_name, ', '.join(outs.mapped('name'))))
        for product in reqs.mapped('product_id'):
            asked = sum(reqs.filtered(lambda r: r.product_id == product).mapped('quantity'))
            sent = sum(m.product_uom._compute_quantity(m.quantity_done, m.product_id.uom_id)
                       for m in moves.filtered(lambda m: m.product_id == product))
            if asked > sent:
                raise UserError(_('VP pide %s u. de %s pero solo se enviaron %s.')
                                % (asked, product.display_name, sent))

        existing = self.env['stock.picking'].search([
            ('move_lines.origin_returned_move_id', 'in', moves.ids), ('state', '!=', 'cancel')])
        vals = {'sale_id': sale.id, 'out_picking_ids': [(6, 0, outs.ids)]}
        if existing:
            # TT/DEV feta a mà (p. ex. la Lorena amb «Devs masivas ONLINE»): s'aprofita si n'hi ha una
            used = self.search([('dev_picking_id', 'in', existing.ids), ('id', '!=', self.id)])
            if len(existing) > 1 or used:
                raise UserError(_('El OUT %s ya tiene devoluciones (%s); revisar manualmente.')
                                % (', '.join(outs.mapped('name')), ', '.join(existing.mapped('name'))))
            if self.dev_picking_id != existing:
                vals['dev_picking_id'] = existing.id
                self.message_post(body=_('Ya existía la TT/DEV %s: se aprovecha.') % existing.name)

        if self.config_id.return_full_order:
            lines = ['%s x %s' % (m.quantity_done, m.product_id.display_name) for m in moves.sorted('id')]
        else:
            lines = ['%s x %s' % (r.quantity, r.product_id.display_name) for r in reqs]
        vals['preview'] = _('Pedido %s · %s\nOUT: %s\nTT/DEV a %s con:\n%s') % (
            sale.name, sale.partner_shipping_id.country_id.code or '?', ', '.join(outs.mapped('name')),
            self.config_id.return_location_id.display_name or '?', '\n'.join(lines))
        self.write(vals)

    def _step_create_dev(self):
        """Com «Devs masivas ONLINE» i el mòdul Shopify: retorn de l'OUT amb to_refund."""
        self.ensure_one()
        location = self.config_id.return_location_id
        if not location:
            raise UserError(_('Falta la ubicación de devolución en la configuración.'))
        outs = self.out_picking_ids
        out = outs.sorted('id')[:1]
        source_moves = outs.mapped('move_lines').filtered(
            lambda m: m.state == 'done' and m.quantity_done > 0).sorted('id')
        if self.env['stock.move'].search([('origin_returned_move_id', 'in', source_moves.ids),
                                          ('state', '!=', 'cancel')]):
            raise UserError(_('Ya existen movimientos de devolución para estos OUT; revisar.'))
        if self.config_id.return_full_order:
            moves = [(0, 0, {'product_id': m.product_id.id, 'quantity': m.quantity_done,
                             'move_id': m.id, 'to_refund': True}) for m in source_moves]
        else:
            moves = []
            available = {m.id: m.product_uom._compute_quantity(m.quantity_done, m.product_id.uom_id)
                         for m in source_moves}
            for req in self.request_ids:
                remaining = req.quantity
                for move in source_moves.filtered(lambda m: m.product_id == req.product_id):
                    take = min(remaining, available[move.id])
                    if take <= 0:
                        continue
                    moves.append((0, 0, {'product_id': req.product_id.id,
                                         'quantity': req.product_id.uom_id._compute_quantity(take, move.product_uom),
                                         'move_id': move.id, 'to_refund': True}))
                    available[move.id] -= take
                    remaining -= take
        ctx = {'active_model': 'stock.picking', 'active_id': out.id, 'active_ids': [out.id]}
        wizard = self.env['stock.return.picking'].with_context(ctx).create({
            'picking_id': out.id, 'location_id': location.id, 'product_return_moves': moves})
        dev = self.env['stock.picking'].browse(wizard.create_returns().get('res_id'))
        self.dev_picking_id = dev
        msg = _('Devolución VP %s (pedido PinkConnect %s)') % (self.name, self.order_id)
        dev.message_post(body=msg)
        for original in outs:
            original.message_post(body=_('Devolución VP: creada %s') % dev.name)
        self.message_post(body=_('TT/DEV creada: %s') % dev.name)
