---
name: pendents-tuctuc
description: "Llista de feines pendents a l'Odoo TUCTUC / Shopify a 2026-10-26, per reprendre-les en altres sessions"
metadata:
  node_type: memory
  type: project
  originSessionId: 5d271661-9bfa-41c4-b5e7-32b2987f912d
  modified: 2026-10-27T14:27:17.022Z
---

Pendent a 2026-10-26 (ordenat per importància):
- **DP 1/11 (diumenge):** provar crons 450/451 en simulació, posar SIMULAR=False i activar. Vegeu [[dp-veepee-automatitzacio]].
- **Devolucions:** activar `auto_process` i posar la Lorena a `summary_partner_ids` quan ella ho digui (l'Isaac espera la seva confirmació). Desplegar 1.6.7. Vegeu [[nath-shopify-returns-estat]].
- ~700 mail.mail en excepció des del 16/10: s'envien amb l'email de cada usuari i Office365 només accepta no_reply@tuctuc.com / no_reply@nath.es.
- Error de calendari (CORS) a "Fecha de entrega" de sale.order (passa amb qualsevol data). WT#349617 encara sense commitment_date 31/12/2099.
- Cron 447 "reintentar pedidos sin entrar": desactivat; fer que només reintenti diagnòstic REINTENTAR.
- Shopify: arxivar fitxes antigues KELLY 7926769451051 i POL 7926767484971 (SKU duplicats) — ho han de fer els d'online.
- Del context inicial: app "Envio Pedidos" (subconsulta amb més d'una fila), cua SII, recollida de prova Nacex 500139311 per anul·lar, preguntar a Nacex si genEtiquetaDevolucion accepta prealerta email.
- Roadmap Lorena: devolucions VP → Mirakl → reemborsaments ([[roadmap-devoluciones]]).

- **Conciliació Shopify (Maria):** acció 2653 "Conciliar automáticamente lo que cuadra (SIMULACIÓN)" a account.bank.statement; la Maria l'ha de provar el 27/10 després de "Asignar terceros para conciliación" (acció 2123). Si quadra, posar SIMULAR=False i treure "(SIMULACIÓN)" del nom. Codi local: `ShopifyDev/conciliar_shopify_auto.py`.
- **Factures WT que no es fan soles:** el connector només factura quan arriba el webhook orders/fulfilled; falla si no s'exporta el tracking (26 jobs "Export tracking" marcats fets a mà el 20/10, transportista "Fedex" sense Shopify Code) o si el fulfilled arriba abans de l'OUT ("no invoiceable line", no es reintenta). Proposta: cron nocturn que faci el pas de factura per a WT amb OUT fet i sense factura.

- **27/10 incident:** comandes TUCTUC no entraven (des de #350191). Causa: cron 261 "Integration: TUCTUC-Prod [6] Receive Orders" desactivat des del 06/08 → `last_receive_orders_datetime` clavada al 17/09; el connector demana `updated_at ASC` amb límit i les noves quedaven fora. Arreglat: data al 26/10 i cron 261 actiu cada hora (`update_dt=True`). 42 comandes entrades a mà; #349954, #349999, #350220 (SKU duplicat: raw_data canviat a la fitxa nova + requeue del job "Create Order from Input File") i #350194 (creat transportista extern 116 "Livraison à domicile - Standard" → Fedex Rest) entrades el 27/10. Truc: `action_create_order` no fa res si el job ha fallat; cal `queue.job.requeue` del job fallat. Si torna a passar: mirar cron 261 i la data de la integració 6.

Fet el 26/10 (tarda): cron 444 de devolucions cada hora (abans 12 h).

Fet el 26/10: correu diari 452 (OUT online sense robot → Lorena, CC Isaac, 7:30), cron 449 enllaçar variants actiu (regla 3Y→3-4Y), CC Lorena al correu de pedidos sin entrar (2645).

**Why:** l'Isaac no recorda tots els projectes oberts; així es poden reprendre.
**How to apply:** quan pregunti "què més queda", partir d'aquesta llista i comprovar a l'Odoo què ja s'ha fet.

Revisió 30/10 (només lectura):
- SII: MODA INTIMA (companyia 23) té `sii_enabled=False` → factures Veepee (diari 308 FVP) sense enviar des del 16/07 (320, cap error). Preguntar a Administració si és volgut.
- SII PRIME: factures B2B Itàlia (diari 1, FAB…) creades per l'usuari "Transporte" sense impost a les línies → AEAT rebutja "Falta DesgloseTipoOperacion" (41 des del 08/10). Les de "Comercial" porten impost 62 i s'envien.
- 3 factures Shopify en esborrany per falta de termini de pagament: WT#350194, WT#350115, WT#350013.
- Cron 68 "Store - B2B Compute Fields" no ha corregut el 30/10 (nextcall 01:40 passat).

- 30/10: columna «Fecha de vencimiento» als extractes (Maria, xecs 431): camp manual `x_fecha_vencimiento` a account.bank.statement.line (13.848 línies omplertes des del 431), vista heretada 7663 (optional show), automatitzacions 45 (extracte→apunte 431), 46 (apunte 431 date_maturity→extracte), 47 (en conciliar, extracte→apunte nou). Provat ok.
