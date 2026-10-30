---
name: eci-mirakl-pedidos-encallats
description: Comandes ECI (Mirakl) que queden sense comanda de venda ("Order not created, check feed lines") i el cron 453 que ho automatitza
metadata:
  type: project
---

- Mòdul `eci_mirakl` (Brain Station 23) a `/opt/tuctuc-erp/nath/custom_addons/eci_mirakl`. Flux: Import :45 → Accept :47 → Download :50 (l'hora següent crea el mapping si SHIPPING) → Evaluate :59 (crea SO només amb línies `available` + `SHIPPING` + producte).
- Falla per tandes horàries senceres (100 comandes des del 18/10). El 29/10 el log mostra que ECI va retornar SHIPPING a capçalera i línies i tot i així l'Evaluate del cron va fallar 12 cops; la Xapusa CheckStock (acció 2364) de l'Isaac a les 19:09 ho va arreglar sense canviar les línies. Causa no trobada al codi; sospita: reinicis (8 el 29/10). L'Isaac no vol més voltes amb això.
- Cron 453 / acció 2662 "ECI: crear pedidos que se han quedado sin crear": cada hora a les :15, mappings ECI sense SO d'1 h a 7 dies; fa el mateix que la Xapusa. Creat 30/10, provat en simulació i **activat en real el 30/10** (SIMULAR=False) (0 encallades; amb finestra ampliada veu les 2 de juliol). Codi: no es pot fer `rec.camp = x` (STORE_ATTR), cal `write`.
- 2 comandes ECI de juliol (…20260718142418_1, …20260722141526_1) encallades per `not_available` — cas diferent.
- Log Odoo: `/var/log/odoo/tuctuc-erp.log` (UTC, cal `grep -a`). Jobs: GC (cron 57) requeue started al cap de 180 min; proposta pendent: requeue de Started al script de reinici.

**Why:** problema recurrent que es resol a mà des d'Order Mapping.
**How to apply:** si torna a quedar alguna ECI sense SO, mirar primer el log del cron 453 (ir.logging, func = nom de l acció). Relacionat: [[pendents-tuctuc]].
