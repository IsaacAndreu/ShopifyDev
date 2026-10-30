# nath_shopify_returns

Automatitza les devolucions de la web: Shopify → TT/DEV a Odoo → Nacex (servei 44) → aprovació a Shopify.

## Flux per devolució

| Estat | Pas |
|---|---|
| Pendent | El cron llegeix de Shopify les comandes amb `return_status:return_requested` |
| Validada | Troba la `sale.order` per `ref_remarks` i els OUT **Hecho** compatibles. Una comanda completament servida en diversos OUT es tracta conjuntament. Si encara hi ha OUT pendents o ubicacions incompatibles, va a revisió manual |
| TT/DEV creada | El mateix assistent que "Devs masivas ONLINE": per defecte, amb tota la comanda |
| Nacex OK | `putExpedicion` servei 44. **Referència = TT/DEV**, **Observacions = TT/DEV + remarks**. El tracking de Nacex es guarda a la TT/DEV |
| Aprovada | `returnApproveRequest` a Shopify i, a continuació, el seguiment Nacex a la devolució (`reverseDeliveryCreateWithShipping`). Així "No se requiere envío" queda lliure per als casos manuals |
| Rebuda | El magatzem valida la TT/DEV. Es comparen les unitats esperades amb les rebudes; si hi ha diferències, queda a revisió |
| Reemborsada | La Lorena clica **Acceptar i reemborsar**: rectificativa a Odoo (com feia `presta_auto_invoicing`, en esborrany per defecte) i reemborsament a Shopify **només de les unitats rebudes** |

- **Revisió manual:** errors de negoci (no troba la comanda, SKU que no quadra, error de Nacex o de Shopify). El sistema no la torna a intentar sola: cal clicar "Reintentar".
- **Error tècnic:** timeout, HTTP… Es reintenta sola fins a `max_attempts`.
- Cada pas fa commit, de manera que ni la TT/DEV ni la recollida de Nacex es creen mai dues vegades.
- Si cancel·les una devolució que ja tenia la TT/DEV creada (i encara no rebuda), també es cancel·la la TT/DEV.

## Instal·lació

1. Copia la carpeta a `custom_addons`, reinicia Odoo i instal·la **NATH - Devolucions Shopify automàtiques**.
2. **Transportista:** duplica el transportista Nacex actual → *Nacex eDevoluciones TUC TUC* amb:
   - Service Code **44**
   - Carriage **D**
   - Packaging **2**
   - Agency **4307**
   - Customer Code **60527**
3. **Contacte d'entrega:** TUC TUC, C/Rin 6-8, 43870 Amposta, 977707005.
4. **Configuració** (Inventari → Devolucions Shopify → Configuració), una per botiga Shopify: integració, companyia, transportista, contacte d'entrega i ubicació (`WH-OR/Stock/DEVOLUCION_ONLINE`, o la de MODAI per a la companyia 23).
5. **Shopify:** l'app necessita els permisos `read_returns` i `write_returns`, i una versió de l'API recent (2024-01 o posterior).

## Proves

### A. Producció: comprovació només de lectura (sense instal·lar res)

```bash
odoo shell -c /ruta/odoo.conf -d NOM_BD --no-http < scripts/check_shopify_returns_readonly.py
```

L'script:

- mostra els permisos de l'app de Shopify i les devolucions sol·licitades;
- per cada devolució, diu què faria el mòdul (OK, revisió o ja té DEV);
- no crida Nacex, no aprova res i acaba amb rollback.

### B. Demo: simulació

1. Instal·la el mòdul a la demo.
2. A la configuració, marca **Simular Shopify** i **Simular Nacex**.
3. Clica **Crear devolució de prova** i escriu el remarks d'una comanda amb l'OUT Hecho i el teu email.
4. Clica **Processar**. Es crea la TT/DEV de veritat, i al xat queda la cadena exacta que s'enviaria a Nacex (referència = TT/DEV, observacions = TT/DEV + remarks).
5. Opcional: desmarca **Simular Nacex** per fer UNA recollida real amb el teu email, i després cancel·la-la a My Nacex → Gestión. La demo té les credencials de Nacex de producció.

### C. Producció: pilot


1. Deixa **Processar automàticament** desmarcat.
2. Clica **Llegir devolucions ara**. Es creen els registres en estat Pendent.
3. Obre'n una i clica **Processar**.
4. Comprova a *My Nacex → Gestión* que la recollida queda igual que una de les que es fan a mà, i mira quin email rep el client.
5. Quan tot quadri, activa el cron *Devolucions Shopify: llegir i processar* i marca **Processar automàticament**.

## Punts a validar a la primera prova

- **Camps de recollida:** Nacex pot rebutjar `nom_rec`, `dir_rec`, `cp_rec`, `pob_rec`, `pais_rec` i `tel_rec`, o les longituds que hi posem. Si passa, ajusta-ho a `models/delivery_carrier.py`.
- **Email al client:** comprova si la prealerta (`tip_pre1=E`, `pre1`=email del client) és el mateix email "eDevoluciones SHOP" que envia la web. Si no ho és, activa **Enviar etiqueta PDF des d'Odoo**.
- **SKU:** es busca pel producte enllaçat al connector (el SKU de Shopify no sempre és el `default_code`, p. ex. `21118499_7Y` → `21118499_7-8Y`), o per `default_code` o `barcode`.

## Canvis 1.6.6

- SKU validat amb l'enllaç del connector (variant de Shopify → producte d'Odoo).
- Línia **No se devuelve**: el client demana tornar una cosa que no va rebre. No es busca a l'OUT, no s'espera a la TT/DEV ni es reemborsa.
- FedEx: si la recollida a domicili falla (p. ex. `FORBIDDEN`), el client porta el paquet a un punt FedEx i la devolució continua (*FedEx: si falla la recogida, entrega en punto*).
- Nacex (etiqueta oberta): `genEtiquetaDevolucion` només retorna el codi d'expedició. El seguiment és l'**albarà** (`4307/11553031`), que s'agafa de `getEstadoExpedicion` en crear l'etiqueta. A les devolucions ja fetes, el cron de seguiment el corregeix a Odoo, a la TT/DEV i a Shopify (`reverseDeliveryShippingUpdate`, sense avisar el client).
- FedEx fora de la UE (Regne Unit): la factura comercial ETD porta la signatura i el membret del compte de FedEx (`IMAGE_1` / `IMAGE_2`, els mateixos que `delivery_fedex_rest2`).

## Canvis 1.6.7

- Nacex: després de crear l'etiqueta oberta, s'espera l'albarà (fins a 5 consultes, cada 3 s) abans de pujar el seguiment a Shopify.
- Estat de l'enviament: si Nacex encara no ha posat data ni hora, l'albarà ja no es barreja amb el text de l'estat.
- Configuració: només la veu el grup «Devoluciones Shopify: Configuración» (assignar-lo a mà als usuaris).
- Rectificativa: les línies porten el preu de la comanda. Els descomptes de Shopify en **%** van al camp *Desc.%* de cada línia i els descomptes en **€ fixos** en una línia a part «Descuento [codi]» (negativa). Si Shopify no dóna el desglossament o no quadra amb el reemborsat, la línia porta el descompte en % equivalent.
- Rectificativa: es crea amb la data de factura del dia en què s'accepta el reemborsament (abans quedava sense data fins a validar-la).

## Canvis 1.6.8 — pendent de prova a Odoo 13

- Diversos OUT entregats de la mateixa comanda: una TT/DEV amb traçabilitat
  a cada moviment original, mantenint el primer OUT al camp anterior.
- Un backorder ja entregat no bloqueja; un OUT encara obert sí.
- Quantitats basades en les realment entregades, amb conversió d'unitats;
  devolució parcial distribuïda entre moviments sense reutilitzar unitats.
- Si ja hi ha moviments de retorn, no se'n creen altres automàticament.
- El canvi no implementa canvis de talla ni substitucions. Cal mantenir
  aquests casos en revisió i no assumir que impliquen un reemborsament.
- Prova necessària a demo: 17 + 1 unitats en dos OUT, una TT/DEV i
  `origin_returned_move_id` correcte a totes les línies. No desplegat.
