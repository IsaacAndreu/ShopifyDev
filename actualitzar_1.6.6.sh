# === Actualitzar nath_shopify_returns a 1.6.6 (enganxa-ho tot al terminal de tuctuc-erp-prod-eu-w1b) ===
cat > ~/nath_shopify_returns_1.6.6.diff <<'PATCHEOF'
diff -ru -x '*.pyc' -x __pycache__ -x '*.bak_*' src_orig/nath_shopify_returns/README.md nath_shopify_returns/README.md
--- src_orig/nath_shopify_returns/README.md	2026-10-19 15:50:06.000000000 +0200
+++ nath_shopify_returns/README.md	2026-10-26 13:51:30.966638700 +0100
@@ -67,4 +67,12 @@
 
 - **Camps de recollida:** Nacex pot rebutjar `nom_rec`, `dir_rec`, `cp_rec`, `pob_rec`, `pais_rec` i `tel_rec`, o les longituds que hi posem. Si passa, ajusta-ho a `models/delivery_carrier.py`.
 - **Email al client:** comprova si la prealerta (`tip_pre1=E`, `pre1`=email del client) és el mateix email "eDevoluciones SHOP" que envia la web. Si no ho és, activa **Enviar etiqueta PDF des d'Odoo**.
-- **SKU:** es busca per `default_code` o `barcode` del producte.
+- **SKU:** es busca pel producte enllaçat al connector (el SKU de Shopify no sempre és el `default_code`, p. ex. `21118499_7Y` → `21118499_7-8Y`), o per `default_code` o `barcode`.
+
+## Canvis 1.6.6
+
+- SKU validat amb l'enllaç del connector (variant de Shopify → producte d'Odoo).
+- Línia **No se devuelve**: el client demana tornar una cosa que no va rebre. No es busca a l'OUT, no s'espera a la TT/DEV ni es reemborsa.
+- FedEx: si la recollida a domicili falla (p. ex. `FORBIDDEN`), el client porta el paquet a un punt FedEx i la devolució continua (*FedEx: si falla la recogida, entrega en punto*).
+- Nacex (etiqueta oberta): `genEtiquetaDevolucion` només retorna el codi d'expedició. El seguiment és l'**albarà** (`4307/11553031`), que s'agafa de `getEstadoExpedicion` en crear l'etiqueta. A les devolucions ja fetes, el cron de seguiment el corregeix a Odoo, a la TT/DEV i a Shopify (`reverseDeliveryShippingUpdate`, sense avisar el client).
+- FedEx fora de la UE (Regne Unit): la factura comercial ETD porta la signatura i el membret del compte de FedEx (`IMAGE_1` / `IMAGE_2`, els mateixos que `delivery_fedex_rest2`).
diff -ru -x '*.pyc' -x __pycache__ -x '*.bak_*' src_orig/nath_shopify_returns/__manifest__.py nath_shopify_returns/__manifest__.py
--- src_orig/nath_shopify_returns/__manifest__.py	2026-10-19 15:50:06.000000000 +0200
+++ nath_shopify_returns/__manifest__.py	2026-10-26 12:16:27.318101700 +0100
@@ -3,7 +3,7 @@
     'name': 'NATH - Devoluciones Shopify automáticas',
     'summary': 'Shopify (devolución solicitada) -> TT/DEV -> Nacex eDevoluciones (44) -> '
                'aprobación Shopify -> recepción',
-    'version': '13.0.1.6.5',
+    'version': '13.0.1.6.6',
     'category': 'Inventory',
     'author': 'NATH',
     'license': 'LGPL-3',
diff -ru -x '*.pyc' -x __pycache__ -x '*.bak_*' src_orig/nath_shopify_returns/models/delivery_carrier.py nath_shopify_returns/models/delivery_carrier.py
--- src_orig/nath_shopify_returns/models/delivery_carrier.py	2026-10-19 15:50:06.000000000 +0200
+++ nath_shopify_returns/models/delivery_carrier.py	2026-10-26 13:50:54.165283500 +0100
@@ -185,10 +185,15 @@
 
     def nacex_get_status(self, cod_exp):
         """Estat de l'expedició.
-        :return: (text de l'estat, entregat True/False)"""
+        Resposta: cod_exp|data|hora|observacions|estat|codi estat|agència|albarà|
+        :return: (text de l'estat, entregat True/False, albarà 'agència/número' o '')"""
         self.ensure_one()
         text = self._nacex_ws_call('getEstadoExpedicion', 'expe_codigo=%s' % cod_exp, timeout=20)
-        parts = [p.strip() for p in text.split('|') if p.strip()]
+        raw = [p.strip() for p in text.split('|')]
+        parts = [p for p in raw if p]
         # Ens quedem amb les parts amb text (data, hora, estat, observacions...)
         status = ' · '.join(parts[1:6]) if len(parts) > 1 else text
-        return status[:250], 'ENTREGAD' in text.upper()
+        # L'albarà (p. ex. 4307/11553031) és el número que serveix per seguir l'enviament;
+        # genEtiquetaDevolucion només retorna el codi d'expedició
+        albaran = '%s/%s' % (raw[6], raw[7]) if len(raw) > 7 and raw[6].isdigit() and raw[7].isdigit() else ''
+        return status[:250], 'ENTREGAD' in text.upper(), albaran
diff -ru -x '*.pyc' -x __pycache__ -x '*.bak_*' src_orig/nath_shopify_returns/models/fedex_return.py nath_shopify_returns/models/fedex_return.py
--- src_orig/nath_shopify_returns/models/fedex_return.py	2026-10-19 15:50:06.000000000 +0200
+++ nath_shopify_returns/models/fedex_return.py	2026-10-26 12:16:19.952540900 +0100
@@ -49,7 +49,7 @@
         dest = config.dest_partner_id
         acct = {'value': self.fedex_rest_account_number}
         ship_date = next_business_day()
-        qty = int(sum(log.line_ids.mapped('quantity'))) or 1
+        qty = int(sum(log.line_ids.filtered(lambda l: not l.ignore).mapped('quantity'))) or 1
         value = round(log.amount_expected or 1.0, 2)
         currency = log.currency_code or 'EUR'
         payload = {
@@ -104,9 +104,17 @@
                     'specialServiceTypes': ['ELECTRONIC_TRADE_DOCUMENTS'],
                     'etdDetail': {'requestedDocumentTypes': ['COMMERCIAL_INVOICE']},
                 },
+                # "Quiero que FedEx me ayude a crear una factura comercial", amb el membret i la
+                # signatura guardats al compte de FedEx (sense: SHIPMENT.ELECTRONICIMAGE.REQUIRED)
                 'shippingDocumentSpecification': {
                     'shippingDocumentTypes': ['COMMERCIAL_INVOICE'],
                     'commercialInvoiceDetail': {
+                        'customerImageUsages': [
+                            {'id': self.fedex_rest_image_signature_id or 'IMAGE_1',
+                             'type': 'SIGNATURE', 'providedImageType': 'SIGNATURE'},
+                            {'id': self.fedex_rest_image_logo_id or 'IMAGE_2',
+                             'type': 'LETTER_HEAD', 'providedImageType': 'LETTER_HEAD'},
+                        ],
                         'documentFormat': {'stockType': 'PAPER_LETTER', 'docType': 'PDF'},
                     },
                 },
diff -ru -x '*.pyc' -x __pycache__ -x '*.bak_*' src_orig/nath_shopify_returns/models/shopify_return_config.py nath_shopify_returns/models/shopify_return_config.py
--- src_orig/nath_shopify_returns/models/shopify_return_config.py	2026-10-19 15:50:06.000000000 +0200
+++ nath_shopify_returns/models/shopify_return_config.py	2026-10-26 12:15:50.352847000 +0100
@@ -39,6 +39,10 @@
         help='Antes de crear el envío pregunta a FedEx si hay puntos FedEx cerca del cliente. '
              'Si no hay ninguno, se programa recogida a domicilio (como en Francia).')
     fedex_location_radius = fields.Integer('FedEx: radio de búsqueda de puntos (km)', default=20)
+    fedex_pickup_fallback = fields.Boolean(
+        'FedEx: si falla la recogida, entrega en punto', default=True,
+        help='Si FedEx no acepta la recogida a domicilio, la devolución sigue adelante: '
+             'se aprueba en Shopify con la etiqueta y el cliente la lleva a un punto FedEx.')
     fedex_pickup_from = fields.Char('FedEx: recogida desde', default='12:00')
     fedex_pickup_to = fields.Char('FedEx: recogida hasta', default='18:00')
     fedex_weight = fields.Float('FedEx: peso (kg)', default=1.0)
diff -ru -x '*.pyc' -x __pycache__ -x '*.bak_*' src_orig/nath_shopify_returns/models/shopify_return_followup.py nath_shopify_returns/models/shopify_return_followup.py
--- src_orig/nath_shopify_returns/models/shopify_return_followup.py	2026-10-19 15:50:06.000000000 +0200
+++ nath_shopify_returns/models/shopify_return_followup.py	2026-10-26 13:51:13.916109100 +0100
@@ -10,6 +10,7 @@
 from datetime import timedelta
 
 from odoo import api, fields, models, _
+from odoo.exceptions import UserError
 from odoo.tools import html_escape
 
 from .shopify_return_log import RETURN_CLOSE_MUTATION
@@ -24,6 +25,29 @@
 }
 """
 
+REVERSE_DELIVERIES_QUERY = """
+{
+  return(id: "%(id)s") {
+    reverseFulfillmentOrders(first: 5) { edges { node {
+      reverseDeliveries(first: 5) { edges { node { id } } }
+    } } }
+  }
+}
+"""
+
+REVERSE_DELIVERY_UPDATE_MUTATION = """
+mutation {
+  reverseDeliveryShippingUpdate(
+    reverseDeliveryId: "%(id)s",
+    trackingInput: { number: "%(number)s", url: "%(url)s" },
+    notifyCustomer: false
+  ) {
+    reverseDelivery { id }
+    userErrors { field message }
+  }
+}
+"""
+
 WAITING_STATES = ('dev_created', 'nacex_ok', 'done')
 
 
@@ -79,11 +103,12 @@
             if not ref or (ref or '').startswith('TEST') or simulated:
                 continue
             carrier = config.fedex_carrier_id if log.return_carrier == 'fedex' else config.carrier_id
+            albaran = ''
             try:
                 if log.return_carrier == 'fedex':
                     status, delivered = carrier.fedex_get_status(ref)
                 else:
-                    status, delivered = carrier.nacex_get_status(ref)
+                    status, delivered, albaran = carrier.nacex_get_status(ref)
             except Exception as e:
                 _logger.info('Estado envío %s: %s', log.remarks, e)
                 log.carrier_status_date = fields.Datetime.now()   # no reintentar fins d'aquí 3 h
@@ -94,8 +119,44 @@
                 vals['carrier_status'] = status
                 log.message_post(body=_('Estado del envío: %s') % html_escape(status))
             log.write(vals)
+            if albaran and albaran != log.nacex_albaran:
+                log._set_nacex_albaran(albaran)
         return all_ok
 
+    def _set_nacex_albaran(self, albaran):
+        """Les etiquetes obertes es creen amb el codi d'expedició com a seguiment, però el
+        número que segueix l'enviament és l'albarà: es corregeix a Odoo, a la TT/DEV i a Shopify."""
+        self.ensure_one()
+        old = self.nacex_albaran
+        self.nacex_albaran = albaran
+        if self.dev_picking_id and self.dev_picking_id.carrier_tracking_ref in (False, old):
+            self.dev_picking_id.carrier_tracking_ref = albaran
+        msg = _('Albarán Nacex %s (antes %s).') % (albaran, old or '-')
+        if self.shopify_tracking_done and not self.config_id.simulate_shopify:
+            try:
+                msg += ' ' + self._shopify_update_tracking()
+            except Exception as e:
+                _logger.info('Seguimiento Shopify %s: %s', self.remarks, e)
+                msg += ' ' + _('No se ha podido actualizar en Shopify: %s') % e
+        self.message_post(body=msg)
+
+    def _shopify_update_tracking(self):
+        config = self.config_id
+        data = self._shopify_graphql(config, REVERSE_DELIVERIES_QUERY % {'id': self.shopify_return_id})
+        ids = [d['node']['id']
+               for rfo in ((data.get('return') or {}).get('reverseFulfillmentOrders') or {}).get('edges', [])
+               for d in ((rfo['node'].get('reverseDeliveries') or {}).get('edges') or [])]
+        if not ids:
+            return _('En Shopify no hay ningún envío de devolución que actualizar.')
+        for rd_id in ids:
+            result = self._shopify_graphql(config, REVERSE_DELIVERY_UPDATE_MUTATION % {
+                'id': rd_id, 'number': self.nacex_albaran, 'url': self._nacex_tracking_url(),
+            }).get('reverseDeliveryShippingUpdate') or {}
+            errors = result.get('userErrors') or []
+            if errors:
+                raise UserError('; '.join(e.get('message', '') for e in errors))
+        return _('Actualizado también en Shopify.')
+
     # ------------------------------------------------------------------
     # Retards
     # ------------------------------------------------------------------
diff -ru -x '*.pyc' -x __pycache__ -x '*.bak_*' src_orig/nath_shopify_returns/models/shopify_return_log.py nath_shopify_returns/models/shopify_return_log.py
--- src_orig/nath_shopify_returns/models/shopify_return_log.py	2026-10-23 14:48:29.000000000 +0200
+++ nath_shopify_returns/models/shopify_return_log.py	2026-10-26 13:50:54.263115700 +0100
@@ -571,11 +571,14 @@
                                 % (outs.name, ', '.join(existing.mapped('name'))))
             adopt = existing
 
-        if not self.line_ids:
+        lines = self.line_ids.filtered(lambda l: not l.ignore)
+        if not lines:
             raise UserError(_('La devolución de Shopify no tiene artículos.'))
-        for line in self.line_ids:
+        for line in lines:
+            mapped = self._product_from_mapping(line.sku)
             move = outs.move_lines.filtered(
-                lambda m: line.sku and line.sku in (m.product_id.default_code, m.product_id.barcode))
+                lambda m: line.sku and (m.product_id == mapped
+                                        or line.sku in (m.product_id.default_code, m.product_id.barcode)))
             if not move:
                 raise UserError(_('El SKU %s no está en el OUT %s.') % (line.sku, outs.name))
             if line.quantity > sum(move.mapped('quantity_done')):
@@ -605,6 +608,18 @@
                 adopt.name, dict(adopt._fields['state']._description_selection(self.env)).get(adopt.state, adopt.state),
                 _(' con el seguimiento %s') % adopt.carrier_tracking_ref if adopt.carrier_tracking_ref else ''))
 
+    def _product_from_mapping(self, sku):
+        """Producte d'Odoo enllaçat al connector amb aquest SKU de Shopify.
+        El SKU de Shopify no sempre és el default_code (p. ej. 21118499_7Y -> 21118499_7-8Y)."""
+        if not sku or not self.config_id.integration_id:
+            return self.env['product.product']
+        ext = self.env['integration.product.product.external'].search([
+            ('integration_id', '=', self.config_id.integration_id.id), ('external_reference', '=', sku)], limit=1)
+        if not ext:
+            return self.env['product.product']
+        return self.env['integration.product.product.mapping'].search(
+            [('external_product_id', '=', ext.id), ('product_id', '!=', False)], limit=1).product_id
+
     # ------------------------------------------------------------------
     def _step_nacex(self):
         config = self.config_id
@@ -621,6 +636,11 @@
         elif config.nacex_return_method == 'label':
             cod_exp, pdf = carrier.nacex_gen_return_label(self)
             albaran = cod_exp
+            try:
+                albaran = carrier.nacex_get_status(cod_exp)[2] or cod_exp
+            except Exception as e:
+                # Sense albarà de moment: el cron de seguiment el corregirà
+                _logger.info('Albarán Nacex %s: %s', self.remarks, e)
             att = self.env['ir.attachment'].create({
                 'name': 'Nacex devolucion %s.pdf' % (self.remarks or '').lstrip('#'),
                 'datas': base64.b64encode(pdf),
@@ -680,7 +700,20 @@
                     label = False
                 self.write({'nacex_albaran': tracking})
                 self.env.cr.commit()     # l'enviament ja existeix a FedEx: que no es perdi
-            pickup_code = carrier.fedex_return_pickup(self, tracking) if pickup else ''
+            pickup_code = ''
+            if pickup:
+                try:
+                    pickup_code = carrier.fedex_return_pickup(self, tracking)
+                except UserError as e:
+                    if not config.fedex_pickup_fallback:
+                        raise
+                    # P. ex. FORBIDDEN si el compte no té l'API de recollides: l'etiqueta ja és vàlida,
+                    # el client la porta a un punt FedEx i no s'atura la devolució
+                    pickup = False
+                    self.fedex_pickup = False
+                    self.message_post(body=_('FedEx no ha aceptado la recogida a domicilio: el cliente '
+                                             'llevará el paquete a un punto FedEx.<br/>%s')
+                                      % (e.name if hasattr(e, 'name') else e))
         vals = {'nacex_albaran': tracking, 'nacex_cod_exp': pickup_code}
         if label:
             att = self.env['ir.attachment'].create({
@@ -822,7 +855,7 @@
             }) for m in out.move_lines]
         else:
             moves = []
-            for line in self.line_ids:
+            for line in self.line_ids.filtered(lambda l: not l.ignore):
                 move = out.move_lines.filtered(lambda m: m.product_id == line.product_id)[:1]
                 moves.append((0, 0, {
                     'product_id': line.product_id.id,
@@ -855,7 +888,7 @@
             for m in done_moves:
                 received[m.product_id.id] = received.get(m.product_id.id, 0.0) + m.quantity_done
             problems = []
-            for line in log.line_ids:
+            for line in log.line_ids.filtered(lambda l: not l.ignore):
                 qty = received.pop(line.product_id.id, 0.0) if line.product_id else 0.0
                 line.qty_received = qty
                 if qty < line.quantity:
@@ -1102,6 +1135,10 @@
     _description = 'Artículo de devolución Shopify'
 
     log_id = fields.Many2one('shopify.return.log', 'Devolución', required=True, ondelete='cascade')
+    ignore = fields.Boolean(
+        'No se devuelve',
+        help='El cliente pide devolver algo que no recibió (o que se gestiona aparte): '
+             'no se busca en el OUT, no se espera en la TT/DEV ni se reembolsa.')
     sku = fields.Char('SKU')
     quantity = fields.Float('Esperadas')
     product_id = fields.Many2one('product.product', 'Producto')
@@ -1117,14 +1154,14 @@
     amount_to_refund = fields.Float('Importe a reembolsar', compute='_compute_line_amounts', digits=(16, 2))
     refunded_subtotal = fields.Float('Reembolsado (Shopify)', digits=(16, 2), readonly=True, copy=False)
 
-    @api.depends('unit_price', 'unit_discount', 'quantity', 'qty_received')
+    @api.depends('unit_price', 'unit_discount', 'quantity', 'qty_received', 'ignore')
     def _compute_line_amounts(self):
         for line in self:
-            net = (line.unit_price or 0.0) - (line.unit_discount or 0.0)
+            net = 0.0 if line.ignore else (line.unit_price or 0.0) - (line.unit_discount or 0.0)
             line.amount_expected = net * line.quantity
             line.amount_to_refund = net * min(line.quantity, line.qty_received)
 
-    @api.depends('quantity', 'qty_received')
+    @api.depends('quantity', 'qty_received', 'ignore')
     def _compute_qty_refund(self):
         for line in self:
-            line.qty_refund = min(line.quantity, line.qty_received)
+            line.qty_refund = 0.0 if line.ignore else min(line.quantity, line.qty_received)
diff -ru -x '*.pyc' -x __pycache__ -x '*.bak_*' src_orig/nath_shopify_returns/views/shopify_return_views.xml nath_shopify_returns/views/shopify_return_views.xml
--- src_orig/nath_shopify_returns/views/shopify_return_views.xml	2026-10-19 15:50:06.000000000 +0200
+++ nath_shopify_returns/views/shopify_return_views.xml	2026-10-26 12:16:19.616583200 +0100
@@ -127,7 +127,8 @@
                         </group>
                     </group>
                     <field name="line_ids">
-                        <tree editable="bottom">
+                        <tree editable="bottom" decoration-muted="ignore">
+                            <field name="ignore" attrs="{'readonly': [('parent.state', 'not in', ('pending', 'validated'))]}"/>
                             <field name="sku"/>
                             <field name="product_id"/>
                             <field name="return_reason"/>
@@ -264,6 +265,7 @@
                         <group string="FedEx (valores por defecto)" attrs="{'invisible': [('fedex_carrier_id', '=', False)]}">
                             <field name="fedex_check_locations"/>
                             <field name="fedex_location_radius" attrs="{'invisible': [('fedex_check_locations', '=', False)]}"/>
+                            <field name="fedex_pickup_fallback"/>
                             <field name="fedex_pickup_from"/>
                             <field name="fedex_pickup_to"/>
                             <field name="fedex_weight"/>
PATCHEOF
cd /opt/tuctuc-erp/nath/custom_addons \
 && sudo tar czf ~/nath_shopify_returns_1.6.5_backup.tgz nath_shopify_returns \
 && sudo patch -p1 --dry-run < ~/nath_shopify_returns_1.6.6.diff \
 && sudo patch -p1 --no-backup-if-mismatch < ~/nath_shopify_returns_1.6.6.diff \
 && sudo /opt/tuctuc-erp/env/bin/python -m py_compile nath_shopify_returns/models/*.py \
 && grep version nath_shopify_returns/__manifest__.py \
 && echo "PATCH OK"
