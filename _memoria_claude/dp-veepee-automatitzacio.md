---
name: dp-veepee-automatitzacio
description: "Confirmació i agrupacions automàtiques dels pedidos DP (dropshipping Veepee/Privalia) a TUCTUC: crons 450 i 451, regles d'agrupació, pla per a la campanya de l'1/11/2026"
metadata:
  node_type: memory
  type: project
  originSessionId: 5d271661-9bfa-41c4-b5e7-32b2987f912d
  modified: 2026-10-26T13:45:19.222Z
---

- Crons creats el 2026-10-26, **desactivats i amb `SIMULAR = True`**: id 450 "DP: confirmar pedidos automaticamente" (sale.order) i id 451 "DP: crear agrupaciones y oleadas" (stock.picking), cada 2 min, usuari IT. Codi local: `ShopifyDev/dp_confirmar_auto.py` i `dp_agrupaciones_auto.py`.
- Horari: entre setmana de 17:15 a 07:00 (Madrid), cap de setmana tot el dia. Només confirma DP amb transportista i fecha de entrega (els posa l'Isaac al pas d'actualització). Les agrupacions esperen que no quedi cap DP per confirmar.
- Regles d'agrupació (de l'Isaac): **màxim 150 OUT per agrupació**; nom `B-DP_<transportista sense "Veepee - ">_<ddmmaa>` (ddmmaa = dia abans de la data prevista); si n'hi ha més d'una del mateix nom, **_1, _2, _3… començant per _1**. "Crear transfer para oleada" = `create_transfer_for_batch` (sorter_batch): necessita OUT reservats, mateix estat i ubicació.
- Pla: diumenge **1/11/2026** (inici campanya) l'Isaac puja i actualitza; executem tots dos en simulació, revisem, posem `SIMULAR = False`, activem els crons i "Ejecutar manualmente" al 450. Primer dia ho fa l'Odoo; després es decideix.
- Ja no es venen SETs: no cal fer agrupacions `_KIT` a part (confirmat per l'Isaac, 2026-10-26).
- Servidor: limit_time_real 9999, limit_time_real_cron -1, max_cron_threads 4.

**Why:** confirmar 500–1.700 DP/dia col·lapsava l'Odoo en horari laboral i l'Isaac ho feia des de casa.
**How to apply:** abans de tocar res de DP, llegir l'estat dels crons 450/451 a l'Odoo; respectar les regles de noms i el màxim de 150. Relacionat: [[roadmap-devoluciones]].

- Idea següent (30/10): baixar i crear els pedidos DP sols. VentePriveeSync.exe (a `Downloads\vp\vp\VentePriveeSync_1100`) usa l'API REST `https://dropshipment.veepee.com/api/v3/`: `POST auth/login` → `access_token`; `GET operations` (campanyes); `GET operations/{op}/batches`; `GET operations/{op}/batches/{batch}` → `deliveryOrders`; `POST …/batches/{batch}/close`. Credencials al `.config` (no llegir-les; l'Isaac les posarà ell a l'Odoo). Manual per campanya: fitxer de preus i transportistes nous. Fer-ho després de l'1/11.
- 30/10: mòdul **nath_vp_dropship 13.0.0.1.0** escrit a `ShopifyDev/nath_vp_dropship` (+ `nath_vp_dropship_13.0.0.1.0.tar.gz`). Models vp.dropship.config/carrier/price/batch/order, cron cada 5 min (inactiu), mode «Simular API» amb l'Excel. Lògica pura a `models/vp_parse.py`; prova `scripts/check_vp_dropship.py vp_kit` = TOT OK (150 i 10.000 unitats vs fitxers 07/08/09/12 del kit). **No provat encara dins d'Odoo** (falta demo). Kit descomprimit a `ShopifyDev/vp_kit`. Valors reals DP a prod: client 14260, entrega 270844, tipus 1, temporada 28, marca 310, equip 6, comercial 2522, modo 118, plazo 299, tarifes 20267/20268/20269, IVA 1.
- 30/10: no hi ha demo. L Isaac el vol instal·lar a PRODUCCIÓ dissabte 31/10 amb `install_nath_vp_dropship.sh` (-i amb servei en marxa + restart). Pla segur: Simular API, cron inactiu, auto_create off; provar amb un Excel de batch antic (comandes ja existents → «Ya existía») i comparar preus/transportistes amb les DP reals; després Probar conexión / Buscar batches (només lectura) sense crear comandes.
- Objectiu de l Isaac (30/10): que DP vagi 100% sol (batch 12-14h, crear comandes, confirmar/agrupar des de les 17h) perquè pugui fer vacances o marxar sense que l altre informàtic ho hagi de fer a mà. Prioritzar robustesa, avisos per correu i documentació per a un successor.
- A TUCTUC no es tanquen mai els batches de Veepee ni es comuniquen ruptures (l Isaac només baixa l Excel). Botó «Cerrar batch» tret de la vista (30/10); paquet refet, SHA E054…806F.
- 30/10: les DP es creen a PREU 0 (el company posa els preus en facturar). Opció `use_price_file` (per defecte desmarcada). Paquet final per dissabte: SHA D646B024…98AA6.
- **31/10 INSTAL·LAT A PRODUCCIÓ** (17:20, mòdul id 830). Cron 454 «Veepee DP: descargar batches y crear pedidos» (OdooBot, inactiu). Grup 134 «Dropshipping Veepee: Configuración» = admin + Isaac (196); menú Ventas → Veepee DP (1662) només per al grup (també a `views/menus.xml` al repo; el servidor té l'XML antic fins al pròxim paquet). Config id 1: valors reals DP, tarifes = 2303 «WholeSale ES-PT» (la per defecte del client; l'Isaac no vol tarifes Veepee), preu 0, avisos a isaac.andreu@nath.es, servidor correu 1. 18 transportistes del MAPPING_CARRIER real (TTUC83). Nota: el pay mode 118 és «Envio Cheque», plazo 299 «Miravia», equip 6 «Jordi Miró» (així són les DP reals).
- 31/10 prova simulació amb `Documents\TTUC85_1925798_05-10-2026.xlsx` → batch 1: 505 comandes / 2.881 u, totes «Ya existía», productes/transportistes/remarks 505/505 iguals que les reals. Després l'Isaac va posar credencials, Simular API desmarcat: «Probar conexión» OK (campanya TTUC86 01/11–08/11, l'API no torna `id`, només `code`), «Buscar batches ahora» = No hay batches nuevos. auto_fetch/auto_create encara desmarcats.
- Pendent: treure el botó genèric «Importar» de la llista de Batches (confon). Pla 1/11: activar cron 454 + auto_fetch (sense auto_create), comparar el primer batch amb el manual, després auto_create; crons 450/451 com estava previst.
- Planificació TTUC86 (de Veepee): campanya 01/11 19:00 – 09/11 6:00; batches cada dia a les 12:00 del 02/11 al 08/11 (també dissabte i diumenge) i l'últim el **09/11 a les 7:00**. Per tant el primer batch és **dilluns 02/11**, no l'1/11. L'Isaac vol Fecha de entrega = dia del batch + 1 (delivery_days 1) i cerca des de les 12:00 (fetch_from 12; el del 09/11 es baixarà a les 12:00). A mà ho feia variable (0 o +1).
