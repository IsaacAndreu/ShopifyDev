import json
from datetime import datetime
from urllib.parse import urlsplit

import pytz
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

MADRID = pytz.timezone('Europe/Madrid')


class VPReturnConfig(models.Model):
    _name = 'vp.return.config'
    _description = 'Configuración devoluciones VP'

    name = fields.Char(required=True)
    connection_id = fields.Many2one('pink.connect.channel.configuration', required=True)
    company_id = fields.Many2one(related='connection_id.company_id', store=True)
    order_id_filter = fields.Char('ID pedido PinkConnect (piloto)', required=True)
    sample_response = fields.Text('Respuesta de ejemplo (JSON)')
    last_response = fields.Text('Última respuesta API', readonly=True)
    last_read = fields.Datetime('Última lectura', readonly=True)

    def _check_access(self):
        self.ensure_one()
        self.check_access_rights('write')
        self.check_access_rule('write')
        if not self.env.user.has_group('nath_vp_returns.group_vp_manager'):
            raise UserError(_('Se requiere el grupo Devoluciones VP: configuración.'))
        if self.company_id not in self.env.companies:
            raise UserError(_('La compañía no está seleccionada.'))
        if not (self.order_id_filter or '').strip().isdigit():
            raise UserError(_('Introduce el ID numérico interno del pedido PinkConnect.'))

    def action_read(self):
        self._check_access()
        connection = self.connection_id
        parts = urlsplit(connection.url or '')
        if (parts.scheme != 'https' or parts.netloc not in
                ('api.pink-connect.com', 'api-pinkstaging.pink-connect.com') or
                parts.path.rstrip('/') != '/v4' or parts.query or parts.fragment):
            raise UserError(_('La URL debe ser la API oficial HTTPS v4 de PinkConnect.'))
        if not connection.api_key:
            raise UserError(_('Falta la clave en la conexión PinkConnect.'))
        # Exactly one bounded GET, no retries, redirects or external mutations.
        try:
            response = requests.get(
                connection.url.rstrip('/') + '/return-requests',
                headers={'Authorization': 'Bearer ' + connection.api_key,
                         'Accept': 'application/json'},
                params={'orderId': self.order_id_filter.strip(), 'limit': 50},
                timeout=(10, 45), allow_redirects=False)
        except requests.RequestException:
            raise UserError(_('No se ha podido leer PinkConnect. No se ha modificado la plataforma.'))
        if response.status_code != 200:
            raise UserError(_('PinkConnect ha respondido HTTP %s.') % response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise UserError(_('PinkConnect no ha devuelto JSON.'))
        self.write({'last_response': json.dumps(data, ensure_ascii=False, indent=2),
                    'last_read': fields.Datetime.now()})
        return self._open_config()

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
        if len(data) > 50:
            raise UserError(_('Máximo 50 líneas por prueba.'))
        parsed = []
        for row in data:
            if not isinstance(row, dict) or not all(row.get(k) for k in ('returnRequestId', 'orderId', 'status')):
                raise UserError(_('Faltan returnRequestId, orderId o status. No se importa la respuesta.'))
            if str(row['orderId']) != self.order_id_filter.strip():
                raise UserError(_('La respuesta contiene otra comanda; no se importa.'))
            parsed.append(row)
        log_model = self.env['vp.return.request']
        for row in parsed:
            vals = {'remote_status': str(row['status']),
                    'order_line_id': str(row.get('orderLineId') or ''),
                    'marketplace_return_id': row.get('marketplaceReturnId') or False,
                    'marketplace_order_number': row.get('marketplaceOrderNumber') or False,
                    'sku': row.get('sku') or False,
                    'gtin': row.get('gtin') or False,
                    'return_type': row.get('type') or False,
                    'reason': row.get('reason') or False,
                    'payload': json.dumps(row, ensure_ascii=False, indent=2)}
            existing = log_model.search([('config_id', '=', self.id),
                ('remote_id', '=', str(row['returnRequestId'])), ('simulated', '=', simulated)])
            if existing:
                existing.write(vals)
                continue
            feeds = self.env['pink.connect.order.feed'].search([
                ('pink_connect_id', '=', self.connection_id.id),
                ('order_id', '=', str(row['orderId']))])
            sale = feeds.sale_order_id if len(feeds) == 1 else self.env['sale.order']
            vals.update({'config_id': self.id, 'remote_id': str(row['returnRequestId']),
                         'order_id': str(row['orderId']), 'simulated': simulated,
                         'sale_id': sale.id if len(sale) == 1 and sale.company_id == self.company_id else False})
            log_model.create(vals)
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

    def action_preview(self):
        self.check_access_rights('write')
        self.check_access_rule('write')
        for rec in self:
            if rec.company_id not in self.env.companies:
                raise UserError(_('La compañía no está seleccionada.'))
            country = rec.sale_id.partner_shipping_id.country_id.code
            if not rec.sale_id:
                result = _('REVISAR: no hay un pedido Odoo inequívoco para este ID y conexión.')
            elif rec.remote_status != 'PENDING':
                result = _('No aceptar: el estado leído no es PENDING.')
            elif country not in ('ES', 'FR'):
                result = _('REVISAR: el piloto solo contempla ES y FR.')
            else:
                transport = ('Nacex 44, entrega a punto' if country == 'ES'
                             else "FedEx a domicilio; PREVENIR A L'AVANCE; etiqueta PDF")
                result = ('SIMULACIÓN — ninguna operación ejecutada.\n'
                          'Pedido: %s\nTransporte: %s\n'
                          '1. Validar artículos, cantidades y OUT.\n'
                          '2. Crear/recuperar TT/DEV y transporte.\n'
                          '3. Enviar mensaje al cliente.\n'
                          '4. PUT /return-requests/%s/PROCESSING\n'
                          '5. Consultar estado y parar si no es PROCESSING.\n'
                          'Creación de TT/DEV, transporte, mensajes y PUT todavía '
                          'no habilitados en esta versión piloto.') % (
                              rec.sale_id.name, transport, rec.remote_id)
            rec.preview = result
