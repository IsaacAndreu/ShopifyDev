"""Fase 2 de les devolucions VP: transport, missatge a la clienta per PinkConnect,
acceptació a VP i recepció.

Ordre (cada pas queda desat abans del següent; en reintentar es continua pel que falta):
1. TT/DEV (vp_returns.py), només amb els articles que demana VP.
2. Etiqueta: ES = Nacex 44 eDevolución oberta (com Shopify); FR = FedEx amb recollida a domicili
   l'endemà feiner i «PREVENIR A L'AVANCE». Si FedEx no accepta la recollida, s'atura (sense
   passar a entrega a punt com fa Shopify).
3. Missatge a VP (POST /orders/{id}/notifications) amb l'etiqueta adjunta.
4. ES: el registre «Recogida a domicilio» de PinkConnect encara no té API documentada: es fa a mà
   i es marca la casella abans d'acceptar.
5. PUT /return-requests/{id}/PROCESSING línia per línia, rellegint-ne l'estat. Mai COMPLETE.
6. Quan el magatzem valida la TT/DEV: Recibida. La rectificativa la crea PinkConnect sol
   (facturació automàtica de stock_picking.action_done): aquí no se'n fa cap.
"""
import base64
import logging
import time

import requests

from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.addons.nath_shopify_returns.models.fedex_return import next_business_day

_logger = logging.getLogger(__name__)

FEDEX_PICKUP_REMARKS = "PREVENIR A L'AVANCE"

MSG_ES_SUBJECT = 'Devolución de paquete Tuc Tuc en punto de recogida cercano'
MSG_ES_BODY = ('Hola, le adjuntamos la etiqueta de NACEX para devolver el paquete en cualquier punto '
               'NACEX.shop cercano: imprímala y péguela en el paquete cerrado. En cuanto lo recibamos, '
               'le devolveremos el dinero. Muchas gracias.')
MSG_FR_SUBJECT = 'Instructions pour votre retour — Commande {referencia}'
MSG_FR_BODY = ("Chère cliente, Cher client,\n\n"
               "Pour procéder au retour, veuillez coller l'étiquette FedEx jointe sur votre colis fermé, "
               "puis le remettre au transporteur lors de son passage prévu le {date_collecte}, "
               "entre {heure_debut} et {heure_fin}.\n\n"
               "Si vous avez la moindre question ou si le transporteur ne se présente pas, "
               "n'hésitez pas à nous en informer.\n\n"
               "Nous restons à votre entière disposition.\n\n"
               "Bien cordialement,\nL'équipe du Service Client")


class _Lines(list):
    """Imita el recordset de línies que esperen els mètodes FedEx del mòdul Shopify."""
    def filtered(self, func):
        return self

    def mapped(self, name):
        return [getattr(line, name) for line in self]


class _Line(object):
    def __init__(self, quantity):
        self.quantity = quantity


class _CarrierData(object):
    """Les dades que els mètodes Nacex/FedEx de nath_shopify_returns llegeixen del registre
    de devolució Shopify, preses de la devolució VP (així es fa servir el mateix codi)."""

    def __init__(self, ret):
        partner = ret.sale_id.partner_shipping_id
        self.config_id = ret.config_id.transport_config_id
        self.dev_picking_id = ret.dev_picking_id
        self.remarks = ret.sale_id.name
        self.partner_name = partner.name
        self.phone = partner.mobile or partner.phone
        self.email = partner.email
        self.street = ' '.join(filter(None, [partner.street, partner.street2]))
        self.city = partner.city
        self.zip = partner.zip
        self.country_code = partner.country_id.code
        self.nacex_shop_code = False
        self.line_ids = _Lines(_Line(q) for q in ret.request_ids.mapped('quantity'))
        self.amount_expected = ret._returned_amount()
        self.currency_code = ret.sale_id.currency_id.name or 'EUR'


class _SafeDict(dict):
    def __missing__(self, key):
        return '{%s}' % key


class VPReturnConfig(models.Model):
    _inherit = 'vp.return.config'

    transport_config_id = fields.Many2one(
        'shopify.return.config', 'Parámetros de transporte',
        help='Almacén de destino, peso, medidas y horario de recogida FedEx: los mismos que '
             'las devoluciones Shopify.')
    nacex_carrier_id = fields.Many2one(
        'delivery.carrier', 'Transportista ES (Nacex 44)', domain=[('delivery_type', '=', 'nacex')],
        help='eDevoluciones 44 Nacex (devoluciones web). Nunca el transportista del OUT.')
    fedex_carrier_id = fields.Many2one(
        'delivery.carrier', 'Transportista FR (FedEx)', domain=[('delivery_type', '=', 'fedex_rest')],
        help='Fedex Rest. Nunca el «Fedex» antiguo del OUT.')
    msg_es_subject = fields.Char('Asunto ES', default=MSG_ES_SUBJECT)
    msg_es_body = fields.Text('Mensaje ES', default=MSG_ES_BODY)
    msg_fr_subject = fields.Char('Asunto FR', default=MSG_FR_SUBJECT,
                                 help='{referencia} = número de pedido de VP.')
    msg_fr_body = fields.Text('Mensaje FR', default=MSG_FR_BODY,
                              help='{referencia}, {date_collecte}, {heure_debut} y {heure_fin} '
                                   'se rellenan con los datos reales de la recogida.')

    def _pink_send(self, method, path, expect=(200, 201, 204), **kwargs):
        """Crida que modifica PinkConnect. Sense reintents: si hi ha timeout, qui crida decideix."""
        base, headers = self._pink_base()
        response = requests.request(method, base + path, headers=headers, timeout=(10, 60),
                                    allow_redirects=False, **kwargs)
        if response.status_code not in expect:
            raise UserError(_('PinkConnect %s %s: HTTP %s %s')
                            % (method, path, response.status_code, (response.text or '')[:500]))
        return response


class VPReturnRequest(models.Model):
    _inherit = 'vp.return.request'

    accepted_date = fields.Datetime('Aceptada en VP', readonly=True)


class VPReturn(models.Model):
    _inherit = 'vp.return'

    carrier_kind = fields.Selection([('nacex', 'Nacex'), ('fedex', 'FedEx')], 'Transporte', readonly=True)
    tracking_ref = fields.Char('Seguimiento', readonly=True, copy=False)
    nacex_cod_exp = fields.Char('Expedición Nacex', readonly=True, copy=False)
    pickup_code = fields.Char('Recogida FedEx', readonly=True, copy=False)
    pickup_date = fields.Date('Fecha de recogida', readonly=True, copy=False)
    label_attachment_id = fields.Many2one('ir.attachment', 'Etiqueta', readonly=True, copy=False)
    notification_state = fields.Selection(
        [('none', 'No enviado'), ('sending', 'Enviando (comprobar)'), ('sent', 'Enviado')],
        'Mensaje a VP', default='none', required=True, readonly=True, copy=False)
    notification_ref = fields.Char('ID mensaje VP', readonly=True, copy=False)
    es_pickup_done = fields.Boolean(
        'Recogida registrada en VP',
        help='Solo España: el registro «Recogida a domicilio» (Tracking «Entrega a punto», Agencia NACEX) '
             'se crea a mano en PinkConnect. Márcalo cuando esté hecho y vuelve a «Procesar».')
    received_date = fields.Datetime('Recibida', readonly=True, copy=False)

    # ------------------------------------------------------------------
    def _progress_state(self):
        reqs = self.request_ids
        if self.received_date:
            return 'received'
        if reqs and all(r.remote_status in ('PROCESSING', 'COMPLETE') for r in reqs) and self.notification_state == 'sent':
            return 'accepted'
        if self.notification_state == 'sent':
            return 'notified'
        if self.tracking_ref and (self.carrier_kind != 'fedex' or self.pickup_code):
            return 'label'
        if self.dev_picking_id:
            return 'dev_created'
        return 'validated'

    def _checkpoint(self):
        """Desa el pas fet (ja hi ha coses creades fora d'Odoo) i torna a bloquejar la fila."""
        self.write({'state': self._progress_state(), 'error_msg': False})
        self.env.cr.commit()
        self.env.cr.execute('SELECT id FROM vp_return WHERE id = %s FOR UPDATE NOWAIT', (self.id,))

    def _country(self):
        return (self.sale_id.partner_shipping_id.country_id.code or '').upper()

    def _carrier(self):
        config = self.config_id
        return config.nacex_carrier_id if self._country() == 'ES' else config.fedex_carrier_id

    def _returned_amount(self):
        total = 0.0
        for req in self.request_ids:
            line = self.sale_id.order_line.filtered(lambda l: l.product_id == req.product_id)[:1]
            if line and line.product_uom_qty:
                total += line.price_total / line.product_uom_qty * req.quantity
        return round(total, 2) or 1.0

    def _check_ready(self):
        config = self.config_id
        country = self._country()
        if country not in ('ES', 'FR'):
            raise UserError(_('País %s: el circuito solo contempla España y Francia.') % (country or '?'))
        if not config.return_location_id:
            raise UserError(_('Falta la ubicación de devolución en la configuración.'))
        if not config.transport_config_id.dest_partner_id:
            raise UserError(_('Falta «Parámetros de transporte» (con el almacén de destino) en la configuración.'))
        carrier = self._carrier()
        if not carrier:
            raise UserError(_('Falta el transportista de %s en la configuración.') % country)
        if carrier.company_id and carrier.company_id != self.sale_id.company_id:
            raise UserError(_('El transportista %s es de otra compañía que el pedido %s.')
                            % (carrier.name, self.sale_id.name))
        partner = self.sale_id.partner_shipping_id
        if country == 'FR' and not (partner.street and partner.zip and partner.city and (partner.mobile or partner.phone)):
            raise UserError(_('Faltan la dirección o el teléfono de la clienta para la recogida FedEx.'))

    def _reference(self):
        """El número de comanda que coneix la clienta (VP); si no hi és, el de la comanda d'Odoo."""
        numbers = [n for n in self.request_ids.mapped('marketplace_order_number') if n]
        return numbers[0] if numbers else self.sale_id.name

    def _message(self):
        config = self.config_id
        if self._country() == 'ES':
            return config.msg_es_subject or MSG_ES_SUBJECT, config.msg_es_body or MSG_ES_BODY
        transport = config.transport_config_id
        values = _SafeDict(referencia=self._reference(),
                           date_collecte=(self.pickup_date or next_business_day()).strftime('%d/%m/%Y'),
                           heure_debut=transport.fedex_pickup_from or '12:00',
                           heure_fin=transport.fedex_pickup_to or '18:00')
        return ((config.msg_fr_subject or MSG_FR_SUBJECT).format_map(values),
                (config.msg_fr_body or MSG_FR_BODY).format_map(values))

    # ------------------------------------------------------------------
    def _run_flow(self):
        self.ensure_one()
        self._check_ready()
        self._step_validate()
        if not self.dev_picking_id:
            # Abans de crear res: totes les peces han d'estar pendents a VP
            reqs = self.request_ids
            other = reqs.filtered(lambda r: r.remote_status != 'PENDING')
            if other:
                raise UserError(_('Hay artículos que ya no están PENDING en VP (%s): gestionar a mano.')
                                % ', '.join(set(other.mapped('remote_status'))))
        if self.config_id.simulate:
            self._simulate()
            self.write({'state': self._progress_state(), 'error_msg': False})
            return
        if not self.dev_picking_id:
            self._step_create_dev()
            self._checkpoint()
        if not self.tracking_ref:
            self._step_transport()
        if self.carrier_kind == 'fedex' and not self.pickup_code:
            self._step_fedex_pickup()
        if self.notification_state != 'sent':
            self._step_message()
        if self._country() == 'ES' and not self.es_pickup_done:
            self.message_post(body=_('Falta crear en PinkConnect la «Recogida a domicilio» (Tracking «Entrega a '
                                     'punto», Agencia NACEX). Cuando esté, marcar «Recogida registrada en VP» '
                                     'y volver a «Procesar».'))
            self._checkpoint()
            return
        self._step_accept()
        self._checkpoint()

    def _simulate(self):
        data = _CarrierData(self)
        carrier = self._carrier()
        subject, body = self._message()
        if self._country() == 'ES':
            transport = _('%s: genEtiquetaDevolucion (eDevolución abierta, ref. TT/DEV, obs. %s)') % (
                carrier.name, data.remarks)
        else:
            tr = self.config_id.transport_config_id
            transport = _('%s: envío de importación (clienta → %s), recogida a domicilio el %s de %s a %s, '
                          'instrucción «%s»') % (carrier.name, tr.dest_partner_id.display_name,
                                                 next_business_day().strftime('%d/%m/%Y'),
                                                 tr.fedex_pickup_from, tr.fedex_pickup_to, FEDEX_PICKUP_REMARKS)
        pending = self.request_ids.filtered(lambda r: r.remote_status == 'PENDING')
        steps = [
            _('1. TT/DEV:<br/>%s') % (self.preview or '').replace('\n', '<br/>'),
            _('2. Etiqueta: %s') % transport,
            _('3. Mensaje a VP con la etiqueta adjunta:<br/><b>%s</b><br/>%s') % (subject, body.replace('\n', '<br/>')),
        ]
        if self._country() == 'ES':
            steps.append(_('4. A mano en PinkConnect: «Recogida a domicilio», Tracking «Entrega a punto», '
                           'Agencia NACEX; marcar «Recogida registrada en VP».'))
        steps.append(_('%s. Aceptar en VP (PROCESSING) y comprobar: %s') % (
            5 if self._country() == 'ES' else 4, ', '.join('%s x %s' % (r.quantity, r.product_id.display_name)
                                                           for r in pending) or '-'))
        self.message_post(body=_('[SIMULACIÓN] No se ha creado ni enviado nada.<br/>') + '<br/>'.join(steps))

    # ------------------------------------------------------------------
    def _attach_label(self, name, datas_b64):
        att = self.env['ir.attachment'].create({
            'name': name, 'datas': datas_b64, 'res_model': self._name, 'res_id': self.id,
            'mimetype': 'application/pdf'})
        self.label_attachment_id = att
        return att

    def _step_transport(self):
        data = _CarrierData(self)
        carrier = self._carrier()
        if self._country() == 'ES':
            cod_exp, pdf = carrier.nacex_gen_return_label(data)
            self.write({'carrier_kind': 'nacex', 'nacex_cod_exp': cod_exp, 'tracking_ref': cod_exp})
            self._attach_label('Nacex devolucion %s.pdf' % self.sale_id.name, base64.b64encode(pdf))
            self._checkpoint()      # l'etiqueta ja existeix a Nacex: que no es perdi
            albaran = self._nacex_wait_albaran(carrier, cod_exp)
            self.tracking_ref = albaran
            msg = _('Etiqueta Nacex creada: %s (exp. %s)') % (albaran, cod_exp)
        else:
            tracking, label = carrier.fedex_return_create(data, True)
            self.write({'carrier_kind': 'fedex', 'tracking_ref': tracking})
            if label:
                self._attach_label('FedEx devolucion %s.pdf' % self.sale_id.name, label)
            msg = _('Envío FedEx creado: %s') % tracking
        self.dev_picking_id.write({'carrier_tracking_ref': self.tracking_ref})
        self.message_post(body=msg)
        self.dev_picking_id.message_post(body=msg)
        self._checkpoint()
        if not self.label_attachment_id:
            raise UserError(_('El transportista no ha devuelto la etiqueta PDF (%s): no se envía el mensaje.')
                            % self.tracking_ref)

    def _nacex_wait_albaran(self, carrier, cod_exp, tries=5, wait=3):
        """Com a Shopify: Nacex dona l'albarà uns segons després de l'etiqueta oberta."""
        for attempt in range(tries):
            if attempt:
                time.sleep(wait)
            try:
                albaran = carrier.nacex_get_status(cod_exp)[2]
            except Exception as e:
                _logger.info('Albarán Nacex %s: %s', self.sale_id.name, e)
                continue
            if albaran:
                return albaran
        return cod_exp

    def _step_fedex_pickup(self):
        carrier = self._carrier()
        payload = carrier.fedex_return_pickup_payload(_CarrierData(self), self.tracking_ref)
        payload['remarks'] = FEDEX_PICKUP_REMARKS
        day = next_business_day()
        out = carrier._fedex_post('/pickup/v1/pickups', payload)
        code = (out.get('output') or {}).get('pickupConfirmationCode')
        if not code:
            raise UserError(_('FedEx no ha confirmado la recogida (envío %s): revisar.') % self.tracking_ref)
        self.write({'pickup_code': code, 'pickup_date': day})
        tr = self.config_id.transport_config_id
        msg = _('Recogida FedEx %s: %s de %s a %s («%s»)') % (
            code, day.strftime('%d/%m/%Y'), tr.fedex_pickup_from, tr.fedex_pickup_to, FEDEX_PICKUP_REMARKS)
        self.message_post(body=msg)
        self.dev_picking_id.message_post(body=msg)
        self._checkpoint()

    # ------------------------------------------------------------------
    def _find_notification(self, subject):
        """Missatges de la comanda a PinkConnect: per no enviar-lo dues vegades després d'un timeout."""
        base, headers = self.config_id._pink_base()
        try:
            response = requests.get(base + '/notifications', headers=headers, params={'orderId': self.order_id},
                                    timeout=(10, 45), allow_redirects=False)
            data = response.json() if response.status_code == 200 else None
        except (requests.RequestException, ValueError):
            data = None
        if data is None:
            raise UserError(_('No se sabe si VP recibió el mensaje y no se pueden leer sus mensajes: '
                              'mirarlo en PinkConnect antes de reintentar.'))
        items = data if isinstance(data, list) else (data.get('items') or data.get('data') or []) \
            if isinstance(data, dict) else []
        for item in items:
            if isinstance(item, dict) and (item.get('subject') or '').strip() == subject.strip():
                return str(item.get('id') or item.get('notificationId') or '?')
        return False

    def _step_message(self):
        subject, body = self._message()
        if self.notification_state == 'sending':
            found = self._find_notification(subject)
            if found:
                self.write({'notification_state': 'sent', 'notification_ref': found})
                self.message_post(body=_('El mensaje ya estaba en VP (%s): no se vuelve a enviar.') % found)
                self._checkpoint()
                return
        att = self.label_attachment_id
        if not att:
            raise UserError(_('No hay etiqueta para adjuntar al mensaje.'))
        self.notification_state = 'sending'
        self._checkpoint()
        try:
            response = self.config_id._pink_send(
                'POST', '/orders/%s/notifications' % self.order_id,
                data={'subject': subject, 'message': body},
                files={'attachedFile': (att.name, base64.b64decode(att.datas), 'application/pdf')})
        except requests.RequestException as e:
            raise UserError(_('Sin respuesta de VP al enviar el mensaje (%s): al reintentar se comprueba '
                              'si llegó.') % e)
        try:
            ref = str((response.json() or {}).get('id') or '')
        except (ValueError, AttributeError):
            ref = ''
        self.write({'notification_state': 'sent', 'notification_ref': ref or 'HTTP %s' % response.status_code})
        self.message_post(body=_('Mensaje enviado a VP con la etiqueta: <b>%s</b>') % subject,
                          attachment_ids=[att.id])
        self._checkpoint()

    def _refresh_requests(self):
        config = self.config_id
        config._upsert_rows(config._api_get({'orderId': self.order_id, 'limit': 50}))

    def _step_accept(self):
        """Una a una; després de cada PUT es rellegeix l'estat. Si alguna surt COMPLETE, s'atura."""
        self._refresh_requests()
        for req in self.request_ids.sorted('id'):
            if req.remote_status == 'PROCESSING':
                continue
            if req.remote_status != 'PENDING':
                raise UserError(_('%s está %s en VP: revisar a mano.') % (req.product_id.display_name,
                                                                         req.remote_status))
            try:
                self.config_id._pink_send('PUT', '/return-requests/%s/PROCESSING' % req.remote_id)
            except requests.RequestException as e:
                raise UserError(_('Sin respuesta de VP al aceptar %s (%s): al reintentar se relee el estado.')
                                % (req.product_id.display_name, e))
            self._refresh_requests()
            if req.remote_status != 'PROCESSING':
                raise UserError(_('Tras aceptar %s, VP la muestra %s: revisar a mano.')
                                % (req.product_id.display_name, req.remote_status))
            req.accepted_date = fields.Datetime.now()
            self.message_post(body=_('Aceptada en VP: %s x %s') % (req.quantity, req.product_id.display_name))
            self._checkpoint()

    # ------------------------------------------------------------------
    def _on_dev_received(self):
        """El magatzem ha validat la TT/DEV. La rectificativa la fa PinkConnect (no se'n crea cap)."""
        for rec in self:
            vals = {'received_date': fields.Datetime.now()}
            if rec.state == 'accepted':
                vals['state'] = 'received'
                rec.message_post(body=_('TT/DEV %s validada: recibida. La rectificativa la crea PinkConnect.')
                                 % rec.dev_picking_id.name)
            else:
                rec.message_post(body=_('TT/DEV %s validada con la devolución en estado «%s»: revisar.')
                                 % (rec.dev_picking_id.name, dict(rec._fields['state'].selection)[rec.state]))
            rec.write(vals)
