"""Comprovació NOMÉS LECTURA de l'Odoo de producció (TUCTUC).

No escriu res. Llegeix les credencials de les variables d'entorn
ODOO_URL, ODOO_DB, ODOO_USER, ODOO_APIKEY.
"""
import os
import xmlrpc.client
from collections import Counter

URL, DB, USER, KEY = (os.environ[k] for k in ('ODOO_URL', 'ODOO_DB', 'ODOO_USER', 'ODOO_APIKEY'))
common = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/common')
uid = common.authenticate(DB, USER, KEY, {})
if not uid:
    raise SystemExit('Autenticació fallida')
models = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/object', allow_none=True)


def call(model, method, *args, **kw):
    return models.execute_kw(DB, uid, KEY, model, method, list(args), kw)


INPUTS = {
    '#349793': '18962389631019',
    '#349761': '18960516349995',
    '#349730': '18958173831211',
    '#349709': '18956481757227',
    '#349689': '18954213916715',
}
FAILED_JOBS = [1671583, 1670966, 1670615, 1670341, 1669979]

print('=== 1. Input files i comandes ===')
for ref, name in INPUTS.items():
    inp = call('sale.integration.input.file', 'search_read',
               [('name', '=', name)], fields=['state', 'order_id', 'si_id'])
    orders = call('sale.order', 'search_read', [('ref_remarks', '=', ref)],
                  fields=['name', 'state', 'picking_ids'])
    print(f'{ref}  input={inp or "NO TROBAT"}')
    for o in orders:
        picks = call('stock.picking', 'read', o['picking_ids'], fields=['name', 'state']) if o['picking_ids'] else []
        print(f'    SO {o["name"]} state={o["state"]} pickings={[(p["name"], p["state"]) for p in picks]}')
    if not orders:
        print('    (cap sale.order amb aquest ref_remarks)')

print('\n=== 2. Cua de jobs (pending/failed per canal) ===')
try:
    jobs = call('queue.job', 'search_read', [('state', 'in', ['pending', 'enqueued', 'started', 'failed'])],
                fields=['channel', 'state'])
    for (ch, st), n in sorted(Counter((j['channel'], j['state']) for j in jobs).items()):
        print(f'  {ch:35} {st:10} {n}')
    oldest = call('queue.job', 'search_read', [('state', '=', 'pending')],
                  fields=['date_created', 'channel'], order='date_created asc', limit=1)
    print(f'  pending més antic: {oldest}')
    orig = call('queue.job', 'read', FAILED_JOBS, fields=['state', 'name', 'exc_info'])
    for j in orig:
        last = (j.get('exc_info') or '').strip().splitlines()[-1:] or ['']
        print(f'  job {j["id"]} {j["state"]}: {last[0][:160]}')
except xmlrpc.client.Fault as e:
    print(f'  No es pot llegir queue.job (cal ser admin?): {e.faultString[:200]}')

print('\n=== 3. delivery.carrier amb nom repetit ===')
carriers = call('delivery.carrier', 'search_read', [('active', 'in', [True, False])],
                fields=['name', 'active', 'delivery_type'])
dups = {n for n, c in Counter(c['name'] for c in carriers).items() if c > 1}
for c in carriers:
    if c['name'] in dups:
        print(f'  id={c["id"]} {c["name"]!r} active={c["active"]} type={c["delivery_type"]}')
if not dups:
    print('  cap nom repetit')
