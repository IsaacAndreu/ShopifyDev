# -*- coding: utf-8 -*-
import base64
import logging

import requests
from urllib.parse import quote

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _clean(value, size=None):
    """El '|' és el separador de Nacex: no pot anar dins d'un valor."""
    value = (value or '').replace('|', ' ').replace('\n', ' ').strip()
    return value[:size] if size else value


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    tip_ser = fields.Selection(selection_add=[('44', 'eDevoluciones SHOP 44')])

    # ------------------------------------------------------------------
    # Crida genèrica al WS de Nacex
    # ------------------------------------------------------------------
    def _nacex_ws_call(self, method, data, timeout=60):
        """Mateix format d'URL que delivery_nacex (data amb '=' i '|' sense codificar),
        però codificant '#', espais i accents perquè no tallin la URL."""
        self.ensure_one()
        url = '%s?method=%s&data=%s&user=%s&pass=%s' % (
            self.nacex_api_url, method,
            quote(data, safe='=|/:,.-_'),
            quote(self.nacex_user_name or '', safe=''),
            quote(self.nacex_user_pass or '', safe=''))
        try:
            resp = requests.get(url, timeout=timeout)
        except requests.RequestException as e:
            raise Exception('Nacex %s: error de conexión: %s' % (method, e))
        text = (resp.text or '').strip()
        if method != 'getEtiqueta':
            _logger.info('Nacex %s respuesta: %s', method, text[:500])
        if resp.status_code not in (200, 201):
            raise Exception('Nacex %s: HTTP %s %s' % (method, resp.status_code, text[:500]))
        if not text:
            raise UserError(_('Nacex %s: respuesta vacía.') % method)
        if text.upper().startswith('ERROR'):
            # Error de negoci de Nacex -> revisió manual
            raise UserError(_('Nacex %s: %s') % (method, text[:500]))
        return text

    # ------------------------------------------------------------------
    # Expedició de devolució (servei 44)
    # ------------------------------------------------------------------
    def nacex_build_return_data(self, log):
        """Munta la cadena 'data' del putExpedicion (sense credencials).
        Separat de la crida per poder-la veure en mode simulació."""
        self.ensure_one()
        config = log.config_id
        dest = config.dest_partner_id
        if not dest:
            raise UserError(_('Falta la dirección de entrega (almacén) en la configuración.'))

        dev_name = log.dev_picking_id.name or ''
        dest_street = ' '.join(filter(None, [dest.street, dest.street2]))

        values = [
            ('del_cli', self.del_cli),
            ('num_cli', self.num_cli),
            ('tip_ser', self.tip_ser or '44'),
            # Devolució: paguem nosaltres, que som el destinatari (Nacex no accepta ORIGEN amb el client com a remitent)
            ('tip_cob', config.nacex_tip_cob or 'D'),
            # Referència = la TT/DEV (com a FedEx), perquè devolucions la identifiqui
            ('ref_cli', _clean(dev_name or log.remarks, 20)),
            ('tip_env', self.tip_env or '2'),
            ('bul', '1'),
            ('kil', '1'),
            # --- Dades de recollida (el client) ---
            ('nom_rec', _clean(log.partner_name, 35)),
            ('dir_rec', _clean(log.street, 60)),
            ('cp_rec', _clean(log.zip)),
            ('pob_rec', _clean(log.city, 30)),
            ('pais_rec', _clean(log.country_code)),
            ('tel_rec', _clean(log.phone) or '.'),
            # --- Dades d'entrega (magatzem) ---
            ('nom_ent', _clean(dest.name, 35)),
            ('dir_ent', _clean(dest_street, 60)),
            ('pais_ent', dest.country_id.code or 'ES'),
            ('cp_ent', _clean(dest.zip)),
            ('pob_ent', _clean(dest.city, 30)),
            ('tel_ent', _clean(dest.phone) or '.'),
            # Observacions = TT/DEV + remarks
            ('obs1', _clean(' '.join(filter(None, [dev_name, log.remarks])), 38)),
        ]
        tip_ser = self.tip_ser or '44'
        if tip_ser == '44' or config.nacex_shop_code or log.nacex_shop_code:
            shop = (log.nacex_shop_code or config.nacex_shop_code or '').strip()
            if not shop:
                raise UserError(_('Falta el código NACEX.shop (punto de recogida): ponlo en la devolución '
                                  'o en la configuración.'))
            values.append(('shop_codigo', _clean(shop)))
        # El servei 44 (eDevoluciones SHOP) no admet prealerta
        if config.nacex_prealert_customer and tip_ser != '44' and (log.email or self.pre1):
            # Prealerta per email al client (a validar si és el mateix email
            # "eDevoluciones SHOP" que envia el botó "Enviar por mail" de la web)
            values += [
                ('tip_pre1', 'E'),
                ('mod_pre1', 'S'),
                ('pre1', _clean(log.email or self.pre1)),
            ]

        return '|'.join('%s=%s' % (k, v) for k, v in values if v not in (None, False, ''))

    def nacex_put_return_expedicion(self, log):
        """Crea la recollida eDevoluciones SHOP.
        Recollida (remitent) = client · Entrega = magatzem (config.dest_partner_id).
        :return: (cod_exp, albaran)  p.ex. ('497627631', '4307/11539638')
        """
        self.ensure_one()
        data = self.nacex_build_return_data(log)
        _logger.info('Nacex putExpedicion (devolución %s): %s', log.remarks, data)
        text = self._nacex_ws_call('putExpedicion', data)
        parts = [p.strip() for p in text.split('|')]
        cod_exp = parts[0] if parts else ''
        albaran = parts[1] if len(parts) > 1 else ''
        if not cod_exp or not albaran:
            raise UserError(_('Nacex no ha devuelto el código de expedición. Respuesta: %s') % text[:500])
        return cod_exp, albaran

    @staticmethod
    def _nacex_b64(text):
        """Mateixa neteja base64 que delivery_nacex (Nacex fa servir un base64 'url-safe' amb soroll)."""
        label = (text or '').replace('\n', '').replace(' ', '').replace('*', '') \
            .replace('-', '+').replace('_', '/')
        padding = len(label) % 4
        if padding:
            label += '=' * (4 - padding)
        return base64.b64decode(label)

    def nacex_gen_return_label(self, log):
        """eDevolución SHOP oberta (genEtiquetaDevolucion): igual que la web de Nacex.
        Sense punt: el client la porta al NACEX.shop que vulgui. Destí = adreça de l'abonat.
        :return: (cod_exp, pdf_bytes)"""
        self.ensure_one()
        dev_name = log.dev_picking_id.name or log.remarks or ''
        values = [
            ('del_cli', self.del_cli),
            ('num_cli', self.num_cli),
            ('modelo', 'PDF_B'),
            ('ref_cli', _clean(dev_name, 20)),
            ('obs1', _clean(' '.join(filter(None, [log.dev_picking_id.name, log.remarks])), 38)),
        ]
        data = '|'.join('%s=%s' % (k, v) for k, v in values if v)
        _logger.info('Nacex genEtiquetaDevolucion (devolución %s): %s', log.remarks, data)
        text = self._nacex_ws_call('genEtiquetaDevolucion', data)
        parts = [p.strip() for p in text.split('|')]
        cod_exp = parts[0] if parts else ''
        if not cod_exp.isdigit() or len(parts) < 2:
            raise UserError(_('Nacex no ha devuelto la etiqueta de devolución. Respuesta: %s') % text[:300])
        try:
            pdf = self._nacex_b64(parts[-1])
        except Exception:
            pdf = self.nacex_get_label_pdf(cod_exp)
        return cod_exp, pdf

    def nacex_get_label_pdf(self, cod_exp):
        """Mateixa neteja base64 que delivery_nacex.nacex_send_shipping."""
        self.ensure_one()
        text = self._nacex_ws_call('getEtiqueta', 'codExp=%s|modelo=PDF_B' % cod_exp)
        label = text.replace('\n', '').replace(' ', '').replace('*', '') \
            .replace('-', '+').replace('_', '/')
        padding = len(label) % 4
        if padding:
            label += '=' * (4 - padding)
        return base64.b64decode(label)

    # ------------------------------------------------------------------
    # Seguiment i cancel·lació
    # ------------------------------------------------------------------
    def nacex_cancel_return(self, cod_exp):
        """Anul·la la recollida si el client cancel·la la devolució a Shopify."""
        self.ensure_one()
        return self._nacex_ws_call('cancelExpedicion', 'expe_codigo=%s' % cod_exp)

    def nacex_get_status(self, cod_exp):
        """Estat de l'expedició.
        Resposta: cod_exp|data|hora|observacions|estat|codi estat|agència|albarà|
        :return: (text de l'estat, entregat True/False, albarà 'agència/número' o '')"""
        self.ensure_one()
        text = self._nacex_ws_call('getEstadoExpedicion', 'expe_codigo=%s' % cod_exp, timeout=20)
        raw = [p.strip() for p in text.split('|')]
        # Data, hora, observacions, estat i codi, per posició: si Nacex encara no ha posat
        # data ni hora, les buides se salten sense que entri l'albarà al text
        status = ' · '.join(p for p in raw[1:6] if p) if len(raw) > 1 else text
        # L'albarà (p. ex. 4307/11553031) és el número que serveix per seguir l'enviament;
        # genEtiquetaDevolucion només retorna el codi d'expedició
        albaran = '%s/%s' % (raw[6], raw[7]) if len(raw) > 7 and raw[6].isdigit() and raw[7].isdigit() else ''
        return status[:250], 'ENTREGAD' in text.upper(), albaran
