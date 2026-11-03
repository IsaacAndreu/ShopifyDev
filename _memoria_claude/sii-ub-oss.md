---
name: sii-ub-oss
description: UB (cia 21) factures Shopify amb impostos IE/HU VAT no OSS → SII 4102; com es van corregir el 03/11 i el «Factura duplicada» fals
metadata:
  type: project
---

- Error SII `Codigo[4102] El XML no cumple el esquema` a factures d'UB = `TipoDesglose` buit perquè la línia porta un impost creat pel connector Shopify («IE VAT 23.0% [included]» 1571, «HU VAT 27.0% [included]» 1574): sense oss_country_id ni compte (l'IVA anava a 700/705). Els bons: 1554 IVA IRLANDA 23% - OSS, 1561 IVA HUNGRIA 27% - OSS (compte 47700012). Comptabilitat ho va confirmar.
- 03/11: mappings integration.account.tax.mapping 102 (Code22men IE) → 1554 i 275 (Locker Gear HU) → 1561. Corregides INV/2026/2324, 2328, 2195 (esborrany → impost OSS → publicar → reconciliar amb el SHP/... → SII). Pendents per decidir: INV/2026/1940 (3T) i 0801 (2T, 0 €).
- En republicar, el SII d'UB envia dues vegades: la primera queda «Correcta» a Hisenda i l'Odoo guarda la segona («3000 Factura duplicada», RegistroDuplicado Correcta). Es marca a mà sii_state=sent amb el CSV de la resposta.

**Why:** evita tornar a investigar el 4102 i el duplicat fals.
**How to apply:** si torna un 4102 a UB, mirar primer l'impost de les línies i el mapping d'impostos del connector.
