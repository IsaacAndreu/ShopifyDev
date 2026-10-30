# Facturació de canvis i sortides manuals — pilot per a demo

Mòdul independent `nath_exchange_billing`, Odoo 13, versió 13.0.0.1.0.
Depèn de `nath_shopify_returns` existent. No requereix VP/PinkConnect.
No instal·lat ni executat a Odoo real; pendent de prova a demo.

## Abast de la primera entrega

Facturació controlada dels moviments fets que se seleccionin explícitament:
una factura per cada OUT manual/de substitució i una rectificativa per cada
TT/DEV, si encara no tenen cobertura. Els documents es creen en esborrany.
No modifica albarans, línies de venda, productes històrics ni estats de Shopify.
No fa peticions HTTP, reemborsaments, pagaments, validació ni conciliació.

La persona revisora introdueix el **preu net per unitat del moviment**, el
compte i els impostos. Si el descompte original figura en una línia negativa
separada, també s'ha d'incloure al preu net, sense copiar el preu brut.
No es dedueix una equivalència de preus entre talles: s'ha de revisar.
Les despeses d'enviament no s'afegeixen automàticament.

## Instal·lació a demo

1. Copiar la carpeta a custom_addons, reiniciar Odoo, actualitzar la llista
   d'aplicacions i instal·lar només aquest mòdul.
2. Assignar a la persona revisora el grup «Facturación de cambios: revisión».
   El grup implica accés de facturació i inventari; no s'assigna automàticament.
3. Obrir Inventari → Devolucions Shopify → Canvis i sortides manuals.
   Si el mòdul VP reorganitza els menús: Inventari → Devolucions → Shopify
   → Canvis i sortides manuals.
4. Crear un expedient, indicar client de facturació, companyia, moneda i
   diari. Si hi ha comanda, seleccionar-la. Per al retorn, seleccionar
   també la factura original validada.
5. Seleccionar els albarans exactes. Excloure l'OUT original ja facturat.
6. «Preparar movimientos y proteger pedido»: llegeix quantitats fetes,
   crea la cobertura interna i bloqueja la facturació ordinària del pedido.
   Encara no crea documents comptables.
7. Per cada línia: vincular la línia comptable existent si ja s'ha facturat;
   si no, introduir preu net, compte i impostos. Revisar també factures
   manuals no vinculades: els remarks per si sols no demostren cobertura.
8. «Previsualizar»: revisar proposta i inventari de documents del client.
   Marcar la confirmació de revisió i «Crear borradores pendientes».
9. Revisar els esborranys a «Ver documentos». Validació i conciliació
   queden per a la revisió comptable habitual, fora d'aquest pilot.

La capçalera queda fixada després de preparar per no canviar la identitat
de la cobertura. Revisar-la abans de preparar. No s'eliminen expedients ni
cobertures finalitzades per evitar regeneracions accidentals.

## Prova concreta #349292

- Comanda: WT#349292. Factura original: FW/2026/6024.
- Incloure TT/DEV/0082337 (8 originals retornats), TT/OUT/0821212 (6 talles
  de substitució) i TT/OUT/0821706 (2 talles de substitució).
- Excloure TT/OUT/0816542, que ja correspon a la factura original pagada.
- Resultat si no s'han facturat encara manualment: una rectificativa de
  les 8 peces originals, una factura de les 6 substitucions i una de les 2.
- Revisar els imports nets descomptats de la factura original i els preus
  acordats de les substitucions. Si han de compensar-se íntegrament,
  comprovar el total amb impostos; el programa no força un saldo zero.
- Si ja s'han facturat els dos OUT manualment, seleccionar les línies
  existents. No crear unes altres. Cobertura agrupada o parcial incompatible
  amb un moviment complet: aturar i revisar fora del pilot.
- Repetir el botó: han de continuar existint els mateixos documents.
- El pedido tècnic i Shopify conserven el seu estat; no reactivar-los.

Les peces poden constar en moviments separats d'una unitat: «8/6/2» és
el total de cada albarà, no una obligació de tenir una sola línia comptable.
Es manté una línia de cobertura per moviment per conservar la traçabilitat.

## Proteccions i límits

- Clau única per moviment, per línia comptable utilitzada i per línia
  comptable generada. Els clics repetits no creen documents nous.
- Bloqueig transaccional del pedido i l'expedient. Creació de documents i
  registre de cobertura en una sola transacció, sense commits intermedis.
- Dades canviades després de la previsualització obliguen a tornar a revisar.
- Bloqueig de `_create_invoices` ordinari per a comandes protegides, i de
  creació de noves línies comptables enllaçades a les seves línies de venda.
- Protecció a `_accept_one` i `_shopify_refund` del mòdul de devolucions
  Shopify quan la comanda està protegida. No controla altres aplicacions,
  el portal Shopify ni un reemborsament fet manualment fora d'aquest mòdul.
- Factures creades manualment sense cap enllaç a venda/stock no es poden
  atribuir automàticament amb certesa. El pilot mostra documents del client
  i exigeix confirmació humana i selecció de cobertura; no garanteix detectar
  qualsevol factura feta fora del circuit.
- Per a sortides sense comanda, la cobertura evita duplicats dins aquest
  mòdul; no hi ha comanda sobre la qual bloquejar altres automatismes.
- El pilot no recableja les línies de les talles antigues ni recalcula la
  facturació pendent de la comanda. Pot seguir indicant «to invoice»:
  queda protegida i els documents es consulten al nou expedient.
- Els esborranys nous no duen `sale_line_ids` incorrectes de la talla antiga;
  s'enllacen explícitament a expedient i moviment mitjançant cobertura.
- Cancel·lar un document no autoritza regenerar-lo automàticament. Revisar
  el cas; la cobertura es conserva també per a documents cancel·lats.
- No admet facturació parcial d'un moviment, ni una línia comptable agrupada
  que cobreixi diversos moviments. No duplica ni divideix a cegues.

## Matriu de prova demo

| Cas | Resultat |
|---|---|
| #349292 sense factures noves | 3 documents en esborrany, productes reals 8/6/2 |
| Dos OUT ja facturats | Vincular cobertura existent; no repetir factures |
| Segon clic / segon expedient | Documents existents o bloqueig de moviment duplicat |
| Preu/impost canviat després de preview | Exigeix nova previsualització |
| Quantitat/producte de factura existent diferent | Bloqueig, sense crear document |
| Stock pendent, companyia o client diferent | Bloqueig |
| Facturar des de la comanda protegida | Bloqueig amb instrucció d'obrir expedient |
| Acceptar i reemborsar a devolucions Shopify | Bloqueig per a comanda protegida |
| Sortida manual sense sale_line_id | Preu/compte/impost explícits; una factura de cobertura |
| Document cancel·lat | No es recrea automàticament |

## Validació realitzada

Proves locals amb dobles d'Odoo: idempotència, revisió caducada, cobertura
existent exacta, guardes de reemborsament, absència de crides de xarxa,
validació/conciliació i sintaxi Python 3.7/XML. Aquestes proves no substitueixen
la instal·lació Odoo 13, els càlculs fiscals ni els tests amb els addons reals.

S'han executat 9 proves del nou mòdul, 4 de múltiples OUT Shopify i 6 del
pilot VP, totes correctes. La prova 8/6/2 comprova l'agrupació en 3 documents
amb dobles, no l'execució comptable real a la base de dades de demo.
