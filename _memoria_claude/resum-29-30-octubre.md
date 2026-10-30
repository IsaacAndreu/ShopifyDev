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
