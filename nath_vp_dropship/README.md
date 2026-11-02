# nath_vp_dropship

Automatitza el procés diari de Dropshipping Veepee/Privalia. Substitueix:

- VentePriveeSync.exe;
- l'Excel amb fórmules;
- «Import Sale Order»;
- l'importació d'actualització;
- l'actualització del Dropshipping Veepee Product ID.

La confirmació, les agrupacions i les oleades les continuen fent els crons 450 i 451.

## Flux

1. **Cron «Veepee DP: descargar batches y crear pedidos»** (cada 5 min). Dins de l'horari configurat (per defecte de 12:00 a 17:30, cada 30 min), fa aquests passos:
   - entra a `https://dropshipment.veepee.com/api/v3/` (`auth/login`);
   - mira les campanyes (`operations`) i els batches (`operations/{op}/batches`);
   - baixa els batches nous (`…/batches/{batch}` → `deliveryOrders`) i en guarda el JSON al batch.
2. **Validació** de cada comanda, que queda en *Pendiente* o en *Error*:
   - EAN → variant (per codi de barres);
   - `LI_Pays` (país#transportista) → transportista i tarifa (pestanya *Transportistas*);
   - preu: **per defecte, les comandes es creen a preu 0**. A TUCTUC els preus els posa el company quan s'ha de facturar. Si es marca «Precios del fichero de la campaña», el preu es busca per EAN + tarifa al menú *Precios* (fitxer importat), i sense preu la comanda no es crea;
   - si ja existeix una comanda `DP-<n>`, no es crea.

   Si hi ha errors, s'envia un correu (des de `no_reply@tuctuc.com`) amb la llista.
3. **Creació de les comandes**, amb «Crear pedidos automáticamente» o amb el botó del batch.
   El botó «Crear pedidos» (1.2) ho fa tot en segon pla: un `queue.job` crea 50 comandes i n'encua
   un altre fins que no en queden. Si un restart deixa el job en `started`, al cap de 20 min es pot
   tornar a prémer el botó. Les comandes es creen en esborrany (no es confirma res).
   **Confirmació, agrupacions i oleades (1.2, abans crons 450 i 451):** amb «Confirmar y agrupar
   automáticamente», el cron «Veepee DP: confirmar pedidos y crear agrupaciones y oleadas» (cada 2 min)
   fa, entre setmana de 17:00 a 07:00 i el cap de setmana tot el dia:
   - confirma els pedidos `DP-` en esborrany un a un (`confirm='yes'`, commit per pedido) durant
     90 s per execució; només els que tenen transportista, data, modo i plazo de pago (si un pedido
     del mòdul no té modo de pago, posa el de la configuració); els que fallen no es tornen a provar
     fins al cap de 24 h;
   - quan no en queda cap per confirmar: agrupacions dels OUT reservats (sense res preparat, no al
     SORTER) per transportista + data prevista, `B-DP_<transportista>_<ddmmaa del batch>`, màxim 150
     repartits per igual (`_1`, `_2`…), i «Crear transfer para oleada» de cada una; una cada vegada,
     amb commit, per no bloquejar els altres crons.
   Tot queda a *Ajustes → Técnico → Registros* amb els mateixos noms que els crons 450 i 451.
   Botons a la configuració: «Simular confirmación y agrupaciones» (no canvia res) i «Confirmar y
   agrupar ahora» (una execució sense mirar l'horari). **Quan s'activi, desactivar els crons 450 i 451.**
   - primer, el *Dropshipping Veepee Product ID* de cada variant (la part del `Product_Code` abans de `_`);
   - després, una comanda `DP-<orderId>` per cada comanda de Veepee, amb aquestes dades:
     - client, tarifa (ES / FR-BENELUX / IT), preu del fitxer, IVA;
     - temporada, marca i tipus de comanda;
     - equip, comercial, modo i plazo de pago;
     - transportista;
     - *Fecha de entrega* = data del batch + N dies;
     - *Remarks* = `LI_Intitule` (`campanya#batch#comanda#referència`).

   Fa commit després de cada comanda i, a cada execució, treballa com a molt «Segundos por ejecución» segons.
4. **No es tanca res a Veepee.** A TUCTUC mai s'ha fet servir el «Cerrar Batch» de VentePriveeSync, així que el mòdul no té el botó. El mètode `action_close_veepee` hi és però no surt enlloc. Com que els batches queden oberts, el mòdul recorda quins ha baixat i només mira els creats des de «Solo batches creados desde».

Les comandes amb error no es creen. Per tornar-les a provar: s'arregla el mapeig o el preu i es clica **«Volver a validar»** al batch.

## Configuració (Ventas → Veepee DP → Configuración)

Valors de les comandes DP d'octubre de 2026 a producció (ids de TUCTUC_PRODUCTION):

| Camp | Valor |
|---|---|
| Cliente | VENTE-PRIVEE.COM SA SUCURSAL EN ESPAÑA (14260) |
| Dirección de entrega | 270844 (Santa Oliva Manhattan) |
| Impuestos | IVA 21% (Bienes) (1) |
| Tipo de pedido / Temporada / Marca | PED. INICIAL (1) / WEB (28) / WEB (310) |
| Equipo / Comercial | Online (6) / Online (2522) |
| Modo de pago / Plazo | CONFIRMING / SIN AVISO / SIN RECURSO (118) / A LA VISTA (299) |
| Tarifas | Veepee - ES (20267), Veepee - FR_BENELUX (20268), Veepee - IT (20269) |
| Almacén | Oriola - Amposta (1) |

**Transportistas:**
- *Importar Excel → Mapeo de transportistas* amb `MAPPING_CARRIER.xlsx` (columnes LI_Pays, odoo_carrier i tarifa);
- o bé el botó «Añadir transportistas 'Veepee - …'», que fa servir els noms `Veepee - <país> - <clau>`.

**Preus:** opcional. Només si es marca «Precios del fichero de la campaña»: *Importar Excel → Precios* amb el fitxer de la campanya (EAN + Tarifa ES / FR-BENELUX / IT) i el codi de la campanya (TTUC85).

**API:** l'usuari i la contrasenya els posa l'administrador (són els mateixos que hi ha al `.config` de VentePriveeSync). No s'han d'enviar per correu ni per xat.

## Proves

- **Sense Odoo:** `python -I scripts/check_vp_dropship.py <carpeta del privalia_demo_kit>`. Compara el resultat amb els fitxers esperats del kit:
  - preu, tarifa i unitats de cada línia (fitxers 07 i 08);
  - transportista i remarks (fitxer 09);
  - Veepee IDs (fitxer 12).

  També comprova que el format de l'API dona el mateix que l'Excel. Resultat a 30/10/2026: **TOT OK**, tant amb 150 comandes com amb 10.000 unitats.
- **Demo:** «Simular API» activat, i *Importar Excel → Batch* amb l'Excel de VentePriveeSync (o els fitxers 03 i 04 del kit). Vegeu PREPARACIO_DEMO.md.
- **Producció:**
  1. Primer «Simular API» amb l'Excel del dia, comparant amb el que es fa a mà.
  2. Després «Probar conexión» i «Buscar batches ahora» amb «Crear pedidos automáticamente» desactivat.
  3. Quan quadri, activar el cron.

## Pendent de confirmar amb l'API real

- El format exacte de `deliveryOrders`. Els noms de camp surten de VentePriveeSync.exe: `orderId`, `zipCode`, `city`, `country`, `carrierKey`, `details[].productId/supplierReference/quantity/ean13List`.
- El 4t camp de `LI_Intitule` (es fa servir `id` de la deliveryOrder).
- L'estat d'un batch tancat (es descarten `Done` i `Closed`).
