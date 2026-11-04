# -*- coding: utf-8 -*-
import json
import logging
import time
from datetime import datetime, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import vp_parse
from .vp_api import VeepeeApi, VeepeeApiError

try:  # queue_job 13.0.3.x: el decorador encara hi és (deprecated); si algun dia no hi és, no cal
    from odoo.addons.queue_job.job import job as _job
except ImportError:
    _job = None


def _as_job(func):
    return _job(func) if _job else func


def _hhmm(value):
    """17.25 -> '17:15'"""
    minutes = int(round((value or 0.0) * 60))
    return '%02d:%02d' % (minutes // 60, minutes % 60)


_logger = logging.getLogger(__name__)
TZ = pytz.timezone('Europe/Madrid')
JOB_ORDERS = 50          # comandes per lot en segon pla (~2 min, per sota del límit del worker)
# Mateixos noms que els crons 450 i 451 (Registros): l'historial i el «ja ha fallat en 24 h» continuen
LOG_CONFIRM = 'DP: confirmar pedidos automaticamente'
LOG_GROUP = 'DP: crear agrupaciones y oleadas'
JOB_STALE_MINUTES = 20   # un job 'started' més vell que això és d'abans d'un restart: es pot rellançar
TARIFA_SELECTION = [('es', 'ES'), ('fr_benelux', 'FR / BENELUX'), ('it', 'IT')]
# Tarifa per país quan el transportista no és a la taula de mapeig
TARIFA_BY_COUNTRY = {'ES': 'es', 'PT': 'es', 'IT': 'it',
                     'FR': 'fr_benelux', 'BE': 'fr_benelux', 'LU': 'fr_benelux', 'NL': 'fr_benelux'}


class VpDropshipConfig(models.Model):
    _name = 'vp.dropship.config'
    _description = 'Dropshipping Veepee: configuración'

    name = fields.Char(required=True, default='Veepee Dropshipping')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)

    # API
    simulate_api = fields.Boolean(
        'Simular API', default=True,
        help='No se conecta a Veepee: los batches se crean subiendo el Excel de VentePriveeSync.')
    base_url = fields.Char('URL API', default='https://dropshipment.veepee.com/')
    api_version = fields.Char('Versión API', default='3')
    api_user = fields.Char('Usuario API', groups='base.group_system')
    api_password = fields.Char('Contraseña API', groups='base.group_system')

    # Automatismes
    auto_fetch = fields.Boolean('Descargar batches automáticamente')
    auto_create = fields.Boolean('Crear pedidos automáticamente',
                                 help='Si no, los pedidos se crean con el botón del batch.')
    # Confirmació i agrupacions (abans crons 450 i 451)
    auto_confirm = fields.Boolean(
        'Confirmar y agrupar automáticamente',
        help='Cron cada 2 min: confirma los pedidos DP- y, cuando no queda ninguno, crea las '
             'agrupaciones y oleadas. Entre semana solo en el horario; sábado y domingo, todo el día.')
    # 03/11: des de les 11:00 (el batch surt de 11:31 a 12:00); espera que s'hagin creat tots els pedidos
    confirm_from = fields.Float('Confirmar desde (hora)', default=11.0)
    confirm_to = fields.Float('Confirmar hasta (hora, día siguiente)', default=7.0)
    confirm_seconds = fields.Integer('Segundos por ejecución (agrupar)', default=90)
    confirm_lot_day = fields.Integer('Pedidos por lote (horario de almacén)', default=20)
    confirm_lunch_from = fields.Float('Comida del almacén desde (hora)', default=13.0)
    confirm_lunch_to = fields.Float('Comida del almacén hasta (hora)', default=13.75)
    confirm_lot_lunch = fields.Integer('Pedidos por lote (comida del almacén)', default=100,
                                       help='Lotes que empiezan en la comida (uno de 100 tarda ~13-20 min).')
    confirm_afternoon_from = fields.Float('Tarde desde (hora)', default=15.0)
    confirm_lot_afternoon = fields.Integer('Pedidos por lote (tarde)', default=40)
    confirm_lot_night = fields.Integer('Pedidos por lote (sin almacén)', default=100)
    confirm_night_from = fields.Float('Lotes grandes desde (hora)', default=17.0,
                                      help='Entre semana, desde esta hora hasta "Confirmar hasta".')
    # Oleades (abans cron 451), quan ja no queda cap pedido per crear ni confirmar. 03/11: des de les
    # 11:00 (provat amb el magatzem treballant: va bé i ràpid), no cal esperar a les 17:00
    group_from = fields.Float('Agrupaciones y oleadas desde (hora)', default=11.0)
    group_to = fields.Float('Agrupaciones y oleadas hasta (hora, día siguiente)', default=6.0)
    group_int_batch = fields.Boolean(
        'Agrupar las INT de cada batch', default=True,
        help='Al acabar las oleadas de un batch, crea una agrupación "<campaña> - <batch>" '
             '(TTUC86 - 1955391) con todas sus INT al SORTER, como se hacía a mano.')
    confirm_action_id = fields.Many2one(
        'ir.actions.server', 'Acción para confirmar', domain=[('model_id.model', '=', 'sale.order')],
        default=lambda s: s.env['ir.actions.server'].search(
            [('name', '=', 'Confirm to Sales Order'), ('model_id.model', '=', 'sale.order')], limit=1),
        help='La misma que se usa a mano (Acción > Confirm to Sales Order). Vacía: Confirmar estándar.')
    group_size = fields.Integer('Máximo de OUT por agrupación', default=150)
    fetch_from = fields.Float('Buscar desde (hora)', default=11.0)
    fetch_to = fields.Float('Buscar hasta (hora)', default=17.5)
    fetch_every = fields.Integer('Buscar cada (min)', default=10)
    start_date = fields.Date('Solo batches creados desde', default=fields.Date.context_today,
                             help='Evita descargar los batches antiguos de la campaña la primera vez.')
    # 03/11: 7200, que es creïn tots d'una (965 en 25 min)
    max_seconds = fields.Integer('Segundos por ejecución', default=7200,
                                 help='Tiempo máximo creando pedidos en cada ejecución del cron.')
    last_fetch = fields.Datetime('Última búsqueda', readonly=True)
    last_error = fields.Text('Último error', readonly=True)

    # Valors de les comandes (els mateixos que posava la plantilla d'importació + actualització)
    partner_id = fields.Many2one('res.partner', 'Cliente')
    partner_shipping_id = fields.Many2one('res.partner', 'Dirección de entrega',
                                          help='Vacío: la de entrega del cliente.')
    warehouse_id = fields.Many2one('stock.warehouse', 'Almacén')
    tax_ids = fields.Many2many('account.tax', string='Impuestos')
    order_type_id = fields.Many2one('sale.order.type', 'Tipo de pedido')
    season_id = fields.Many2one('style.season', 'Temporada')
    brand_id = fields.Many2one('product.brand', 'Marca')
    team_id = fields.Many2one('crm.team', 'Equipo de ventas')
    user_id = fields.Many2one('res.users', 'Comercial')
    payment_mode_id = fields.Many2one('account.payment.mode', 'Modo de pago')
    payment_term_id = fields.Many2one('account.payment.term', 'Plazo de pago')
    delivery_days = fields.Integer('Fecha de entrega: días después del batch', default=1)
    use_price_file = fields.Boolean(
        'Precios del fichero de la campaña',
        help='Desmarcado: los pedidos se crean a precio 0 y los precios se ponen al facturar. '
             'Marcado: se usa el precio importado (menú Precios) y sin precio no se crea el pedido.')
    pricelist_es_id = fields.Many2one('product.pricelist', 'Tarifa ES')
    pricelist_fr_benelux_id = fields.Many2one('product.pricelist', 'Tarifa FR / BENELUX')
    pricelist_it_id = fields.Many2one('product.pricelist', 'Tarifa IT')

    # Variants
    update_veepee_ids = fields.Boolean('Actualizar "Dropshipping Veepee Product ID"', default=True)
    veepee_field = fields.Char('Campo de la variante', default='x_studio_veepee_product_id')

    # Avisos
    notify_emails = fields.Char('Avisar a (emails)', help='Separados por comas.')
    email_from = fields.Char('Remitente', default='TUC TUC <no_reply@tuctuc.com>')
    mail_server_id = fields.Many2one('ir.mail_server', 'Servidor de correo')

    carrier_ids = fields.One2many('vp.dropship.carrier', 'config_id', 'Transportistas')

    # ------------------------------------------------------------------
    def _api(self):
        self.ensure_one()
        cfg = self.sudo()
        return VeepeeApi(cfg.base_url, cfg.api_version, cfg.api_user, cfg.api_password)

    def _pricelist(self, tarifa):
        # sense tarifa específica: la del client (WholeSale ES-PT)
        return ({'es': self.pricelist_es_id, 'fr_benelux': self.pricelist_fr_benelux_id,
                 'it': self.pricelist_it_id}.get(tarifa)
                or self.partner_id.property_product_pricelist)

    def _in_window(self):
        now = datetime.now(TZ)
        hour = now.hour + now.minute / 60.0
        return self.fetch_from <= hour < self.fetch_to

    def action_test_connection(self):
        self.ensure_one()
        if self.simulate_api:
            raise UserError(_('Está en modo "Simular API": no se conecta a Veepee.'))
        api = self._api()
        try:
            api.login()
            ops = api.operations()
        except VeepeeApiError as e:
            raise UserError(str(e))
        lines = ['%s  %s  %s-%s  %s' % (o.get('id'), o.get('code') or o.get('name') or '',
                                        (o.get('beginDate') or '')[:10], (o.get('endDate') or '')[:10],
                                        o.get('status') or '') for o in ops[:30]]
        raise UserError(_('Conexión correcta. Campañas (%s):\n%s') % (len(ops), '\n'.join(lines)))

    def action_fetch_now(self):
        self.ensure_one()
        if self.simulate_api:
            raise UserError(_('En modo "Simular API" los batches se crean subiendo el Excel.'))
        new = self._fetch_new_batches()
        if not new:
            raise UserError(_('No hay batches nuevos.'))
        return {
            'type': 'ir.actions.act_window', 'name': _('Batches nuevos'),
            'res_model': 'vp.dropship.batch', 'view_mode': 'tree,form',
            'domain': [('id', 'in', new.ids)],
        }

    def action_fill_carriers(self):
        """Omple la taula amb els transportistes 'Veepee - <país> - <clau>' que encara no hi són."""
        self.ensure_one()
        Carrier = self.env['delivery.carrier'].with_context(active_test=False)
        existing = set(self.carrier_ids.mapped('key'))
        for carrier in Carrier.search([('name', '=like', 'Veepee - %')]):
            parts = [p.strip() for p in carrier.name.split(' - ')]
            if len(parts) != 3:
                continue
            key = '%s#%s' % (parts[1], parts[2])
            tarifa = TARIFA_BY_COUNTRY.get(parts[1])
            if key in existing or not tarifa:   # país sense tarifa coneguda (DE, AT, CH...): a mà
                continue
            self.env['vp.dropship.carrier'].create({
                'config_id': self.id, 'key': key, 'carrier_id': carrier.id, 'tarifa': tarifa,
            })
            existing.add(key)
        return True

    # ------------------------------------------------------------------
    def _fetch_new_batches(self):
        """Busca a Veepee els batches que encara no tenim i els descarrega."""
        self.ensure_one()
        Batch = self.env['vp.dropship.batch']
        new = Batch
        api = self._api()
        api.login()
        start = fields.Date.to_string(self.start_date) if self.start_date else '0000'
        for op in api.operations():
            op_id = vp_parse._txt(op.get('id') or op.get('code'))
            op_code = vp_parse._txt(op.get('code') or op.get('name') or op_id)
            if not op_id or (op.get('endDate') and op['endDate'][:10] < start):
                continue
            for b in api.batches(op_id):
                b_id = vp_parse._txt(b.get('id') or b.get('batchId'))
                created = vp_parse._txt(b.get('creationDate'))[:10]
                if not b_id or (created and created < start):
                    continue
                if (b.get('status') or '').lower() in ('done', 'closed'):
                    continue
                if Batch.search_count([('config_id', '=', self.id), ('operation_ref', '=', op_id),
                                       ('batch_ref', '=', b_id)]):
                    continue
                batch = Batch.create({
                    'config_id': self.id, 'operation_ref': op_id, 'operation_code': op_code,
                    'batch_ref': b_id, 'batch_date': created or fields.Date.context_today(self),
                    'api_status': b.get('status'),
                })
                self.env.cr.commit()   # que no es torni a crear si falla la descàrrega
                try:
                    batch._download(api=api)
                except Exception as e:
                    self.env.cr.rollback()
                    batch.write({'state': 'review'})
                    batch.message_post(body=_('Error al descargar: %s') % e)
                self.env.cr.commit()
                new |= batch
        return new

    # ------------------------------------------------------------------
    # Confirmar pedidos DP- i crear agrupacions + oleades (la lògica dels crons 450 i 451)
    def _in_confirm_window(self):
        """Entre setmana, de confirm_from fins a confirm_to de l'endemà; dissabte i diumenge, tot el dia."""
        now = datetime.now(TZ)
        hhmm = now.strftime('%H:%M')
        return now.weekday() >= 5 or not (_hhmm(self.confirm_to) <= hhmm < _hhmm(self.confirm_from))

    def _in_group_window(self):
        """Oleades: entre setmana de group_from fins a group_to de l'endemà; el cap de setmana, tot el dia."""
        now = datetime.now(TZ)
        hhmm = now.strftime('%H:%M')
        return now.weekday() >= 5 or not (_hhmm(self.group_to) <= hhmm < _hhmm(self.group_from))

    def _batches_creating(self):
        """Batches Veepee que encara estan creant pedidos: fins que no acabin no es confirma ni s'agrupa."""
        return self.env['vp.dropship.batch'].search_count([('state', 'in', ('downloaded', 'creating'))])

    def _log(self, func, message, level='info'):
        """Com el log() de les accions de servidor: a Ajustes > Técnico > Registros."""
        self.env['ir.logging'].sudo().create({
            'name': 'nath_vp_dropship', 'type': 'server', 'dbname': self.env.cr.dbname,
            'level': level, 'message': message, 'path': self._name, 'func': func, 'line': str(self.id),
        })

    def _confirm_lot_size(self):
        """Mida del lot segons l'hora en què comença (entre setmana, 03/11): 20 mentre el magatzem
        treballa, 100 si comença a la comida (13:00-13:45), 40 a la tarda (15:00) i 100 a partir de
        confirm_night_from i el cap de setmana. Lots més grans no: es guanya molt poc i un error
        desfà tot el lot."""
        now = datetime.now(TZ)
        hhmm = now.strftime('%H:%M')
        if now.weekday() >= 5 or not (_hhmm(self.confirm_to) <= hhmm < _hhmm(self.confirm_night_from)):
            return self.confirm_lot_night or 100
        if _hhmm(self.confirm_lunch_from) <= hhmm < _hhmm(self.confirm_lunch_to):
            return self.confirm_lot_lunch or 100
        if hhmm >= _hhmm(self.confirm_afternoon_from):
            return self.confirm_lot_afternoon or 40
        return self.confirm_lot_day or 20

    def _confirm_records(self, sales):
        """Com a mà: l'acció «Confirm to Sales Order» (comprovacions de NIF, SEPA i data dels albarans)
        sobre tot el lot d'una vegada. Sense acció configurada, action_confirm() estàndard."""
        action = self.confirm_action_id
        if action:
            action.with_context(active_model='sale.order', active_ids=sales.ids, active_id=sales[:1].id).run()
        else:
            sales.action_confirm()

    def _confirm_step(self, simulate=False):
        """Confirma UN LOT de pedidos DP- en presupuesto (02/11: un a un amb confirm='yes' anava
        10 vegades més lent que en lot: 95-180 s contra 8,8 s per pedido). Només els que ja tenen
        transportista, data d'entrega, modo i plazo de pago (si un pedido del mòdul no té modo de pago,
        se li posa el de la configuració). Si el lot falla, es desfà i es proven un a un; els que
        fallen no es tornen a provar fins al cap de 24 h."""
        t0 = time.time()
        since = fields.Datetime.now() - timedelta(days=1)
        Logging = self.env['ir.logging'].sudo()
        SaleOrder = self.env['sale.order']
        pedidos = SaleOrder.search([('name', '=like', 'DP-%'), ('state', 'in', ['draft', 'sent'])], order='id')
        size = self._confirm_lot_size()
        lote = SaleOrder
        sin_datos = []
        for pedido in pedidos:
            if len(lote) >= size:
                break
            modo = pedido.payment_mode_id or (pedido.dp_batch_id and self.payment_mode_id)
            if not (pedido.carrier_id and pedido.commitment_date and modo and pedido.payment_term_id):
                sin_datos.append(pedido.name)
                continue
            if Logging.search_count([('func', '=', LOG_CONFIRM), ('message', '=like', pedido.name + ' ERROR%'),
                                     ('create_date', '>=', since)]):
                continue   # ja ha fallat en les últimes 24 h
            lote |= pedido
        hechos = 0
        if lote and not simulate:
            ids, nombres = lote.ids, lote.mapped('name')
            t1 = time.time()
            try:
                for pedido in lote.filtered(lambda s: not s.payment_mode_id):
                    pedido.payment_mode_id = self.payment_mode_id
                self._confirm_records(lote)
                self.env.cr.commit()
                hechos = len(ids)
                self._log(LOG_CONFIRM, 'Lote de %s confirmado en %.0f s (%s ... %s)' % (
                    len(ids), time.time() - t1, nombres[0], nombres[-1]))
            except Exception as e:
                self.env.cr.rollback()
                self.env.clear()
                self._log(LOG_CONFIRM, 'Lote de %s con error, se confirman uno a uno: %s' % (
                    len(ids), str(e)[:300]), 'warning')
                self.env.cr.commit()
                for pedido in SaleOrder.browse(ids):
                    if pedido.state not in ('draft', 'sent'):
                        continue
                    nombre = pedido.name
                    t1 = time.time()
                    try:
                        if not pedido.payment_mode_id:
                            pedido.payment_mode_id = self.payment_mode_id
                        self._confirm_records(pedido)
                        self.env.cr.commit()
                        self._log(LOG_CONFIRM, '%s confirmado en %.1f s' % (nombre, time.time() - t1))
                        hechos += 1
                    except Exception as e2:
                        self.env.cr.rollback()
                        self.env.clear()
                        self._log(LOG_CONFIRM, '%s ERROR: %s' % (nombre, str(e2)[:300]), 'warning')
                    self.env.cr.commit()
        if simulate:
            resumen = 'Ejecucion: lote de %s pedidos por confirmar (SIMULACION, %s lineas, lotes de %s) · %s en ' \
                      'presupuesto · %s sin datos actualizados%s' % (
                          len(lote), len(lote.mapped('order_line')), size, len(pedidos), len(sin_datos),
                          (' (p. ej. %s)' % ', '.join(sin_datos[:5])) if sin_datos else '')
        else:
            resumen = 'Ejecucion: %s pedidos confirmados en %.0f s · %s pendientes · %s sin datos actualizados%s' % (
                hechos, time.time() - t0, len(pedidos) - hechos - len(sin_datos), len(sin_datos),
                (' (p. ej. %s)' % ', '.join(sin_datos[:5])) if sin_datos else '')
            if pedidos:   # des de les 11:00 cada 2 min: sense res a confirmar no omple Registros
                self._log(LOG_CONFIRM, resumen)
                self.env.cr.commit()
        return resumen

    def _dp_left_to_confirm(self):
        return self.env['sale.order'].search_count([
            ('name', '=like', 'DP-%'), ('state', 'in', ['draft', 'sent']),
            ('carrier_id', '!=', False), ('commitment_date', '!=', False)])

    def _group_step(self, simulate=False):
        """Agrupacions dels OUT de pedidos DP- reservats, sense agrupació, sense backorder i encara en
        estoc (no al SORTER), per transportista + data prevista: B-DP_<transportista>_<ddmmaa>
        (ddmmaa = dia abans de la data prevista = dia del batch), màxim group_size repartits per igual,
        _1, _2... si n'hi ha més d'una. Després de cada una, «Crear transfer para oleada» (INT al SORTER).
        Una agrupació cada vegada, amb commit, fins a confirm_seconds."""
        Picking = self.env['stock.picking']
        Batch = self.env['stock.picking.batch']
        max_outs = self.group_size or 150
        t0 = time.time()
        por_confirmar = self._dp_left_to_confirm()
        if por_confirmar and not simulate:
            return 'Quedan %s pedidos DP por confirmar: todavia no se agrupa.' % por_confirmar
        por_crear = self._batches_creating()
        if por_crear and not simulate:
            return 'Esperando: %s batch(es) Veepee aun creando pedidos: todavia no se agrupa.' % por_crear
        outs = Picking.search([
            ('name', '=like', 'TT/OUT/%'), ('origin', '=like', 'DP-%'), ('state', '=', 'assigned'),
            ('batch_id', '=', False), ('backorder_id', '=', False),
            ('location_id.barcode', '!=', 'SORTER'),
        ], order='id')
        # com el cron de web/ECI: fora els que ja tenen alguna cosa preparada
        outs = outs.filtered(lambda p: not p.move_line_ids_without_package.filtered(lambda l: l.qty_done > 0))
        grupos, orden = {}, []
        for p in outs:
            dia = (pytz.utc.localize(p.scheduled_date).astimezone(TZ).date() if p.scheduled_date
                   else datetime.now(TZ).date())
            clave = (p.carrier_id.id, dia)
            if clave not in grupos:
                grupos[clave] = Picking
                orden.append(clave)
            grupos[clave] |= p

        def unidades(pickings):
            return sum(pickings.mapped('move_lines.product_uom_qty'))

        def nombre_base(pickings, dia):
            transp = (pickings[0].carrier_id.name or 'SIN_TRANSPORTISTA').replace('Veepee - ', '')
            transp = transp.replace(' - ', '_').replace(' ', '_')
            return 'B-DP_%s_%s' % (transp, (dia - timedelta(days=1)).strftime('%d%m%y'))

        def partes(pickings):
            return -(-len(pickings) // max_outs) or 1

        def siguiente_nombre(base, usados, total_partes):
            """Una sola agrupació: sense número. Diverses del mateix nom: _1, _2, _3..."""
            existentes = Batch.search([('name', '=like', base + '%')]).mapped('name') + usados
            n = len([x for x in existentes if x == base or x.startswith(base + '_')])
            return base if n == 0 and total_partes == 1 else '%s_%d' % (base, n + 1)

        def primer_trozo(pickings):
            """Els OUT de la primera agrupació: es reparteix per igual, sense passar de max_outs."""
            return pickings[:-(-len(pickings) // partes(pickings))]

        lineas, usados = [], []
        creadas = 0
        for clave in orden:
            restantes = grupos[clave]
            base = nombre_base(restantes, clave[1])
            while restantes:
                if not simulate and time.time() - t0 > (self.confirm_seconds or 90):
                    return 'Agrupaciones creadas: %s (continua en la siguiente ejecucion)' % creadas
                trozo = primer_trozo(restantes)
                nombre = siguiente_nombre(base, usados, partes(restantes))
                if simulate:
                    usados.append(nombre)
                    lineas.append('%s: %s OUT, %s u.' % (nombre, len(trozo), int(unidades(trozo))))
                    restantes -= trozo
                    continue
                t1 = time.time()
                try:
                    batch = Batch.create({'name': nombre, 'company_id': trozo[0].company_id.id})
                    trozo.write({'batch_id': batch.id})
                    Picking.create_transfer_for_batch(trozo)
                    self.env.cr.commit()
                    self._log(LOG_GROUP, '%s creada: %s OUT, %s u., oleada en %.0f s' % (
                        nombre, len(trozo), int(unidades(trozo)), time.time() - t1))
                    self.env.cr.commit()
                    creadas += 1
                    restantes -= trozo
                except Exception as e:
                    self.env.cr.rollback()
                    self.env.clear()
                    self._log(LOG_GROUP, '%s ERROR: %s' % (nombre, str(e)[:300]), 'warning')
                    self.env.cr.commit()
                    return 'Error en %s: %s' % (nombre, str(e)[:300])   # que no ho reintenti en bucle
        if simulate:
            return 'SIMULACION agrupaciones DP: %s OUT en %s agrupaciones%s\n%s%s' % (
                len(outs), len(lineas),
                (' (atencion: quedan %s pedidos DP por confirmar)' % por_confirmar) if por_confirmar else '',
                '\n'.join(lineas) or 'Nada que agrupar.',
                ('\n' + self._int_batch_step(simulate=True)) if not outs and self.group_int_batch else '')
        resumen = 'Agrupaciones creadas: %s' % creadas
        if not outs and self.group_int_batch:   # ja no queda cap OUT per agrupar
            resumen += '\n' + self._int_batch_step()
        return resumen

    def _int_batch_step(self, simulate=False):
        """03/11: quan s'han fet totes les oleades d'un batch Veepee, una agrupació
        «<campanya> - <batch>» (TTUC86 - 1955391) amb totes les seves INT al SORTER (l'origen de cada INT
        és el nom de l'agrupació d'OUT), com la feia el magatzem a mà. Si ja n'hi ha una amb aquest nom
        (feta a mà), s'hi afegeixen les que falten."""
        Picking = self.env['stock.picking']
        PickingBatch = self.env['stock.picking.batch']
        since = fields.Date.context_today(self) - timedelta(days=7)
        lineas = []
        for batch in self.env['vp.dropship.batch'].search([
                ('config_id', '=', self.id), ('state', 'in', ('done', 'review', 'closed')),
                ('int_batch_id', '=', False), ('batch_date', '>=', since)], order='id'):
            sales = batch.sale_ids
            if not sales or sales.filtered(lambda s: s.state in ('draft', 'sent')):
                continue
            outs = sales.mapped('picking_ids').filtered(lambda p: p.name.startswith('TT/OUT/'))
            sin_oleada = outs.filtered(
                lambda p: p.state == 'assigned' and not p.batch_id and not p.backorder_id
                and p.location_id.barcode != 'SORTER'
                and not p.move_line_ids_without_package.filtered(lambda l: l.qty_done > 0))
            if sin_oleada:
                continue   # encara li falten oleades
            agrupaciones = outs.mapped('batch_id.name')
            if not agrupaciones:
                continue
            ints = Picking.search([('name', '=like', 'TT/INT/%'), ('origin', 'in', agrupaciones),
                                   ('batch_id', '=', False), ('state', 'not in', ('done', 'cancel'))])
            nombre = '%s - %s' % (batch.operation_code, batch.batch_ref)
            existente = PickingBatch.search([('name', '=', nombre)], limit=1)
            if not ints and not existente:
                continue
            if simulate:
                lineas.append('%s: %s INT%s' % (nombre, len(ints), ' (ya existe, se añaden)' if existente else ''))
                continue
            try:
                destino = existente or PickingBatch.create({'name': nombre, 'company_id': batch.company_id.id})
                ints.write({'batch_id': destino.id})
                batch.int_batch_id = destino
                batch.message_post(body=_('Agrupación de las INT: %s (%s INT).') % (nombre, len(destino.picking_ids)))
                self.env.cr.commit()
                self._log(LOG_GROUP, '%s %s: %s INT al SORTER' % (
                    nombre, 'actualizada' if existente else 'creada', len(ints)))
                self.env.cr.commit()
                lineas.append(nombre)
            except Exception as e:
                self.env.cr.rollback()
                self.env.clear()
                self._log(LOG_GROUP, '%s ERROR: %s' % (nombre, str(e)[:300]), 'warning')
                self.env.cr.commit()
                lineas.append('Error en %s: %s' % (nombre, str(e)[:300]))
        if simulate:
            return 'SIMULACION agrupaciones de INT: %s' % (', '.join(lineas) or 'ninguna')
        return 'Agrupaciones de INT: %s' % (', '.join(lineas) or 'ninguna')

    def _confirm_and_group(self, check_hours=False):
        """Una execució: primer confirmar; quan ja no en queda cap per confirmar, agrupar. Res mentre
        algun batch Veepee encara estigui creant pedidos (03/11), perquè surtin complets. Amb
        check_hours, cada pas només dins el seu horari (confirmar / agrupacions i oleades)."""
        self.ensure_one()
        por_crear = self._batches_creating()
        if por_crear:
            resumen = 'Esperando: %s batch(es) Veepee aun creando pedidos' % por_crear
            self._log(LOG_CONFIRM, resumen)
            self.env.cr.commit()
            return resumen
        resumen = ''
        if not check_hours or self._in_confirm_window():
            resumen = self._confirm_step()
        if (not check_hours or self._in_group_window()) and not self._dp_left_to_confirm():
            resumen += ('\n' if resumen else '') + self._group_step()
        return resumen or 'Fuera de horario.'

    @api.model
    def cron_confirm_group(self):
        """Cron cada 2 minuts (substitueix els crons 450 i 451)."""
        for config in self.search([('auto_confirm', '=', True)]):
            if not (config._in_confirm_window() or config._in_group_window()):
                continue
            try:
                config._confirm_and_group(check_hours=True)
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception('VP dropship confirmar/agrupar %s', config.name)
                config.write({'last_error': str(e)[:2000]})
                self.env.cr.commit()

    def action_simulate_confirm_group(self):
        """No canvia res: diu què confirmaria i quines agrupacions faria (a qualsevol hora)."""
        self.ensure_one()
        raise UserError('%s\n\n%s' % (self._confirm_step(simulate=True), self._group_step(simulate=True)))

    def action_confirm_group_now(self):
        """Una execució ara mateix, sense mirar l'horari (com «Ejecutar manualmente» del cron)."""
        self.ensure_one()
        raise UserError(self._confirm_and_group())

    @api.model
    def cron_run(self):
        """Cron cada 5 minuts: busca batches nous (dins l'horari) i continua creant comandes."""
        for config in self.search([]):
            try:
                if (config.auto_fetch and not config.simulate_api and config._in_window()
                        and (not config.last_fetch or config.last_fetch
                             <= fields.Datetime.now() - timedelta(minutes=config.fetch_every or 30))):
                    config.write({'last_fetch': fields.Datetime.now(), 'last_error': False})
                    self.env.cr.commit()
                    config._fetch_new_batches()
                if config.auto_create:
                    deadline = time.time() + (config.max_seconds or 240)
                    # també els 'Revisar': es creen les que estan bé i les d'error s'hi queden
                    for batch in self.env['vp.dropship.batch'].search(
                            [('config_id', '=', config.id),
                             ('state', 'in', ('downloaded', 'creating', 'review'))], order='id'):
                        if time.time() > deadline:
                            break
                        if batch.n_pending:
                            batch._create_orders(deadline)
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception('VP dropship %s', config.name)
                config.write({'last_error': str(e)[:2000]})
                self.env.cr.commit()


class VpDropshipCarrier(models.Model):
    _name = 'vp.dropship.carrier'
    _description = 'Dropshipping Veepee: transportista'
    _order = 'key'

    config_id = fields.Many2one('vp.dropship.config', required=True, ondelete='cascade')
    key = fields.Char('País#Transportista Veepee', required=True, help='Columna LI_Pays: ES#ASM')
    carrier_id = fields.Many2one('delivery.carrier', 'Transportista Odoo', required=True)
    tarifa = fields.Selection(TARIFA_SELECTION, 'Tarifa',
                              help='Solo para el fichero de precios. Si se deja vacía, la del país (ES#...).')

    _sql_constraints = [('key_uniq', 'unique(config_id, key)', 'Esta clave ya está mapeada.')]

    @api.model
    def create(self, vals):
        if not vals.get('tarifa') and vals.get('key'):
            vals['tarifa'] = TARIFA_BY_COUNTRY.get(vals['key'].split('#')[0].strip().upper())
        return super().create(vals)


class VpDropshipPrice(models.Model):
    _name = 'vp.dropship.price'
    _description = 'Dropshipping Veepee: precio por EAN'
    _order = 'campaign, barcode'

    campaign = fields.Char('Campaña', index=True, help='Código de la operación (TTUC85). Vacío: cualquiera.')
    barcode = fields.Char('EAN', required=True, index=True)
    price_es = fields.Float('Tarifa ES', digits='Product Price')
    price_fr_benelux = fields.Float('Tarifa FR / BENELUX', digits='Product Price')
    price_it = fields.Float('Tarifa IT', digits='Product Price')

    _sql_constraints = [('price_uniq', 'unique(campaign, barcode)', 'EAN repetido en la campaña.')]


class VpDropshipBatch(models.Model):
    _name = 'vp.dropship.batch'
    _description = 'Dropshipping Veepee: batch'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(compute='_compute_name', store=True)
    config_id = fields.Many2one('vp.dropship.config', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='config_id.company_id', store=True)
    operation_ref = fields.Char('Id campaña')
    operation_code = fields.Char('Campaña')
    batch_ref = fields.Char('Batch', required=True)
    batch_date = fields.Date('Fecha del batch', default=fields.Date.context_today)
    api_status = fields.Char('Estado en Veepee', readonly=True)
    source_file = fields.Binary('Excel del batch', attachment=True,
                                help='Solo en modo "Simular API": el Excel de VentePriveeSync.')
    source_filename = fields.Char()
    state = fields.Selection([
        ('new', 'Nuevo'),
        ('downloaded', 'Descargado'),
        ('creating', 'Creando pedidos'),
        ('done', 'Pedidos creados'),
        ('review', 'Revisar'),
        ('closed', 'Cerrado en Veepee'),
        ('cancel', 'Cancelado'),
    ], default='new', tracking=True)
    order_line_ids = fields.One2many('vp.dropship.order', 'batch_id', 'Pedidos del batch')
    sale_ids = fields.One2many('sale.order', 'dp_batch_id', 'Pedidos de venta')
    n_orders = fields.Integer('Pedidos', compute='_compute_counts')
    n_units = fields.Float('Unidades', compute='_compute_counts')
    n_created = fields.Integer('Creados', compute='_compute_counts')
    n_error = fields.Integer('Con errores', compute='_compute_counts')
    n_pending = fields.Integer('Pendientes', compute='_compute_counts')
    create_job_uuid = fields.Char('Job de creación', readonly=True, copy=False)
    int_batch_id = fields.Many2one('stock.picking.batch', 'Agrupación de las INT', readonly=True, copy=False,
                                   help='"<campaña> - <batch>" con todas las INT al SORTER del batch.')

    _sql_constraints = [('batch_uniq', 'unique(config_id, operation_ref, batch_ref)', 'Batch ya descargado.')]

    @api.depends('operation_code', 'batch_ref')
    def _compute_name(self):
        for b in self:
            b.name = '%s / %s' % (b.operation_code or '?', b.batch_ref)

    @api.depends('order_line_ids.state', 'order_line_ids.units')
    def _compute_counts(self):
        for b in self:
            lines = b.order_line_ids
            b.n_orders = len(lines)
            b.n_units = sum(lines.mapped('units'))
            b.n_created = len(lines.filtered(lambda l: l.state in ('created', 'exists')))
            b.n_error = len(lines.filtered(lambda l: l.state == 'error'))
            b.n_pending = len(lines.filtered(lambda l: l.state == 'pending'))

    # ------------------------------------------------------------------
    def _rows(self, api=None):
        self.ensure_one()
        config = self.config_id
        if config.simulate_api:
            if not self.source_file:
                raise UserError(_('Sube el Excel del batch (modo "Simular API").'))
            import base64
            return vp_parse.rows_from_xlsx(base64.b64decode(self.source_file))
        if api is None:
            api = config._api()
            api.login()
        data = api.batch(self.operation_ref, self.batch_ref)
        import base64
        # Odoo 13: ir.attachment no té 'raw' (és de la 14), cal 'datas' en base64
        self.env['ir.attachment'].create({
            'name': 'veepee_%s_%s.json' % (self.operation_code, self.batch_ref),
            'res_model': self._name, 'res_id': self.id, 'mimetype': 'application/json',
            'datas': base64.b64encode(json.dumps(data, ensure_ascii=False, indent=1).encode('utf-8')),
        })
        # que la resposta de Veepee es quedi guardada encara que després falli la lectura
        self.env.cr.commit()
        return vp_parse.rows_from_api(data, self.operation_code, self.batch_ref)

    def action_download(self):
        for batch in self:
            batch._download()
        return True

    def _download(self, api=None):
        """Llegeix el batch (API o Excel) i crea una línia per comanda, ja validada."""
        self.ensure_one()
        if self.sale_ids:
            raise UserError(_('El batch ya tiene pedidos creados: no se vuelve a descargar.'))
        rows = self._rows(api=api)
        if not rows:
            raise UserError(_('El batch no tiene líneas.'))
        if self.config_id.simulate_api and rows[0].get('LI_Intitule'):
            parts = rows[0]['LI_Intitule'].split('#')
            if not self.operation_code and parts:
                self.operation_code = parts[0]
        self.order_line_ids.unlink()
        Order = self.env['vp.dropship.order']
        for o in vp_parse.group_orders(rows).values():
            Order.create({
                'batch_id': self.id,
                'name': o['name'],
                'intitule': o['intitule'],
                'carrier_key': o['carrier_key'],
                'units': sum(l['qty'] for l in o['lines']),
                'n_lines': len(o['lines']),
                'data': json.dumps(o['lines']),
            })
        self.state = 'downloaded'
        self.message_post(body=_('Descargado: %s pedidos, %s unidades.') % (self.n_orders, self.n_units))
        self._check()
        if self.n_error:
            self._notify_errors()
        return True

    def action_check(self):
        for batch in self:
            batch._check()
        return True

    def _lookups(self, orders):
        """Precarrega productes, preus i transportistes per validar el batch de cop."""
        config = self.config_id
        eans = set()
        for o in orders:
            for line in json.loads(o.data or '[]'):
                eans.update(line.get('eans') or [line.get('ean')])
        eans.discard('')
        eans.discard(None)
        products = {}
        if eans:
            for p in self.env['product.product'].search_read([('barcode', 'in', list(eans))], ['barcode']):
                products.setdefault(p['barcode'], p['id'])
        prices = {}
        Price = self.env['vp.dropship.price']
        for campaign in ('', self.operation_code or ''):   # la de la campanya mana sobre la genèrica
            domain = [('barcode', 'in', list(eans))]
            domain.append(('campaign', '=', campaign) if campaign else ('campaign', 'in', ('', False)))
            for p in Price.search_read(domain, ['barcode', 'price_es', 'price_fr_benelux', 'price_it']):
                prices[p['barcode']] = p
        mapping = {c.key: (c.carrier_id.id, c.tarifa) for c in config.carrier_ids}

        def find_product(line_eans):
            for e in line_eans or []:
                if e in products:
                    return products[e]
            return None

        def find_carrier(key):
            if key in mapping:
                return mapping[key]
            return (None, None)

        def find_price(ean, tarifa):
            p = prices.get(ean)
            if not p:
                return None
            value = p.get('price_%s' % tarifa)
            return value if value else None

        return find_product, find_carrier, find_price

    def _check(self):
        """(Re)valida les comandes pendents o amb error: producte, transportista i preu."""
        self.ensure_one()
        orders = self.order_line_ids.filtered(lambda o: o.state in ('pending', 'error'))
        if not orders:
            return
        find_product, find_carrier, find_price = self._lookups(orders)
        existing = set(self.env['sale.order'].search([('name', 'in', orders.mapped('name'))]).mapped('name'))
        for o in orders:
            lines = json.loads(o.data or '[]')
            rows = []
            for line in lines:
                rows.append({'PE': o.name[3:], 'EAN_Code': line.get('ean'), 'EANS': line.get('eans'),
                             'Product_Code': line.get('product_code'), 'QTY': line.get('qty'),
                             'LI_Intitule': o.intitule, 'LI_Pays': o.carrier_key})
            plan = vp_parse.plan_orders(rows, find_product, find_carrier, find_price, existing,
                                        require_price=self.config_id.use_price_file)[0]
            vals = {'carrier_id': plan['carrier_id'], 'tarifa': plan['tarifa'] or False,
                    'data': json.dumps(plan['lines'])}
            if plan['exists']:
                vals.update(state='exists', error=_('Ya existe un pedido %s en Odoo.') % o.name,
                            sale_id=self.env['sale.order'].search([('name', '=', o.name)], limit=1).id)
            elif plan['errors']:
                vals.update(state='error', error='\n'.join(plan['errors']))
            else:
                vals.update(state='pending', error=False)
            o.write(vals)
        if self.n_error:
            self.state = 'review'
            self.message_post(body=_('%s pedidos con errores (ver pestaña Pedidos del batch).') % self.n_error)
        elif self.state == 'review':
            self.state = 'downloaded'

    # ------------------------------------------------------------------
    def _job_running(self, uuid):
        """El job encara és viu (pendent, a la cua o en marxa des de fa poc)."""
        if not uuid:
            return False
        qjob = self.env['queue.job'].sudo().search([('uuid', '=', uuid)], limit=1)
        if qjob.state in ('pending', 'enqueued'):
            return True
        return (qjob.state == 'started' and qjob.date_started
                and qjob.date_started > fields.Datetime.now() - timedelta(minutes=JOB_STALE_MINUTES))

    def _enqueue_create_orders(self):
        qjob = self.with_delay(description=_('Veepee DP: crear pedidos %s') % self.name)._job_create_orders()
        self.create_job_uuid = qjob.uuid

    def action_create_orders(self):
        """Crea totes les comandes pendents en segon pla, en lots encadenats de JOB_ORDERS."""
        self.ensure_one()
        if self._job_running(self.create_job_uuid):
            raise UserError(_('Los pedidos de este batch ya se están creando en segundo plano.'))
        self._enqueue_create_orders()
        self.message_post(body=_('Creando %s pedidos en segundo plano (lotes de %s). '
                                 'Recarga la página para ver el avance.') % (self.n_pending, JOB_ORDERS))
        return True

    @_as_job
    def _job_create_orders(self):
        self.ensure_one()
        if self.state not in ('downloaded', 'creating', 'review'):
            return _('Batch en estado %s: no se crea nada.') % self.state
        deadline = time.time() + min(self.config_id.max_seconds or 240, 240)
        done = self._create_orders(deadline, limit=JOB_ORDERS)
        pending = len(self.order_line_ids.filtered(lambda o: o.state == 'pending'))
        if pending:
            self._enqueue_create_orders()
        return _('Creados: %s · pendientes: %s') % (done, pending)

    def _update_veepee_ids(self, orders):
        """Pas 'Actualització Dropshipping Veepee Product ID': cada variant amb el seu id de Veepee."""
        config = self.config_id
        field = config.veepee_field
        Product = self.env['product.product']
        if not (config.update_veepee_ids and field and field in Product._fields):
            return 0
        by_product = {}
        for o in orders:
            for line in json.loads(o.data or '[]'):
                if line.get('product_id') and line.get('veepee_id'):
                    by_product[line['product_id']] = line['veepee_id']
        changed = 0
        for product in Product.browse(list(by_product)):
            if (product[field] or '') != by_product[product.id]:
                product.write({field: by_product[product.id]})
                changed += 1
        return changed

    def _order_vals(self, o):
        config = self.config_id
        lines = json.loads(o.data or '[]')
        Product = self.env['product.product']
        tax_ids = config.tax_ids.ids
        use_prices = config.use_price_file   # si no: tot a 0, el preu es posa en acabar la campanya
        order_lines = []
        for line in lines:
            product = Product.browse(line['product_id'])
            order_lines.append((0, 0, {
                'product_id': product.id,
                'name': product.get_product_multiline_description_sale() or product.display_name,
                'product_uom_qty': line['qty'],
                'product_uom': product.uom_id.id,
                'price_unit': (line.get('price') or 0.0) if use_prices else 0.0,
                'tax_id': [(6, 0, tax_ids)],
            }))
        local = TZ.localize(datetime.combine(self.batch_date or fields.Date.context_today(self),
                                             datetime.min.time()) + timedelta(days=config.delivery_days))
        vals = {
            'name': o.name,
            'company_id': config.company_id.id,
            'partner_id': config.partner_id.id,
            'pricelist_id': config._pricelist(o.tarifa).id,
            'ref_remarks': o.intitule,
            'commitment_date': local.astimezone(pytz.utc).replace(tzinfo=None),
            'carrier_id': o.carrier_id.id,
            'picking_policy': 'direct',
            'order_line': order_lines,
            'dp_batch_id': self.id,
        }
        optional = {
            'partner_shipping_id': config.partner_shipping_id.id,
            'warehouse_id': config.warehouse_id.id,
            's_order_type_id': config.order_type_id.id,
            'season_id': config.season_id.id,
            'brand_id': config.brand_id.id,
            'team_id': config.team_id.id,
            'user_id': config.user_id.id,
            'payment_mode_id': config.payment_mode_id.id,
            'payment_term_id': config.payment_term_id.id,
        }
        vals.update({k: v for k, v in optional.items() if v})
        return vals

    def _create_orders(self, deadline, limit=None):
        """Crea les comandes pendents una a una (commit després de cada una) fins a deadline
        o fins a 'limit' comandes."""
        self.ensure_one()
        config = self.config_id
        if not config.partner_id:
            raise UserError(_('Falta el cliente en la configuración.'))
        missing = [t for t in ('es', 'fr_benelux', 'it')
                   if t in self.order_line_ids.mapped('tarifa') and not config._pricelist(t)]
        if missing:
            raise UserError(_('Faltan tarifas en la configuración: %s') % ', '.join(missing))
        pending = self.order_line_ids.filtered(lambda o: o.state == 'pending')
        if self.state in ('downloaded', 'review'):
            changed = self._update_veepee_ids(self.order_line_ids.filtered(lambda o: o.state != 'error'))
            self.write({'state': 'creating'})
            self.message_post(body=_('Variantes con el Dropshipping Veepee Product ID actualizado: %s') % changed)
            self.env.cr.commit()
        SaleOrder = self.env['sale.order']
        done = failed = 0
        for o in pending:
            if time.time() > deadline or (limit and done + failed >= limit):
                break
            if SaleOrder.search_count([('name', '=', o.name)]):
                o.write({'state': 'exists', 'sale_id': SaleOrder.search([('name', '=', o.name)], limit=1).id})
                self.env.cr.commit()
                continue
            try:
                sale = SaleOrder.create(self._order_vals(o))
                # el create (sales_ext) deixa el modo de pago buit (el client no en té): el de la configuració
                if config.payment_mode_id and sale.payment_mode_id != config.payment_mode_id:
                    sale.payment_mode_id = config.payment_mode_id
                o.write({'state': 'created', 'sale_id': sale.id, 'error': False})
                self.env.cr.commit()
                done += 1
            except Exception as e:
                self.env.cr.rollback()
                o.write({'state': 'error', 'error': str(e)[:1000]})
                self.env.cr.commit()
                failed += 1
        if failed:
            self._notify_errors()
        if not self.order_line_ids.filtered(lambda l: l.state == 'pending'):
            self.state = 'review' if self.n_error else 'done'
            self.message_post(body=_('Pedidos creados: %s · con errores: %s') % (self.n_created, self.n_error))
            self.env.cr.commit()
        return done

    def action_close_veepee(self):
        """Tanca el batch a Veepee (el botó 'Cerrar Batch' de VentePriveeSync)."""
        self.ensure_one()
        if self.config_id.simulate_api:
            self.state = 'closed'
            self.message_post(body=_('SIMULACIÓN: batch marcado como cerrado (no se llama a Veepee).'))
            return True
        api = self.config_id._api()
        try:
            api.login()
            api.close_batch(self.operation_ref, self.batch_ref)
        except VeepeeApiError as e:
            raise UserError(str(e))
        self.state = 'closed'
        self.message_post(body=_('Batch cerrado en Veepee.'))
        return True

    def action_view_sales(self):
        return {
            'type': 'ir.actions.act_window', 'name': _('Pedidos'),
            'res_model': 'sale.order', 'view_mode': 'tree,form',
            'domain': [('dp_batch_id', '=', self.id)],
        }

    def _notify_errors(self):
        config = self.config_id
        if not config.notify_emails:
            return
        errors = self.order_line_ids.filtered(lambda o: o.state == 'error')
        rows = ''.join('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            o.name, o.carrier_key, (o.error or '').replace('\n', '<br/>')) for o in errors[:300])
        body = _('<p>Batch <b>%s</b>: %s pedidos, %s con errores (no se han creado).</p>'
                 '<table border="1" cellpadding="4" style="border-collapse:collapse">'
                 '<tr><th>Pedido</th><th>Transportista</th><th>Error</th></tr>%s</table>'
                 '<p>Corrige el mapeo de transportistas o los precios y pulsa "Volver a validar" en el batch.</p>') % (
            self.name, self.n_orders, self.n_error, rows)
        self.env['mail.mail'].sudo().create({
            'subject': _('Veepee DP: batch %s con %s pedidos sin crear') % (self.name, self.n_error),
            'email_from': config.email_from,
            'email_to': config.notify_emails,
            'mail_server_id': config.mail_server_id.id,
            'body_html': body,
            'auto_delete': False,
        })


class VpDropshipOrder(models.Model):
    _name = 'vp.dropship.order'
    _description = 'Dropshipping Veepee: pedido del batch'
    _order = 'id'

    batch_id = fields.Many2one('vp.dropship.batch', required=True, ondelete='cascade', index=True)
    name = fields.Char('Pedido', required=True, index=True)
    intitule = fields.Char('Remarks (LI_Intitule)')
    carrier_key = fields.Char('LI_Pays')
    carrier_id = fields.Many2one('delivery.carrier', 'Transportista')
    tarifa = fields.Selection(TARIFA_SELECTION, 'Tarifa')
    n_lines = fields.Integer('Líneas')
    units = fields.Float('Unidades')
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('error', 'Error'),
        ('created', 'Creado'),
        ('exists', 'Ya existía'),
    ], default='pending', index=True)
    error = fields.Text('Error')
    sale_id = fields.Many2one('sale.order', 'Pedido de venta')
    data = fields.Text('Líneas (JSON)')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    dp_batch_id = fields.Many2one('vp.dropship.batch', 'Batch Veepee', index=True, copy=False)
