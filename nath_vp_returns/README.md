# NATH — Devolucions VP, pilot 0.1

Versió 13.0.0.1.3: menú comú **Devoluciones Online**, amb branques separades
per Shopify i VP / PinkConnect.

Versió 13.0.0.1.2: importació adaptada al camp real `returnRequestId`,
confirmat al diagnòstic de producció del 28/10/2026 (HTTP 200, 8 elements).
La mostra de dues línies tenia estat PROCESSING i tipus HOMEPICKUP;
no és una prova d'acceptació ni confirma l'estat dels altres sis elements.
Inclou diagnòstic addicional de moviments i retorns existents:
`scripts/diagnose_vp_stock_readonly.py`, amb les mateixes variables d'entorn.

Preparació ampliada, diagnòstic i matriu de proves: [PREPARACIO_DEMO.md](PREPARACIO_DEMO.md).
Versió 13.0.0.1.1: comprovació explícita d'ACL/regles als botons i validació
de l'ID intern numèric, a més del diagnòstic anonimitzat independent.

Primera entrega: menú Inventari → Devoluciones Online → Shopify / VP, lectura API
acotada a una comanda, importació local i previsualització. No modifica
PinkConnect, no crea transport, TT/DEV ni documents comptables. Sense cron.
El connector original i el codi Shopify es conserven; en instal·lar aquesta
ampliació, el menú Shopify passa a estar sota el nou menú Devoluciones Online.

## Instal·lació en demo

1. Copiar `nath_vp_returns` a custom_addons. Dependències:
   `odoo_pink_connect` i `nath_shopify_returns` 13.0.1.6.8.
2. Reiniciar Odoo, actualitzar la llista d'aplicacions i instal·lar
   «NATH - Devoluciones VP (piloto)». No actualitzar els altres mòduls.
3. Assignar el grup «Devoluciones VP: configuración» a l'usuari de proves.
4. Inventari → Devoluciones Online → VP / PinkConnect → Configuració: crear un
   registre i seleccionar la connexió PinkConnect de la mateixa companyia.
5. Escriure l'ID intern PinkConnect d'una comanda coneguda, no els remarks.

## Primera prova sense accés extern

Al camp Exemple local, posar (substituir 123 per l'ID configurat):

```json
[{"returnRequestId":"TEST-1","orderId":"123","status":"PENDING"}]
```

Clicar «Importar ejemplo local». Repetir: no ha de duplicar la sol·licitud.
Obrir-la i clicar «Simular / previsualizar». Si no existeix la comanda al
connector, indica revisió; no inventa una associació.

## Primera lectura API

«Leer API (solo lectura)» fa un GET amb orderId i limit=50 a l'API configurada.
No crea ni accepta sol·licituds. La resposta queda a «Respuesta API».
«Importar última respuesta» espera una llista amb returnRequestId, orderId i status;
si el format real és diferent, s'atura perquè l'adaptem amb una mostra real.
Les dades originals poden contenir informació de clients: compartir-ne només
una mostra anonimitzada, conservant els noms dels camps.

Les consultes no filtren per PENDING expressament: permeten veure també
estats PROCESSING/COMPLETE en repetir la prova. No hi ha paginació automàtica
en aquesta versió; comandes amb 50 resultats poden tenir més dades.

## Pendent per al circuit complet

- Confirmar l'esquema real i implementar lectura paginada i agrupació.
- Validar unitats/SKU/OUT i crear TT/DEV sense repetir devolucions existents.
- Compartir adaptadors Nacex/FedEx amb Shopify sense registres ficticis.
- Crear transport, enviar missatge i adjunt amb recuperació de timeouts.
- Acceptar una línia i rellegir-ne l'estat abans de seguir; provar el
  comportament ES sense Home Pick Up després dels canvis de tipus de VP.
- Recepció, comptabilitat i reemborsament, amb comprovació de duplicats.

No és encara una versió del circuit complet. La instal·lació i execució
dins Odoo 13 s'han de verificar a la demo; les comprovacions locals només
cobreixen sintaxi Python/XML i les proteccions de lectura/importació.

## Canvis 13.0.0.1.4

- Solicitudes VP: la veuen tots els usuaris d'Inventari; la Configuración (API) només el grup «Devoluciones VP: configuración».
- Cada sol·licitud es diu «comanda · clienta» (com a Shopify) en lloc de l'ID tècnic. La llista mostra Fecha, Pedido, Cliente, País, Producto, Motivo i Estado VP; l'ID de la sol·licitud queda al formulari i com a columna opcional.
- Producte: es busca pel GTIN (sempre és l'EAN) i, si no, pel SKU (EAN o referència).
- Fecha: la `requestDate` de PinkConnect («29/10/2026 10:35:06», hora de Madrid).

## Canvis 13.0.0.2.0 — circuit fase 1 (llegir i crear la TT/DEV)

- Nou model **Devolución VP** (`vp.return`): una per comanda de PinkConnect, amb les sol·licituds (una per peça) a dins. Menú *VP / PinkConnect → Devoluciones* (la llista d'abans queda com a *Artículos*).
- **«Leer pendientes ahora»** (Configuración) i cron *Devoluciones VP: leer pendientes de PinkConnect* (cada hora, **desactivat**): `GET /return-requests?status=PENDING` per pàgines de 50 (`offset`). Si l'API torna la mateixa pàgina, s'atura i ho diu al resultat. Després rellegeix per `orderId` (màx. 20) les comandes que tenim en PENDING i ja no hi surten, per tenir l'estat bo (p. ex. acceptades a mà a VP).
- **Validació** (no crea res): comanda d'Odoo inequívoca i de la companyia, OUT validats i sense entregues pendents, cada peça a l'OUT amb prou unitats. Si ja hi ha una TT/DEV d'aquests OUT (feta a mà), s'aprofita. Si alguna cosa no quadra: estat *Revisar* amb el motiu.
- **Crear TT/DEV**: com «Devs masivas ONLINE» i el mòdul Shopify (retorn de l'OUT, `to_refund`), per defecte **amb tota la comanda** (és el que fa la Lorena), a la ubicació configurada. Amb **«Simular TT/DEV»** (per defecte) només escriu al xat el que crearia. Automàtic només si «Crear TT/DEV automáticamente» i sense simular.
- Encara **no**: transport (Nacex/FedEx), missatge a la clienta, acceptar a VP (`PUT …/PROCESSING`), recepció ni reemborsament.

## Canvis 13.0.0.2.1 — circuit fase 2 (transport, missatge, acceptació, recepció)

Botó **«Procesar»** a la devolució: fa tots els passos seguits. Cada pas queda desat abans del següent; si un falla, la devolució queda a *Revisar* i **«Reintentar»** continua pel pas que faltava, sense repetir res.

1. **TT/DEV** només amb els articles que demana VP («TT/DEV con todo el pedido» desmarcat per defecte). Abans de crear res, totes les peces han d'estar PENDING a VP.
2. **Etiqueta**, sempre amb els transportistes de la configuració, **mai el de l'OUT** (els OUT de VP de França porten el «Fedex» antic, arxivat):
   - ES: **eDevoluciones 44 Nacex** (350), eDevolución oberta (`genEtiquetaDevolucion`), com Shopify.
   - FR: **Fedex Rest** (346), enviament d'importació i **recollida a domicili** l'endemà feiner (horari de «Parámetros de transporte»), amb la instrucció «PREVENIR A L'AVANCE». Si FedEx no accepta la recollida, s'atura (no passa a entrega a punt).
   - Pes, mides, magatzem de destí i horari: els de la configuració de Devoluciones Shopify («Parámetros de transporte»).
   - Comandes d'una altra companyia que el transportista (p. ex. MODA INTIMA) → *Revisar*.
3. **Missatge a la clienta** per PinkConnect (`POST /orders/{id}/notifications`, multipart `subject`, `message`, `attachedFile`) amb l'etiqueta. Textos ES i FR a la configuració (pestanya «Mensajes a la clienta»); el FR porta la data i la franja reals. Si no hi ha resposta, en reintentar es miren els missatges de la comanda (`GET /notifications?orderId=`) abans de tornar-lo a enviar.
4. **ES:** el registre «Recogida a domicilio» de PinkConnect (Tracking «Entrega a punto», Agencia NACEX) no té API documentada: es fa a mà, es marca «Recogida registrada en VP» i es torna a «Procesar».
5. **Acceptar a VP**: `PUT /return-requests/{id}/PROCESSING` una per una, rellegint l'estat després de cada una. Mai COMPLETE.
6. **Recepció**: quan el magatzem valida la TT/DEV, la devolució passa a *Recibida*. **La rectificativa la fa PinkConnect** (en validar una devolució d'una comanda VP posa `auto_invoice_state = waiting` i el seu cron de facturació automàtica la crea): el mòdul no en fa cap.

Amb **«Simular (no crea nada)»** marcat (per defecte), «Procesar» només escriu al xat tot el que faria: TT/DEV, etiqueta, data de recollida, text del missatge i línies que acceptaria.

Després d'actualitzar, a la configuració: «Parámetros de transporte» = TucTuc (Shopify), ES = eDevoluciones 44 Nacex (350), FR = Fedex Rest (346).

Treta la previsualització antiga d'«Artículos VP» (text de la 1.3).
