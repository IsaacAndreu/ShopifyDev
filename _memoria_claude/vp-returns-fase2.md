---
name: vp-returns-fase2
description: "nath_vp_returns 2.1 (transport, missatge VP, PROCESSING, recepció) preparada a 02/11; transportistes VP i per què la DEV només porta el que demana VP"
metadata:
  node_type: memory
  type: project
  originSessionId: 5d271661-9bfa-41c4-b5e7-32b2987f912d
  modified: 2026-11-02T15:42:30.233Z
---

- 02/11: TT/DEV/0082885 (VP-033067, 3 peces) **anul·lada** per ordre de l'Isaac: sense etiqueta/missatge/acceptació no té sentit. VP-033067 torna a «Validada» (només MAYA 8Y x1). Config 1: simulate=True, return_full_order=False (l'Isaac vol **només els articles que demana VP**).
- **Per què només els articles VP:** en validar una DEV d'una comanda VP, `odoo_pink_connect` (stock_picking.action_done) posa `auto_invoice_state='waiting'` i el seu `cron_auto_invoicing` crea la rectificativa sola de tot el que s'ha retornat. El mòdul no ha de fer rectificativa.
- **Transportistes (Isaac: «Sí, 350 i 346»):** ES = 350 «eDevoluciones 44 Nacex (devoluciones web)», FR = 346 «Fedex Rest». Mai el de l'OUT: els OUT VP de França porten el 298 «Fedex» antic (arxivat, sense Shopify Code; és el que va bloquejar Export tracking el 20/10). 175 OUT VP són de MODA INTIMA (cia 23, «Nacex MI»): sense transportistes de devolució → Revisar.
- **2.1 preparada, NO instal·lada** (`nath_vp_returns_13.0.0.2.1.tar.gz`, script `actualitzar_nath_vp_returns_2.1.sh`): botó «Procesar» = DEV → etiqueta (Nacex label / FedEx + recollida «PREVENIR A L'AVANCE») → POST /orders/{id}/notifications amb PDF → (ES: casella «Recogida registrada en VP», a mà) → PUT PROCESSING un a un amb relectura → Recibida en validar la DEV. Fa servir els mètodes Nacex/FedEx de nath_shopify_returns amb un adaptador (`_CarrierData`) i «Parámetros de transporte» = shopify.return.config 1.
- No provat contra l'API real: format de resposta de /notifications, camp `remarks` del pickup FedEx, que el PUT torni 2xx.

**Why:** és el pas que faltava perquè una devolució VP sigui útil per a la clienta.
**How to apply:** després d'instal·lar, posar a config 1 transport_config_id=1, nacex_carrier_id=350, fedex_carrier_id=346; primer «Procesar» amb Simular a VP-033067 (FR), i la primera real una a una amb l'Isaac. Relacionat: [[roadmap-devoluciones]], [[nath-shopify-returns-estat]].
