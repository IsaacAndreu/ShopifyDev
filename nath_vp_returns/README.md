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
