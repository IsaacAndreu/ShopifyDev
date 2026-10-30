# === Actualitzar nath_shopify_returns 1.6.6 -> 1.6.7 (a tuctuc-erp-prod-eu-w1b: bash ~/actualitzar_1.6.7.sh) ===
cat > ~/nath_shopify_returns_1.6.7.diff <<'PATCHEOF'
diff -ruN -x '*.pyc' -x __pycache__ -x '*.bak_*' src_166/nath_shopify_returns/README.md nath_shopify_returns/README.md
--- src_166/nath_shopify_returns/README.md	2026-10-26 14:00:23.189766200 +0100
+++ nath_shopify_returns/README.md	2026-10-28 14:04:46.699021900 +0100
@@ -76,3 +76,11 @@
 - FedEx: si la recollida a domicili falla (p. ex. `FORBIDDEN`), el client porta el paquet a un punt FedEx i la devolució continua (*FedEx: si falla la recogida, entrega en punto*).
 - Nacex (etiqueta oberta): `genEtiquetaDevolucion` només retorna el codi d'expedició. El seguiment és l'**albarà** (`4307/11553031`), que s'agafa de `getEstadoExpedicion` en crear l'etiqueta. A les devolucions ja fetes, el cron de seguiment el corregeix a Odoo, a la TT/DEV i a Shopify (`reverseDeliveryShippingUpdate`, sense avisar el client).
 - FedEx fora de la UE (Regne Unit): la factura comercial ETD porta la signatura i el membret del compte de FedEx (`IMAGE_1` / `IMAGE_2`, els mateixos que `delivery_fedex_rest2`).
+
+## Canvis 1.6.7
+
+- Nacex: després de crear l'etiqueta oberta, s'espera l'albarà (fins a 5 consultes, cada 3 s) abans de pujar el seguiment a Shopify.
+- Estat de l'enviament: si Nacex encara no ha posat data ni hora, l'albarà ja no es barreja amb el text de l'estat.
+- Configuració: només la veu el grup «Devoluciones Shopify: Configuración» (assignar-lo a mà als usuaris).
+- Rectificativa: les línies porten el preu de la comanda. Els descomptes de Shopify en **%** van al camp *Desc.%* de cada línia i els descomptes en **€ fixos** en una línia a part «Descuento [codi]» (negativa). Si Shopify no dóna el desglossament o no quadra amb el reemborsat, la línia porta el descompte en % equivalent.
+- Rectificativa: es crea amb la data de factura del dia en què s'accepta el reemborsament (abans quedava sense data fins a validar-la).
diff -ruN -x '*.pyc' -x __pycache__ -x '*.bak_*' src_166/nath_shopify_returns/__manifest__.py nath_shopify_returns/__manifest__.py
--- src_166/nath_shopify_returns/__manifest__.py	2026-10-26 14:00:23.159021200 +0100
+++ nath_shopify_returns/__manifest__.py	2026-10-28 09:47:30.755660400 +0100
@@ -3,7 +3,7 @@
     'name': 'NATH - Devoluciones Shopify automáticas',
     'summary': 'Shopify (devolución solicitada) -> TT/DEV -> Nacex eDevoluciones (44) -> '
                'aprobación Shopify -> recepción',
-    'version': '13.0.1.6.6',
+    'version': '13.0.1.6.7',
     'category': 'Inventory',
     'author': 'NATH',
     'license': 'LGPL-3',
@@ -17,6 +17,7 @@
         'sales_ext',
     ],
     'data': [
+        'security/security.xml',
         'security/ir.model.access.csv',
         'data/mail_template.xml',
         'data/ir_cron.xml',
diff -ruN -x '*.pyc' -x __pycache__ -x '*.bak_*' src_166/nath_shopify_returns/models/delivery_carrier.py nath_shopify_returns/models/delivery_carrier.py
--- src_166/nath_shopify_returns/models/delivery_carrier.py	2026-10-26 14:00:23.175519900 +0100
+++ nath_shopify_returns/models/delivery_carrier.py	2026-10-26 14:00:44.212571900 +0100
@@ -190,9 +190,9 @@
         self.ensure_one()
         text = self._nacex_ws_call('getEstadoExpedicion', 'expe_codigo=%s' % cod_exp, timeout=20)
         raw = [p.strip() for p in text.split('|')]
-        parts = [p for p in raw if p]
-        # Ens quedem amb les parts amb text (data, hora, estat, observacions...)
-        status = ' · '.join(parts[1:6]) if len(parts) > 1 else text
+        # Data, hora, observacions, estat i codi, per posició: si Nacex encara no ha posat
+        # data ni hora, les buides se salten sense que entri l'albarà al text
+        status = ' · '.join(p for p in raw[1:6] if p) if len(raw) > 1 else text
         # L'albarà (p. ex. 4307/11553031) és el número que serveix per seguir l'enviament;
         # genEtiquetaDevolucion només retorna el codi d'expedició
         albaran = '%s/%s' % (raw[6], raw[7]) if len(raw) > 7 and raw[6].isdigit() and raw[7].isdigit() else ''
diff -ruN -x '*.pyc' -x __pycache__ -x '*.bak_*' src_166/nath_shopify_returns/models/shopify_return_log.py nath_shopify_returns/models/shopify_return_log.py
--- src_166/nath_shopify_returns/models/shopify_return_log.py	2026-10-26 14:00:23.173521000 +0100
+++ nath_shopify_returns/models/shopify_return_log.py	2026-10-28 14:04:46.619451100 +0100
@@ -132,6 +132,30 @@
 }
 """
 
+LINE_DISCOUNTS_QUERY = """
+{
+  nodes(ids: [%(ids)s]) {
+    ... on LineItem {
+      id
+      quantity
+      discountAllocations {
+        allocatedAmountSet { shopMoney { amount } }
+        discountApplication {
+          value {
+            __typename
+            ... on PricingPercentageValue { percentage }
+          }
+          ... on DiscountCodeApplication { code }
+          ... on ManualDiscountApplication { title }
+          ... on AutomaticDiscountApplication { title }
+          ... on ScriptDiscountApplication { title }
+        }
+      }
+    }
+  }
+}
+"""
+
 RETURN_CLOSE_MUTATION = """
 mutation {
   returnClose(id: "%(id)s") {
@@ -635,12 +659,7 @@
             cod_exp, albaran = 'TEST', 'TEST/%s' % self.id
         elif config.nacex_return_method == 'label':
             cod_exp, pdf = carrier.nacex_gen_return_label(self)
-            albaran = cod_exp
-            try:
-                albaran = carrier.nacex_get_status(cod_exp)[2] or cod_exp
-            except Exception as e:
-                # Sense albarà de moment: el cron de seguiment el corregirà
-                _logger.info('Albarán Nacex %s: %s', self.remarks, e)
+            albaran = self._nacex_wait_albaran(carrier, cod_exp)
             att = self.env['ir.attachment'].create({
                 'name': 'Nacex devolucion %s.pdf' % (self.remarks or '').lstrip('#'),
                 'datas': base64.b64encode(pdf),
@@ -656,6 +675,22 @@
         self.message_post(body=msg)
         self.dev_picking_id.message_post(body=msg)
 
+    def _nacex_wait_albaran(self, carrier, cod_exp, tries=5, wait=3):
+        """Nacex assigna l'albarà uns segons després de crear l'etiqueta oberta: es pregunta
+        fins a `tries` vegades abans de pujar el seguiment a Shopify. Si no arriba, es queda
+        el codi d'expedició i el cron de seguiment el corregirà."""
+        for attempt in range(tries):
+            if attempt:
+                time.sleep(wait)
+            try:
+                albaran = carrier.nacex_get_status(cod_exp)[2]
+            except Exception as e:
+                _logger.info('Albarán Nacex %s: %s', self.remarks, e)
+                continue
+            if albaran:
+                return albaran
+        return cod_exp
+
     def _step_fedex(self):
         config = self.config_id
         carrier = config.fedex_carrier_id
@@ -962,6 +997,38 @@
         rate = sum(t.amount for t in taxes if t.amount_type == 'percent' and not t.price_include)
         return gross / (1 + rate / 100.0)
 
+    def _discount_breakdown(self, lines):
+        """Descomptes de Shopify per línia de pedido, separats en % i en € fixos (per unitat):
+        {id línia: {'pct': €/u., 'fixed': €/u., 'codes': [codi o títol]}}.
+        Si Shopify no respon, retorna {} i la rectificativa es fa com abans (descompte en % equivalent)."""
+        ids = sorted({l.shopify_order_line_id for l in lines if l.shopify_order_line_id})
+        if not ids:
+            return {}
+        try:
+            data = self._shopify_graphql(
+                self.config_id, LINE_DISCOUNTS_QUERY % {'ids': ', '.join('"%s"' % i for i in ids)})
+        except Exception as e:
+            _logger.info('Descuentos de %s: %s', self.remarks, e)
+            return {}
+        res = {}
+        for node in data.get('nodes') or []:
+            if not node or not node.get('id'):
+                continue
+            qty = node.get('quantity') or 1
+            info = {'pct': 0.0, 'fixed': 0.0, 'codes': []}
+            for alloc in node.get('discountAllocations') or []:
+                amount = float(((alloc.get('allocatedAmountSet') or {}).get('shopMoney') or {}).get('amount') or 0.0) / qty
+                app = alloc.get('discountApplication') or {}
+                if (app.get('value') or {}).get('__typename') == 'PricingPercentageValue':
+                    info['pct'] += amount
+                else:
+                    info['fixed'] += amount
+                    code = app.get('code') or app.get('title')
+                    if code and code not in info['codes']:
+                        info['codes'].append(code)
+            res[node['id']] = info
+        return res
+
     def _create_refund_invoice(self):
         """Rectificativa amb el que ha reemborsat Shopify (preu amb descompte i IVA inclòs),
         enllaçada a la factura original i a les línies de venda. Sense línies de descompte
@@ -974,6 +1041,8 @@
         if not lines:
             raise UserError(_('No hay importes reembolsados por línea para hacer la rectificativa.'))
         inv_lines = []
+        breakdown = self._discount_breakdown(lines)
+        fixed_by_tax = {}   # impostos de l'article -> descompte fix (brut), codis i compte
         for line in lines:
             sl = sale.order_line.filtered(lambda s: s.product_id == line.product_id and not s.display_type
                                           and s.price_unit > 0)[:1]
@@ -981,12 +1050,40 @@
                 raise UserError(_('El artículo %s no está en el pedido %s.') % (line.sku, sale.name))
             vals = sl._prepare_invoice_line()
             gross_unit = line.refunded_subtotal / line.qty_refund
+            refunded_unit = self._price_excluded(gross_unit, sl.tax_id)
+            price_unit, discount = refunded_unit, 0.0
+            info = breakdown.get(line.shopify_order_line_id)
+            # el desglossament de Shopify només es fa servir si quadra amb el que ha reemborsat
+            if info and line.unit_price > 0 and abs(
+                    (line.unit_price - info['pct'] - info['fixed']) * line.qty_refund
+                    - line.refunded_subtotal) <= 0.05:
+                # descompte en %: al camp Desc.% de la línia; descompte fix en €: una línia a part
+                price_unit = self._price_excluded(line.unit_price, sl.tax_id)
+                discount = round(info['pct'] / line.unit_price * 100, 4)
+                if info['fixed']:
+                    entry = fixed_by_tax.setdefault(
+                        tuple(sl.tax_id.ids),
+                        {'taxes': sl.tax_id, 'amount': 0.0, 'codes': [], 'account_id': vals.get('account_id')})
+                    entry['amount'] += info['fixed'] * line.qty_refund
+                    entry['codes'] += [c for c in info['codes'] if c not in entry['codes']]
+            elif sl.price_unit > 0 and refunded_unit < sl.price_unit:
+                # sense desglossament: preu de la comanda i descompte en % equivalent
+                price_unit = sl.price_unit
+                discount = round((1 - refunded_unit / sl.price_unit) * 100, 4)
             vals.update({
                 'quantity': line.qty_refund,
-                'discount': 0.0,
-                'price_unit': self._price_excluded(gross_unit, sl.tax_id),
+                'discount': discount,
+                'price_unit': price_unit,
             })
             inv_lines.append((0, 0, vals))
+        for entry in fixed_by_tax.values():
+            inv_lines.append((0, 0, {
+                'name': _('Descuento %s') % ', '.join('[%s]' % c for c in entry['codes'] if c),
+                'quantity': 1.0,
+                'price_unit': -self._price_excluded(entry['amount'], entry['taxes']),
+                'account_id': entry['account_id'],
+                'tax_ids': [(6, 0, entry['taxes'].ids)],
+            }))
         move_vals = {
             'type': 'out_refund',
             'partner_id': inv.partner_id.id,
@@ -996,6 +1093,7 @@
             'fiscal_position_id': inv.fiscal_position_id.id,
             'invoice_user_id': inv.invoice_user_id.id,
             'team_id': inv.team_id.id if 'team_id' in inv._fields else False,
+            'invoice_date': fields.Date.context_today(self),   # data d'aprovació del reemborsament
             'invoice_origin': sale.name,
             'reversed_entry_id': inv.id,
             'ref': _('Devolución %s (%s)') % (self.remarks, self.shopify_return_name or ''),
diff -ruN -x '*.pyc' -x __pycache__ -x '*.bak_*' src_166/nath_shopify_returns/security/ir.model.access.csv nath_shopify_returns/security/ir.model.access.csv
--- src_166/nath_shopify_returns/security/ir.model.access.csv	2026-10-26 14:00:23.166094100 +0100
+++ nath_shopify_returns/security/ir.model.access.csv	2026-10-28 09:47:30.806825000 +0100
@@ -2,6 +2,6 @@
 access_shopify_return_log_user,shopify.return.log user,model_shopify_return_log,stock.group_stock_user,1,1,1,0
 access_shopify_return_log_line_user,shopify.return.log.line user,model_shopify_return_log_line,stock.group_stock_user,1,1,1,1
 access_shopify_return_config_user,shopify.return.config user,model_shopify_return_config,stock.group_stock_user,1,0,0,0
-access_shopify_return_config_manager,shopify.return.config manager,model_shopify_return_config,stock.group_stock_manager,1,1,1,1
+access_shopify_return_config_manager,shopify.return.config manager,model_shopify_return_config,group_shopify_returns_config,1,1,1,1
 access_shopify_return_test_wizard_user,shopify.return.test.wizard user,model_shopify_return_test_wizard,stock.group_stock_user,1,1,1,1
 access_shopify_return_close_wizard_user,shopify.return.close.wizard user,model_shopify_return_close_wizard,stock.group_stock_user,1,1,1,1
diff -ruN -x '*.pyc' -x __pycache__ -x '*.bak_*' src_166/nath_shopify_returns/security/security.xml nath_shopify_returns/security/security.xml
--- src_166/nath_shopify_returns/security/security.xml	1970-01-01 01:00:00.000000000 +0100
+++ nath_shopify_returns/security/security.xml	2026-10-28 09:47:30.718058900 +0100
@@ -0,0 +1,9 @@
+<?xml version="1.0" encoding="utf-8"?>
+<odoo>
+    <data noupdate="0">
+        <record id="group_shopify_returns_config" model="res.groups">
+            <field name="name">Devoluciones Shopify: Configuración</field>
+            <field name="category_id" ref="base.module_category_hidden"/>
+        </record>
+    </data>
+</odoo>
diff -ruN -x '*.pyc' -x __pycache__ -x '*.bak_*' src_166/nath_shopify_returns/views/shopify_return_views.xml nath_shopify_returns/views/shopify_return_views.xml
--- src_166/nath_shopify_returns/views/shopify_return_views.xml	2026-10-26 14:00:23.161079200 +0100
+++ nath_shopify_returns/views/shopify_return_views.xml	2026-10-28 09:47:30.851627700 +0100
@@ -376,6 +376,6 @@
               parent="menu_shopify_returns_root" action="action_shopify_return_log" sequence="1"/>
     <menuitem id="menu_shopify_returns_config" name="Configuración"
               parent="menu_shopify_returns_root" action="action_shopify_return_config" sequence="10"
-              groups="stock.group_stock_manager"/>
+              groups="nath_shopify_returns.group_shopify_returns_config"/>
 
 </odoo>
PATCHEOF
cd /opt/tuctuc-erp/nath/custom_addons \
 && sudo tar czf ~/nath_shopify_returns_1.6.6_backup.tgz nath_shopify_returns \
 && sudo patch -p1 --dry-run < ~/nath_shopify_returns_1.6.7.diff \
 && sudo patch -p1 --no-backup-if-mismatch < ~/nath_shopify_returns_1.6.7.diff \
 && sudo /opt/tuctuc-erp/env/bin/python -m py_compile nath_shopify_returns/models/*.py \
 && grep version nath_shopify_returns/__manifest__.py \
 && echo "PATCH OK"
