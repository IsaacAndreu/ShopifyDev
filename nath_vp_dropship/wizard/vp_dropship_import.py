# -*- coding: utf-8 -*-
import base64
import re

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models import vp_parse


class VpDropshipImport(models.TransientModel):
    _name = 'vp.dropship.import'
    _description = 'Dropshipping Veepee: importar Excel'

    config_id = fields.Many2one('vp.dropship.config', required=True,
                                default=lambda s: s.env['vp.dropship.config'].search([], limit=1))
    kind = fields.Selection([
        ('prices', 'Precios de la campaña (EAN + tarifa ES / FR-BENELUX / IT)'),
        ('carriers', 'Mapeo de transportistas (MAPPING_CARRIER.xlsx)'),
        ('batch', 'Batch de VentePriveeSync (modo "Simular API")'),
    ], required=True, default='prices')
    campaign = fields.Char('Campaña', help='Código de la campaña (TTUC85). Vacío: vale para cualquiera.')
    replace = fields.Boolean('Sustituir los precios de esta campaña', default=True)
    file = fields.Binary('Excel', required=True)
    filename = fields.Char()
    result = fields.Text('Resultado', readonly=True)

    def action_import(self):
        self.ensure_one()
        data = base64.b64decode(self.file)
        return getattr(self, '_import_%s' % self.kind)(data)

    @staticmethod
    def _col(header, *words):
        for i, h in enumerate(header):
            hl = h.lower()
            if any(w in hl for w in words):
                return i
        return None

    def _import_prices(self, data):
        header, values = vp_parse.read_xlsx(data)
        c_ean = self._col(header, 'barre', 'barcode', 'ean', 'código de barras', 'codigo')
        cols = {}
        for i, h in enumerate(header):
            if i == c_ean:
                continue
            tarifa = vp_parse.tarifa_from_text(h)
            if tarifa and tarifa not in cols:
                cols[tarifa] = i
        if c_ean is None or not cols:
            raise UserError(_('No encuentro la columna del EAN o las de tarifas en: %s') % ', '.join(header))
        Price = self.env['vp.dropship.price']
        campaign = (self.campaign or '').strip()
        if self.replace:
            Price.search([('campaign', '=', campaign or False)]).unlink()
        existing = {p.barcode: p for p in Price.search([('campaign', '=', campaign or False)])}
        to_create = []
        seen = set()
        for row in values:
            ean = vp_parse._txt(row[c_ean]) if c_ean < len(row) else ''
            if not ean or ean in seen:
                continue
            seen.add(ean)
            vals = {'campaign': campaign or False, 'barcode': ean}
            for tarifa, i in cols.items():
                try:
                    vals['price_%s' % tarifa] = float(row[i]) if i < len(row) and row[i] not in (None, '') else 0.0
                except (TypeError, ValueError):
                    vals['price_%s' % tarifa] = 0.0
            if ean in existing:
                existing[ean].write(vals)
            else:
                to_create.append(vals)
        Price.create(to_create)
        return self._done(_('%s precios importados para la campaña %s (tarifas: %s).') % (
            len(seen), campaign or _('(cualquiera)'), ', '.join(sorted(cols))))

    def _import_carriers(self, data):
        header, values = vp_parse.read_xlsx(data)
        c_key = self._col(header, 'li_pays', 'pays', 'clave')
        c_carrier = self._col(header, 'odoo_carrier', 'carrier', 'transportista')
        c_tarifa = self._col(header, 'tarifa', 'pricelist')
        if None in (c_key, c_carrier, c_tarifa):
            raise UserError(_('El Excel necesita las columnas LI_Pays, odoo_carrier y tarifa.'))
        Carrier = self.env['delivery.carrier'].with_context(active_test=False)
        Map = self.env['vp.dropship.carrier']
        done, missing = 0, []
        for row in values:
            key = vp_parse._txt(row[c_key])
            name = vp_parse._txt(row[c_carrier])
            tarifa = vp_parse.tarifa_from_text(row[c_tarifa])
            if not key or not name:
                continue
            carrier = Carrier.search([('name', '=', name)], limit=1)
            if not carrier or not tarifa:
                missing.append('%s -> %s' % (key, name))
                continue
            current = Map.search([('config_id', '=', self.config_id.id), ('key', '=', key)])
            vals = {'config_id': self.config_id.id, 'key': key, 'carrier_id': carrier.id, 'tarifa': tarifa}
            if current:
                current.write(vals)
            else:
                Map.create(vals)
            done += 1
        msg = _('%s transportistas mapeados.') % done
        if missing:
            msg += _('\nNo encontrados en Odoo (créalos y vuelve a importar):\n%s') % '\n'.join(missing)
        return self._done(msg)

    def _import_batch(self, data):
        if not self.config_id.simulate_api:
            raise UserError(_('Solo en modo "Simular API". Con la API, los batches se descargan solos.'))
        rows = vp_parse.rows_from_xlsx(data)
        intitule = (rows[0].get('LI_Intitule') or '').split('#') if rows else []
        m = re.search(r'(\d{5,})_(\d{2})-(\d{2})-(\d{4})', self.filename or '')
        batch_ref = (intitule[1] if len(intitule) > 1 else '') or (m.group(1) if m else self.filename)
        batch_date = '%s-%s-%s' % (m.group(4), m.group(3), m.group(2)) if m else fields.Date.context_today(self)
        batch = self.env['vp.dropship.batch'].create({
            'config_id': self.config_id.id,
            'operation_code': intitule[0] if intitule else self.campaign,
            'batch_ref': batch_ref,
            'batch_date': batch_date,
            'source_file': self.file,
            'source_filename': self.filename,
        })
        batch._download()
        return {'type': 'ir.actions.act_window', 'res_model': 'vp.dropship.batch',
                'res_id': batch.id, 'view_mode': 'form'}

    def _done(self, message):
        # Odoo 13 no té 'display_notification': es torna a obrir l'assistent amb el resultat
        self.result = message
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new', 'name': _('Importación')}
