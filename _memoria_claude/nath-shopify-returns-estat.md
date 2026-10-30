---
name: nath-shopify-returns-estat
description: Estat del mòdul nath_shopify_returns a producció TUCTUC i on és el codi local (a 2026-10-26)
metadata:
  node_type: memory
  type: project
  originSessionId: 5d271661-9bfa-41c4-b5e7-32b2987f912d
  modified: 2026-10-28T15:55:19.416Z
---

- 30/10: a producció hi ha la **13.0.1.6.8** (veure [[resum-29-30-octubre]]). Històric: 1.6.6 el 26/10, 1.6.7 el 28/10.
- 28/10: la 1.6.7 inclou també `invoice_date` = avui a la rectificativa (la Lorena la veia sense data). Script regenerat; desplegament ajornat a més tard (hi ha gent treballant). Config prod: auto_process=No, auto_post_refund=No (rectificativa en esborrany).
- 28/10: la 1.6.7 ja és a producció (installed 13:07 UTC). Documentació en 4 PDFs a `ShopifyDev/documentacio/` (generats amb `make_docs.py` al scratchpad); si canvia res important, regenerar-los.
- Codi local: `ShopifyDev/nath_shopify_returns` (versió actual), bases per fer diffs: `src_orig` (1.6.5 del servidor), `src_166`. Desplegament = script amb `patch -p1` enganxat/pujat al servidor, després `-u nath_shopify_returns` amb el servei en marxa i **després** `systemctl restart` (l'Isaac no vol `stop`).
- FedEx: la clau de producció de l'Odoo (transportista "Fedex Rest", compte 949903834) **no** és del projecte "Odoo Prime Collections" de l'usuari NATH2 (aquest només té clau de prova). Pickup Request i Locations Search ja s'han afegit a la clau correcta; la recollida FR ja funciona.
- Nacex genEtiquetaDevolucion només retorna cod_exp|bultos|pdf; l'albarà (agència/número) surt a getEstadoExpedicion (camps 7 i 8).
- Plantilla 65 envia des de `TUC TUC <no_reply@tuctuc.com>` (servidor TUCTUC NO REPLY) amb auto_delete=False; Office365 rebutja qualsevol altre remitent.

**Why:** feina repartida en diverses sessions (també des de casa); cal saber què hi ha desplegat.
**How to apply:** abans de tocar el mòdul, comprova `installed_version` a ir.module.module i fes el diff contra la versió desplegada. Relacionat: [[roadmap-devoluciones]].
