# Resum del treball — últims 3 dies

**Període:** 26–30 d’octubre de 2026  
**Entorn principal:** Odoo 13, base `TUCTUC_PRODUCTION`, servidor `tuctuc-erp-prod-eu-w1b`  
**Mòduls implicats:** Shopify Returns, PinkConnect/VP, FedEx i facturació de canvis.

> Aquest document resumeix el que s’ha investigat, preparat i provat. No inclou cap API key ni cap credencial.

## 1. Devolucions Shopify

### Estat i versió

- Es va revisar el mòdul `nath_shopify_returns` i el seu flux de devolucions.
- Es van preparar les versions intermèdies `1.6.6` i `1.6.7`.
- Es va empaquetar la versió final Odoo `13.0.1.6.8`:
  - Fitxer local: `nath_shopify_returns_13.0.1.6.8.tar.gz`
  - SHA-256: `685150AD0AA34D07F91F99A36256C2F0446E2AAB757965FE30F0029D11450009`
- A producció, el mòdul es va comprovar instal·lat amb la versió `13.0.1.6.8`.

### Millores revisades/preparades

- Flux de devolucions Shopify amb estats, seguiment i tasques automàtiques.
- Control de devolucions i reemborsaments per evitar duplicats.
- Millora per a canvis i sortides manuals:
  - facturar cada sortida real;
  - evitar duplicar factures;
  - no generar reemborsaments addicionals a Shopify quan la comanda ja està cancel·lada o compensada;
  - permetre treballar amb comandes servides en més d’un `OUT`.
- Es van preparar comprovacions per a comandes amb múltiples sortides (`check_shopify_multi_out.py`).
- Es va revisar el cas d’intercanvi `#349292`, amb devolució i dues sortides posteriors de canvi.

### Botó “ACEPTAR Y REEMBOLSAR”

- El botó és d’ús individual des del formulari.
- Només apareix quan la devolució està en l’estat adequat (`received`).
- El flux fa, en aquest ordre:
  1. intenta el reemborsament a Shopify;
  2. registra el resultat i l’identificador del reemborsament;
  3. crea la rectificativa d’Odoo;
  4. publica la rectificativa segons la configuració.
- Si la rectificativa ja s’ha fet manualment, s’ha d’utilitzar l’opció de tancament manual i no tornar a prémer el botó de reemborsament.
- Es va detectar que la llista ja té l’acció “Procesar devoluciones”, però no equival necessàriament a acceptar i reemborsar.

### Acció de servidor massiva

Es va definir el codi per crear una acció massiva sense actualitzar el mòdul:

**Nom proposat:** `Aceptar y reembolsar devoluciones seleccionadas`  
**Model:** `shopify.return.log` / Devolució Shopify  
**Tipus:** Executar codi Python  
**Vista:** Llista  
**Vinculació:** Acció sobre el model

```python
if not records:
    raise UserError('Selecciona almenys una devolució.')

no_recibidas = records.filtered(
    lambda record: record.state != 'received'
)

if no_recibidas:
    raise UserError(
        'Només es poden reemborsar devolucions en estat Recibida.'
    )

records.action_accept()
```

**Important:** segons l’últim estat conegut, aquesta acció encara estava pendent de crear/verificar a Odoo. No s’ha d’executar sobre dades reals sense revisar abans la selecció i el resultat.

## 2. PinkConnect / Veepee (VP)

### Investigació de l’API

Es va analitzar la documentació de Brandsplace/PinkConnect:

- `GET /return-requests`
- `PUT /return-requests/{returnRequestId}/{status}`
- `POST /orders/{orderId}/return`
- `POST /orders/{orderId}/refund`
- notificacions de comanda (`/notifications`)

Flux identificat:

```text
PENDING → PROCESSING → COMPLETED
      ↘ REJECTED

COMPLETED → POST /orders/{orderId}/return → reemborsament automàtic segons el motiu
```

També es va confirmar que el JSON de les devolucions conté camps com `orderId`, `orderLineId`, `gtin`, `sku`, `quantity`, `status` i `type` (`HOMEPICKUP` en alguns casos).

### Diagnòstics de només lectura

Es van preparar i executar proves sense modificar Odoo ni PinkConnect:

- `diagnose_vp_readonly.py`
  - consulta de sol·licituds VP;
  - verificació de connexió i esquema de resposta;
  - una comanda de prova retornava HTTP 200.
- `diagnose_vp_stock_readonly.py`
  - comparació entre `OUT`, devolucions i `TT/DEV`;
  - revisió de quantitats entregades, rebudes i obertes;
  - detecció de comandes servides en més d’un `OUT`.

### Mòdul pilot preparat

- Mòdul: `nath_vp_returns`
- Versió local final: `13.0.0.1.3`
- Fitxer: `nath_vp_returns_13.0.0.1.3.tar.gz`
- SHA-256: `20333E88DA3E0427DB8C110629C09F9A14E333427A191649E8A04D3220C148B2`
- Tests locals: `6/6` correctes amb `check_vp_pilot.py`.
- Menú proposat:
  - `Devolucions Online`
  - `Shopify`
  - `VP / PinkConnect`
  - `Solicitudes`
  - `Configuración`

### Limitacions actuals del pilot VP

El pilot és de consulta/previsualització. Encara no implementa el circuit complet:

- no crea `TT/DEV` automàticament;
- no actualitza estats amb `PUT`;
- no crea recollides a domicili;
- no envia missatges;
- no executa reemborsaments;
- no resol encara tota la lògica de comandes amb diversos `OUT`.

Per tant, el mòdul VP no s’ha de considerar acabat per a producció.

## 3. FedEx i seguiments duplicats

### Cas investigat

Es va investigar el seguiment `879337633282` associat a `TT/OUT/0825526`.

Resultat de la consulta de només lectura:

- a Odoo constava **un únic albarà**;
- hi havia **un únic paquet**;
- hi havia **una única etiqueta** amb aquest tracking;
- Odoo tenia una única referència FedEx i una resposta FedEx guardada;
- el duplicat es veia a la web de FedEx, però no es va trobar un segon albarà creat a Odoo.

També es van revisar tres casos més:

- `TT/OUT/0824695`
- `TT/OUT/0825952`
- `TT/OUT/0826365`

En aquests casos Odoo mostrava més d’un esdeveniment/etiqueta FedEx associat al mateix albarà, fet compatible amb reintents o generacions repetides de document.

### Automatismes revisats

Es va executar `diagnose_fedex_automation_readonly.py` per identificar accions i cron que podien intervenir en la validació o enviament:

- cron d’“OUT online sin Almacen Automatizado”;
- accions sobre `stock.picking`, `stock.move` i `sale.order`;
- accions de validació massiva, replicació de tracking i agrupacions.

No es va executar cap acció ni es va fer cap crida FedEx durant el diagnòstic.

### Guard d’idempotència

Es va preparar una millora mínima del mòdul `delivery_fedex_rest2`:

- versió proposada: `13.0.1.1.0`;
- reutilitzar el tracking existent si l’enviament ja està creat;
- evitar un segon `POST` a FedEx;
- conservar la integració, el transport i els mètodes d’enviament existents;
- no alterar credencials ni configuració API.

La prova `diagnose_fedex_guard_dryrun.py` va donar, per als tres albarans, la decisió:

```text
REUTILITZAR tracking actual; 0 POST a FedEx
```

### Desplegament i incidència de l’arxiu

- Es va preparar `fedex_preflight_no_restart.sh`, que valida sense escriure ni reiniciar.
- Es va preparar `deploy_fedex_restart.sh`, que fa còpia de seguretat, copia el mòdul i només reinicia amb confirmació.
- L’arxiu inicial `delivery_fedex_rest2_13.0.1.1.0.tar.gz` va arribar buit (0 bytes), per això va fallar amb `gzip: unexpected end of file`.
- Es va localitzar l’arxiu correcte:
  - `delivery_fedex_rest2_13.0.1.1.0.tar_(1).gz`
  - aproximadament 7,1 KB
  - `gzip -t` correcte.
- El servei correcte identificat és `tuctuc-erp.service`.
- El reinici correcte és sempre:

```bash
sudo systemctl restart tuctuc-erp.service
```

No s’ha d’utilitzar el patró stop/start separat.

## 4. Facturació i canvis

### Problema analitzat

Es va revisar el cas d’una comanda amb:

- retorn de les peces originals;
- canvi enviat en dues sortides posteriors;
- comanda de Shopify cancel·lada per evitar reemborsaments;
- risc que el botó de facturació generés una rectificativa de tota la comanda.

### Solució funcional definida

- Facturar les sortides reals una per una quan pertoqui.
- No crear una rectificativa global si la mercaderia de canvi ja ha sortit.
- Conciliar la rectificativa amb les sortides de canvi corresponents.
- Marcar les sortides manuals perquè també entrin al circuit de facturació.
- Evitar qualsevol reemborsament duplicat a Shopify.

### Mòdul preparat

- `nath_exchange_billing`
- Versió local: `13.0.0.1.0`
- Inclou model, vistes, permisos i comprovacions auxiliars.
- Scripts de suport:
  - `diagnose_shopify_exchange_readonly.py`
  - `check_exchange_billing.py`
  - `conciliar_shopify_auto.py`

Cal provar-lo primer en demo amb comandes que tinguin dos `OUT` i sortides manuals abans d’aplicar-lo a producció.

## 5. Scripts i materials creats

Fitxers principals del projecte:

- `deploy_nath_shopify_returns_restart.sh`
- `fedex_preflight_no_restart.sh`
- `stage_fedex_no_restart.sh`
- `deploy_fedex_restart.sh`
- `diagnose_fedex_duplicate_readonly.py`
- `diagnose_fedex_automation_readonly.py`
- `diagnose_fedex_guard_dryrun.py`
- `diagnose_fedex_history_readonly.py`
- `diagnose_vp_readonly.py`
- `diagnose_vp_stock_readonly.py`
- `diagnose_shopify_exchange_readonly.py`
- `check_shopify_multi_out.py`
- `check_exchange_billing.py`
- `check_vp_pilot.py`
- `VP_RETURNS_SPEC.md`

Característica comuna dels diagnòstics: s’han dissenyat per fer només lectura, sense modificar Odoo i sense crides externes quan així s’indica.

## 6. Comandes habituals del servidor

### Shell Odoo de només lectura

```bash
sudo -u ubuntu /opt/tuctuc-erp/env/bin/python \\
  /opt/tuctuc-erp/odoo13/odoo-bin shell \\
  -c /opt/tuctuc-erp/tuctuc-erp.conf \\
  -d TUCTUC_PRODUCTION --no-http \\
  < /home/it_nath_group/diagnostic.py
```

### Preflight FedEx sense reinici

```bash
bash /home/it_nath_group/fedex_preflight_no_restart.sh \\
  /home/it_nath_group/delivery_fedex_rest2_13.0.1.1.0.tar.gz \\
  /opt/tuctuc-erp/nath/custom_addons/delivery_fedex_rest2
```

### Desplegament FedEx amb reinici només si es confirma

```bash
sudo bash /home/it_nath_group/deploy_fedex_restart.sh \\
  /home/it_nath_group/delivery_fedex_rest2_13.0.1.1.0.tar.gz \\
  /opt/tuctuc-erp/nath/custom_addons/delivery_fedex_rest2 \\
  tuctuc-erp.service \\
  TUCTUC_PRODUCTION
```

### Comprovar servei

```bash
systemctl status tuctuc-erp.service
systemctl is-active tuctuc-erp.service
```

## 7. Estat final i pendents

### Fet o verificat

- Shopify Returns `13.0.1.6.8` preparat i comprovat instal·lat a producció.
- Flux de reemborsament i rectificatives revisat.
- Diagnòstics VP i FedEx executats en mode de només lectura.
- Guard FedEx i scripts de desplegament preparats.
- Pilot VP empaquetat amb menú `Devolucions Online`.
- Problema de comandes amb diversos `OUT` documentat.
- Millora de facturació de canvis i sortides manuals definida.

### Pendent

1. Crear i verificar l’acció de servidor massiva de Shopify Returns.
2. Provar `nath_exchange_billing` en demo amb un cas real de canvi en dues sortides.
3. Fer prova funcional del guard FedEx en demo i revisar logs després del reinici.
4. Completar el mòdul VP: creació de `TT/DEV`, estats, missatges, home pickup i reemborsaments.
5. Confirmar si VP requereix agrupar tots els `OUT` d’una mateixa comanda abans de generar la devolució.
6. No pujar VP a producció fins que el pilot tingui proves completes i validació funcional.

## 8. Recomanació operativa

Abans de qualsevol canvi en producció:

1. executar el diagnòstic de només lectura;
2. fer còpia del mòdul actual;
3. executar el preflight;
4. actualitzar el mòdul des de la interfície Odoo si cal;
5. reiniciar només amb `systemctl restart` i confirmació explícita;
6. comprovar servei, logs i un cas de prova controlat.

