# Devolucions VP / PinkConnect

Proposta funcional basada en les captures facilitades el 28/10/2026.
Pendent de confirmar la interfície de PinkConnect (API, connector o web).
Aquest document no executa operacions en cap plataforma.

## Connector existent verificat a Odoo

Revisió web de només lectura el 28/10/2026:

- Aplicació instal·lada: **Pink Connect Odoo**, autor **Brain Station 23 LTD**
  (registre `ir.module.module`, ID 768).
- Model de configuració: `pink.connect.channel.configuration`.
- Configuracions validades: **Pink VP Live** (ID 1, PRIME COLLECTIONS SL)
  i **Pink Connect Moda Intima** (MODA INTIMA 1964 SL).
- La configuració Pink VP Live mostra `Import Order Status: pending` i
  pestanyes Operation, Credentials i Sale Order Defaults.
- Menús observats: Feeds → Order; Synchronization → Logs; Mappings.
- Aquesta revisió confirma l'existència del connector, però no confirma
  suport per devolucions, missatges, adjunts o recollides. Cal revisar el
  seu codi font i els endpoints que utilitza abans d'implementar el nou flux.
- No s'han modificat configuracions ni executat sincronitzacions.

## Abast

Nou mòdul Odoo `nath_vp_returns`, separat del flux Shopify. Reutilitzar la
lògica de transportistes i de creació de TT/DEV mitjançant una capa comuna,
després de revisar-ne les dependències. No crear registres Shopify ficticis.

Origen: sol·licituds de devolució pendents de PinkConnect. Identificadors
diferenciats: ID de comanda PinkConnect, referència comercial / remarks,
ID de sol·licitud de cada línia i SKU. El país de l'adreça determina el flux;
el camp Type de PinkConnect està invertit respecte a l'operativa real.

## Flux Espanya

1. Importar totes les línies pendents de la comanda, amb els seus IDs.
2. Validar comanda Odoo, companyia, productes, quantitats i entrega original.
   Revisió manual si hi ha ambigüitat, entrega parcial o dades incompletes.
3. Crear o recuperar la TT/DEV. Confirmar si ha d'incloure tota la comanda
   com el flux web o exclusivament les unitats sol·licitades a VP.
4. Generar la devolució Nacex servei 44 a punt, amb referència TT/DEV i
   observacions TT/DEV + remarks. Nom i email del client procedents de VP.
5. Enviar el missatge de VP amb l'assumpte i el cos indicats més avall.
6. Crear el registre de «Recogida a domicilio» a PinkConnect, tot i que
   l'entrega real és a punt: Tracking = `Entrega a punto`, Agencia = `NACEX`.
   Verificar que el registre existeix abans de continuar.
7. Acceptar les línies pendents d'una en una i verificar que cadascuna
   queda en «En Proceso». No executar «Completar Solicitud».

Si el pas 6 falla o no es pot verificar, no acceptar cap línia.
Si una línia apareix completada inesperadament, aturar la comanda i derivar-la
a revisió manual: les captures indiquen que aquest estat no es pot revertir.

## API documentada facilitada per l'usuari

Base producció: `https://api.pink-connect.com/v4`.
Base preproducció: `https://api-pinkstaging.pink-connect.com/v4`.
Autenticació: Bearer, reutilitzant la configuració Odoo sense copiar claus
als fitxers del nou mòdul.

- `GET /return-requests`: llista de sol·licituds; filtres documentats
  `status`, `Offset`, `limit`, `orderId`. Falta confirmar a Swagger el
  format de resposta i la capitalització exacta del paràmetre de paginació.
- `PUT /return-requests/{returnRequestId}/PROCESSING`: acceptació individual.
- `PUT /return-requests/{returnRequestId}/REJECTED`: rebuig des de pendent.
- La documentació descriu PROCESSING → COMPLETE, però el seu exemple
  repeteix `/PROCESSING`. Confirmar la ruta final a Swagger/preproducció
  abans d'implementar la compleció.
- Completar una sol·licitud no reemborsa diners. El text remet després a
  `POST /orders/{orderId}/return`, que calcula i executa el reemborsament
  per a comandes workflow V2. No usar aquest POST per acceptar sol·licituds.
- `POST /orders/{orderId}/refund`: reemborsament d'import explícit;
  no combinar amb `/return` per als mateixos articles.
- Cancel·lació de sol·licituds: el text indica que encara no està desenvolupada.

Missatges, segons la documentació facilitada:

- `GET /notifications`: filtres `orderId`, `subject`, `message`,
  `updateDateLTE`, `updateDateGTE`. Prioritzar filtre per comanda.
- `GET /notifications/{id}`: consulta d'un missatge.
- `POST /orders/{orderId}/notifications`: crear missatge amb camps
  multipart `subject`, `message` i `attachedFile` per al PDF.
- `POST /notifications/{id}`: respondre amb els mateixos camps multipart.
- Guardar l'identificador retornat en crear el missatge. Si hi ha timeout,
  reconciliar amb els missatges de la comanda abans de tornar-lo a enviar.
- En Python requests, deixar que la llibreria generi el Content-Type amb
  el boundary multipart quan s'utilitzi `files`.
- El text d'exemple indica `updateDateGTE > updateDateLTE`, però aquesta
  desigualtat és inconsistent amb els noms dels límits; verificar-la a
  Swagger abans d'usar filtres temporals.

Pendent: documentació Home Pick Ups i esquemes de resposta.
El comportament de l'acceptació ES per API s'ha de validar a
preproducció: no donar per fet que evita la incidència observada al portal.
Les instruccions de crear sol·licituds fictícies de la documentació són
referència per a proves, no autorització per crear-les en producció.

## Flux França

1. Importar i validar com a Espanya; crear o recuperar la TT/DEV.
2. Crear enviament FedEx de retorn/importació amb el client com a origen
   i el magatzem configurat com a destí. Recollida a domicili obligatòria.
   Confirmar dades equivalents a la plantilla manual «Reco a domicilio FR».
3. Programar recollida amb instrucció `PREVENIR A L'AVANCE`, i guardar
   data, franja horària, seguiment, confirmació de recollida i etiqueta PDF.
   La data i la franja de la captura són exemples, no valors fixos.
4. Enviar missatge en francès a VP amb l'etiqueta adjunta.
5. Acceptar les línies pendents d'una en una i verificar «En Proceso».
   El Type mostrat per VP és «El cliente envía».

El registre «Recogida a domicilio» de VP és opcional per a França segons
les captures. Si es crea, portar el seguiment real i l'agència FEDEX.
Si falla la recollida FedEx, aturar per revisió: no aplicar automàticament
l'alternativa d'entrega a punt del mòdul Shopify.

## Missatges

### Espanya

Assumpte: Devolución de paquete Tuc Tuc en punto de recogida cercano

Hola, acabamos de generar un código que le permite devolver el paquete a un
punto de recogida cercano. Por favor, revise su bandeja de entrada y correo
no deseado para obtener información de la agencia NACEX. En cuanto lo
recibamos, le devolveremos el dinero. Muchas gracias.

### França

Assumpte: Instructions pour votre retour — Commande {referencia}

Chère cliente, Cher client,

Pour procéder au retour, veuillez coller l'étiquette FedEx jointe sur votre
colis fermé, puis le remettre au transporteur lors de son passage prévu
le {date_collecte}, entre {heure_debut} et {heure_fin}.

Si vous avez la moindre question ou si le transporteur ne se présente pas,
n'hésitez pas à nous en informer.

Nous restons à votre entière disposition.

Bien cordialement,
L'équipe du Service Client

La referència, data i franja es generen amb les dades reals. No reutilitzar
la menció «vendredi dernier» de l'exemple.

## Seguiment i recuperació

- Clau única per connexió i ID de línia VP; agrupar les línies per devolució
  comercial segons els identificadors que ofereixi PinkConnect.
- Guardar TT/DEV, referències del transportista, etiqueta, ID de missatge,
  ID del registre de recollida i resultat de cada acceptació individual.
- En reintentar, recuperar els passos confirmats. Davant d'un timeout amb
  resultat desconegut, consultar la plataforma abans de repetir la creació
  d'una recollida, un enviament o un missatge. Si no hi ha manera de consultar,
  derivar a revisió manual.
- Una sola execució concurrent per devolució; errors i accions auditats.
- Països diferents d'ES i FR, tipus inesperats i estats inconsistents:
  revisió manual.
- Pilot manual amb previsualització; automatització només després de
  validar una devolució de cada país.

## Recepció i rectificatives

Segons les captures, acceptar les línies de VP ja genera rectificatives
en esborrany de manera automàtica. Cal identificar quin connector ho fa
abans d'afegir cap creació comptable. El nou mòdul no ha de duplicar-les.
El magatzem valida la recepció. La gestió del reemborsament VP queda pendent
de definir; no s'ha d'assimilar al reemborsament Shopify.

## Informació necessària per implementar la connexió

1. API o connector de PinkConnect: autenticació, lectura paginada de
   sol·licituds i dades de comanda, missatges amb adjunts, creació/consulta de
   recollides i acceptació/consulta de cada línia.
2. Identitat del connector Odoo que importa VP i genera les rectificatives.
3. Regla de quantitats de la TT/DEV i criteri d'agrupació de sol·licituds.
4. Configuració de transportistes, destí, horaris i calendari de recollida.

## Validacions d'acceptació

- ES: cap acceptació si no s'ha confirmat el registre NACEX / Entrega a punto.
- FR: cap missatge sense etiqueta ni acceptació sense recollida confirmada.
- Acceptació parcial: reprendre només les línies pendents.
- Timeout de creació: evitar duplicats mitjançant reconciliació o revisió.
- Reexecució completa: una TT/DEV, un enviament, una recollida i un missatge.
- No generar una segona rectificativa ni marcar completada una sol·licitud.
