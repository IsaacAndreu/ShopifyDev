# Preparació i criteris de prova VP

## Resultat de la revisió local

- El paquet no modifica el codi font de Shopify ni del connector PinkConnect.
- Sí que reubica el menú Shopify existent sota Inventari → Devoluciones Online.
  Cal verificar aquesta navegació a la demo i després d'actualitzar Shopify:
  el seu XML original pot tornar a situar el menú al lloc anterior.
- El pilot només hereta mail.thread; no afegeix hooks de stock.picking,
  crons, transport, emails, facturació ni crides POST/PUT.
- Els registres VP tenen regla global de companyia i un grup explícit de
  configuració. El pilot no assigna el grup automàticament a cap usuari.
- Dependències: Odoo 13, odoo_pink_connect i nath_shopify_returns. Aquesta
  dependència temporal de Shopify s'ha de separar quan s'extregui la base
  comuna de transport; no s'han creat devolucions Shopify fictícies.
- Les garanties locals no substitueixen la instal·lació real a Odoo 13.

## Diagnòstic API sense instal·lar el pilot

Copiar scripts/diagnose_vp_readonly.py al servidor. Executar amb el mateix
Python/virtualenv, usuari de servei, executable Odoo i configuració que
utilitza la instal·lació existent. Plantilla (substituir les rutes i la BD):

```bash
VP_CONNECTION_ID=1 VP_ORDER_ID=26197221 \
  /ruta/venv/bin/python /ruta/odoo-bin shell \
  -c /ruta/odoo.conf -d NOM_BD --no-http \
  < /ruta/diagnose_vp_readonly.py
```

L'ID 26197221 és l'exemple de les captures; triar una comanda pròpia amb
sol·licituds de devolució per obtenir una resposta útil. El diagnòstic només
fa un GET a /return-requests i rollback al final, sense instal·lar res.
No mostra clau, contingut de missatges, noms, emails, telèfons ni adreces.
La resposta anonimitzada conserva noms de camps, tipus i alguns estats.
Si és buida, provar una comanda que tingui sol·licituds; no ampliar la
consulta automàticament a tota la història de clients.

Pendent: executar-lo al servidor. No disposem encara d'una resposta real.

## Quantitats TT/DEV

Les captures no mostren les línies de TT/DEV/0082546 o TT/DEV/0082547.
No demostren si la Lorena retorna tota la comanda o només els articles
sol·licitats. Proposta pendent de confirmar: només sol·licituds VP,
descomptant quantitats ja retornades i excloent articles no entregats.

Abans d'habilitar la creació real: comparar en lectura una d'aquestes TT/DEV
amb l'OUT original i amb les sol·licituds VP. Si tenen els mateixos articles
no sol·licitats o quantitats superiors, confirmar el criteri amb la Lorena.
No crear una TT/DEV per cada línia: agrupar el conjunt de sol·licituds que
corresponen a la mateixa devolució comercial, un cop confirmat l'esquema.

## Proves immediates del pilot 0.1

| Cas | Acció a demo | Resultat esperat |
|---|---|---|
| Instal·lació | Instal·lar només nath_vp_returns | Sense error de models, XML o dependències |
| Shopify | Obrir registres i configuració existents | Accessibles amb permisos anteriors |
| Permisos | Usuari sense grup VP | Sense accés als models VP |
| Companyies | Usuari amb una sola companyia | No llegeix ni importa registres d'una altra |
| Dades locals | Importar el JSON d'exemple dues vegades | Una sola sol·licitud |
| API | Consultar una comanda concreta | GET limitat, sense efectes externs |
| Esquema desconegut | Importar JSON incompatible | Error explícit; cap importació parcial |
| Enllaç | Comanda sense feed inequívoc | Revisió; cap associació inventada |
| Estat | Exemple PROCESSING/COMPLETE | Previsualització indica que no s'ha d'acceptar |

## Proves del circuit complet (encara no implementat)

No executar aquests casos amb la versió 0.1: són els criteris per a les
següents entregues. Els assaigs amb escriptures requereixen compte staging
o una comanda de prova acordada amb VP i transportistes configurats per a
la prova. Una còpia d'Odoo pot conservar credencials i crons de producció.

| Cas | Resultat esperat |
|---|---|
| ES correcte | Una TT/DEV; Nacex 44; missatge ES; acceptació individual i relectura PROCESSING |
| ES tipus canviats | Provar una primera línia sense Home Pick Up; si es completa, aturar la devolució i registrar incidència |
| FR correcte | TT/DEV; FedEx a domicili confirmat; PREVENIR A L'AVANCE; dates reals; PDF adjunt; PROCESSING |
| FR sense recollida | Revisió, sense convertir automàticament en entrega a punt |
| Acceptació parcial | Reprendre només línies encara pendents |
| Timeout després de POST | Reconciliar abans de repetir missatge o transport; revisió si no es pot saber el resultat |
| Dues execucions simultànies | Un sol transport, TT/DEV i missatge |
| Quantitat parcial/retorn previ | No superar l'entregat disponible per retornar |
| Recepció amb diferències | Revisió abans de completar o reemborsar |
| Comptabilitat | No duplicar la rectificativa que pugui generar el connector existent |
| Reemborsament | Mai cridar /return i /refund per als mateixos articles |

## Missatges preparats

ES, assumpte: Devolución de paquete Tuc Tuc en punto de recogida cercano

Hola, acabamos de generar un código que le permite devolver el paquete a un
punto de recogida cercano. Por favor, revise su bandeja de entrada y correo
no deseado para obtener información de la agencia NACEX. En cuanto lo
recibamos, le devolveremos el dinero. Muchas gracias.

FR, assumpte: Instructions pour votre retour — Commande {referencia}

Chère cliente, Cher client,

Pour procéder au retour, veuillez coller l'étiquette FedEx jointe sur votre
colis fermé, puis le remettre au transporteur lors de son passage prévu
le {date_collecte}, entre {heure_debut} et {heure_fin}.

Si vous avez la moindre question ou si le transporteur ne se présente pas,
n'hésitez pas à nous en informer.

Bien cordialement,
L'équipe du Service Client

No enviar el missatge FR fins a tenir PDF i recollida confirmada. No fer
servir dates d'exemple ni la referència «vendredi dernier» de les captures.
