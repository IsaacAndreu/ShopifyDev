---
name: resum-29-30-octubre
description: "Estat a 2026-10-30 segons ShopifyDev/RESUM_TREBALL_ULTIMS_3_DIES.md: returns 1.6.8 a prod, guard FedEx 1.1.0, pilot nath_vp_returns, nath_exchange_billing"
metadata:
  type: project
---

Font completa: `ShopifyDev/RESUM_TREBALL_ULTIMS_3_DIES.md` (escrit el 30/10, feina feta en altres sessions).

- nath_shopify_returns **13.0.1.6.8** instal·lada a producció (diversos OUT per comanda → una TT/DEV). Script: `deploy_nath_shopify_returns_restart.sh`.
- delivery_fedex_rest2 **13.0.1.1.0** (guard d'idempotència: reutilitza el tracking, 0 POST duplicats) preparat; tar bo = `delivery_fedex_rest2_13.0.1.1.0.tar_(1).gz` (el primer era de 0 bytes). Scripts preflight/deploy. Falta prova en demo i revisar logs.
- `nath_vp_returns` 13.0.0.1.3: pilot VP/PinkConnect només de consulta (menú Devolucions Online). NO a producció; falta TT/DEV, PUT d'estats, home pickup, reemborsaments.
- `nath_exchange_billing` 13.0.0.1.0: facturar cada sortida real de canvis (cas #349292), sense rectificativa global ni reemborsament Shopify duplicat. Provar en demo.
- Acció massiva 2657 "Aceptar y reembolsar devoluciones seleccionadas" creada (29/10) i verificada el 30/10; missatges passats a castellà. Sense diàleg de confirmació ni grup. Producció confirmada: returns 13.0.1.6.8 i delivery_fedex_rest2 13.0.1.1.0 instal·lats (29/10).

**Why:** hi ha feina feta en sessions paral·leles que aquesta sessió no va veure.
**How to apply:** abans de tocar returns/FedEx/VP, comprovar versions instal·lades; relacionat amb [[nath-shopify-returns-estat]] i [[pendents-tuctuc]].

30/10 (tarda): acció 2659 "Marcar como hecha a mano" (shopify.return.log → state closed, sense tocar Shopify/Nacex/DEV). Acció 2660 "DEV única de varios OUT" (stock.picking, llista): una TT/DEV amb tots els OUT Hechos d'una comanda; validacions provades, creació real encara no (primer ús previst: #349867). Ull: a les accions de servidor d'Odoo 13 **no existeix `UserError`**, cal `Warning` (2657 corregida).
- **01/11: nath_vp_returns 13.0.0.1.3 instal·lat a PRODUCCIÓ** (11:48). Menú Inventario → Devoluciones Online → Shopify / VP. Canvis a mà (i al codi com a 13.0.0.1.4, no desplegat): Solicitudes per a stock.group_stock_user (ACL 2580/2581, menú 1668 sense grup), Configuración només grup 135 (Isaac). Config id 1 «Pink VP Live - piloto», connexió 1, comanda prova 26262438 (VP-032863). «Leer API» OK: 5 return requests PROCESSING, type SENDTOSELLER; el `sku` de vegades és EAN i de vegades default_code; la DEV de la Lorena (TT/DEV/0082836) té 6 peces i PinkConnect només 5 (falta 11397995_10A). Errors «reading 'target'» = menús en memòria cau → Ctrl+Shift+R.
- 01/11: el restart de la instal·lació va deixar 5 jobs «Export Product Quantities» en started → requeue manual. Proposta pendent: requeue automàtic a l'script de reinici.
- **01/11 nath_vp_returns 13.0.0.2.0 a PRODUCCIÓ** (12:22): model vp.return (una per comanda), «Leer pendientes ahora», cron 455 (inactiu), validació i creació TT/DEV (simulate=True). Config 1: ubicació 517653 WH-OR/Stock/DEVOLUCION_ONLINE, return_full_order=True. Primera lectura: 23 PENDING → 9 devolucions validades + VP-032863 adoptada (TT/DEV/0082836). Paginació amb `offset` sense problemes (1 pàgina). Dubte obert: TT/DEV amb tota la comanda (com la Lorena) o només el que demana VP (VP-032317: VP 1 u, OUT 16 u).
- Cada restart deixa jobs d'export en started (3 vegades el 01/11) → requeue manual.
- 01/11 12:36: simulació de «Crear TT/DEV» a VP-033067 OK (només nota al chatter, estat validated, 0 pickings creats). Pendent 02/11: l'Isaac pregunta a la Lorena comanda sencera vs només peces de VP → ajustar return_full_order, treure simulate i fer 1 TT/DEV real amb ella. Pendent 2.0.1: treure/actualitzar el botó vell «Simular / previsualizar» d'Artículos VP (text de la 1.3, despista).
