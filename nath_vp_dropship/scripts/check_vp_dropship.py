# -*- coding: utf-8 -*-
"""Prova local (sense Odoo) de la lògica de nath_vp_dropship amb el privalia_demo_kit.

    python -I scripts/check_vp_dropship.py <carpeta_del_kit>

Compara el que calcularia el mòdul amb els fitxers que el kit dona com a resultat esperat:
  07/08 import_sale_order (preu i tarifa per línia), 09 update (transportista i remarks),
  12 expected_ID_import (Dropshipping Veepee Product ID). I prova que el format de l'API
  (deliveryOrders) dona el mateix que l'Excel.
"""
import glob
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('vp_parse', os.path.join(HERE, '..', 'models', 'vp_parse.py'))
vp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vp)

KIT = sys.argv[1] if len(sys.argv) > 1 else '.'
fails = []


def f(pattern):
    return glob.glob(os.path.join(KIT, pattern))[0]


def check(name, ok, detail=''):
    print('%s %s %s' % ('OK  ' if ok else 'FAIL', name, detail))
    if not ok:
        fails.append(name)


def sheet(path, idx=0):
    header, values = vp.read_xlsx(path, idx)
    return [dict(zip(header, [vp._txt(v) for v in row])) for row in values]


# --- dades mestres del kit (el que a Odoo serien productes, mapeig i preus) ---
products = {r['Barcode']: i for i, r in enumerate(sheet(f('01_products_to_create.xlsx')), 1)}
mapping = {}
for r in sheet(f('05_MAPPING_CARRIER.xlsx')):
    mapping[r['LI_Pays']] = (r['odoo_carrier'], vp.tarifa_from_text(r['tarifa']))
price_header, price_rows = vp.read_xlsx(f('06_price_list_by_country.xlsx'))
cols = {vp.tarifa_from_text(h): i for i, h in enumerate(price_header) if vp.tarifa_from_text(h)}
prices = {vp._txt(r[0]): {t: r[i] for t, i in cols.items()} for r in price_rows}
check('tarifes detectades al fitxer de preus', sorted(cols) == ['es', 'fr_benelux', 'it'], str(cols))


def find_product(eans):
    for e in eans or []:
        if e in products:
            return products[e]
    return None


def find_carrier(key):
    return mapping.get(key, (None, None))


def find_price(ean, tarifa):
    p = prices.get(ean)
    return p.get(tarifa) if p else None


def run(batch_file, import_file, update_sheet):
    print('\n=== %s ===' % os.path.basename(batch_file))
    t0 = time.time()
    rows = vp.rows_from_xlsx(batch_file)
    plan = vp.plan_orders(rows, find_product, find_carrier, find_price)
    print('     %s files, %s comandes, %.1f s' % (len(rows), len(plan), time.time() - t0))
    check('cap comanda amb errors', not [o for o in plan if o['errors']],
          str([(o['name'], o['errors']) for o in plan if o['errors']][:3]))

    # 07/08: una línia per comanda+EAN amb preu i tarifa
    expected = sheet(import_file, 0)
    exp_lines = {}
    for r in expected:
        key = (r['ORDER'], r['PRODUCT'])
        e = exp_lines.setdefault(key, {'qty': 0.0, 'price': float(r['PRICE']), 'pricelist': r['PRICELIST']})
        e['qty'] += float(r['QUANTITY'])
    got_lines = {}
    for o in plan:
        for l in o['lines']:
            got_lines[(o['name'], l['ean'])] = {'qty': l['qty'], 'price': l['price'], 'tarifa': o['tarifa']}
    check('mateixes comandes que el fitxer d\'importació',
          {k[0] for k in got_lines} == {k[0] for k in exp_lines},
          '%s vs %s' % (len({k[0] for k in got_lines}), len({k[0] for k in exp_lines})))
    check('mateixes línies (comanda+EAN)', set(got_lines) == set(exp_lines),
          '%s vs %s' % (len(got_lines), len(exp_lines)))
    bad_qty = [k for k in exp_lines if k in got_lines and abs(got_lines[k]['qty'] - exp_lines[k]['qty']) > 1e-6]
    check('unitats per línia', not bad_qty, str(bad_qty[:3]))
    bad_price = [k for k in exp_lines if k in got_lines
                 and abs((got_lines[k]['price'] or 0) - exp_lines[k]['price']) > 0.0001]
    check('preu per línia', not bad_price,
          str([(k, got_lines[k]['price'], exp_lines[k]['price']) for k in bad_price[:3]]))
    bad_tarifa = [k for k in exp_lines if k in got_lines
                  and got_lines[k]['tarifa'] != vp.tarifa_from_text(exp_lines[k]['pricelist'])]
    check('tarifa per comanda', not bad_tarifa, str(bad_tarifa[:3]))
    total = sum(l['qty'] for o in plan for l in o['lines'])
    print('     unitats totals: %s' % total)

    # 09: transportista i remarks
    upd = {r['Referencia del pedido']: r for r in sheet(f('09_order_update_template.xlsx'), update_sheet)}
    bad_car = [o['name'] for o in plan if o['name'] in upd and o['carrier_id'] != upd[o['name']]['Método entrega']]
    check('transportista per comanda', not bad_car and len(upd) == len(plan),
          '%s diferents, %s/%s comandes' % (len(bad_car), len(upd), len(plan)))
    bad_rem = [o['name'] for o in plan if o['name'] in upd and o['intitule'] != upd[o['name']]['Remarks']]
    check('remarks (LI_Intitule)', not bad_rem, str(bad_rem[:3]))
    return rows, plan


rows, plan = run(f('03_batch_*.xlsx'), f('07_import_sale_order_*.xlsx'), 0)

# 12: Dropshipping Veepee Product ID esperat per al batch petit
exp_ids = {}
by_ext = {r['External ID']: r['Barcode'] for r in sheet(f('01_products_to_create.xlsx'))}
for r in sheet(f('12_expected_ID_import_small_batch.xlsx')):
    exp_ids[by_ext[r['ID']]] = r['Dropshipping Veepee Product ID']
current = {r['Código de barras'] if 'Código de barras' in r else list(r.values())[2]:
           r['Dropshipping Veepee Product ID'] for r in sheet(f('02_variants_export.xlsx'))}
got_ids = {}
for o in plan:
    for l in o['lines']:
        if l['veepee_id'] and current.get(l['ean']) != l['veepee_id']:
            got_ids[l['ean']] = l['veepee_id']
check('Veepee Product ID a actualitzar = fitxer 12', got_ids == exp_ids,
      '%s calculats vs %s esperats' % (len(got_ids), len(exp_ids)))

# API: es reconstrueix la resposta deliveryOrders a partir de l'Excel i ha de donar el mateix
orders = {}
for r in rows:
    parts = r['LI_Intitule'].split('#')
    country, carrier = r['LI_Pays'].split('#', 1)
    do = orders.setdefault(r['PE'], {'orderId': r['PE'], 'id': parts[3], 'zipCode': r['LI_CodePostal'],
                                     'city': r['LI_Ville'], 'country': country, 'carrierKey': carrier,
                                     'details': []})
    pid, sref = r['Product_Code'].split('_', 1)
    do['details'].append({'productId': pid, 'supplierReference': sref, 'name': r['Style'],
                          'quantity': int(float(r['QTY'])), 'ean13List': [r['EAN_Code']]})
api_rows = vp.rows_from_api({'deliveryOrders': list(orders.values())}, parts[0], parts[1])
api_plan = vp.plan_orders(api_rows, find_product, find_carrier, find_price)
simple = lambda p: [(o['name'], o['intitule'], o['carrier_id'],
                     [(l['ean'], l['qty'], l['price'], l['veepee_id']) for l in o['lines']]) for o in p]
check('format API = format Excel', simple(api_plan) == simple(plan))

# a preu 0 (com a TUCTUC: els preus es posen en facturar): sense fitxer de preus no hi ha errors
p0 = vp.plan_orders(rows, find_product, find_carrier, lambda e, t: None, require_price=False)
check('a preu 0: cap error sense fitxer de preus', not [o for o in p0 if o['errors']])
check('a preu 0: totes les línies a 0', all(l['price'] == 0.0 for o in p0 for l in o['lines']))

# errors: EAN inexistent, transportista sense mapeig, preu que falta, comanda que ja existeix
broken = [dict(r) for r in rows[:6]]
broken[0]['EAN_Code'] = '0000000000000'
broken[0]['EANS'] = ['0000000000000']
for r in broken:
    if r['PE'] == broken[-1]['PE']:
        r['LI_Pays'] = 'XX#NOPE'
p = vp.plan_orders(broken, find_product, find_carrier, lambda e, t: None, existing_names=[plan[0]['name']])
check('detecta EAN inexistent', any('no existe' in e for o in p for e in o['errors']))
check('detecta transportista sense mapeig', any('sin mapear' in e for o in p for e in o['errors']))
check('detecta preu que falta', any('sin precio' in e for o in p for e in o['errors']))
check('detecta comanda ja existent', p[0]['exists'])

run(f('04_batch_*.xlsx'), f('08_import_sale_order_*.xlsx'), 1)

print('\n%s' % ('TOT OK' if not fails else 'FALLEN: %s' % ', '.join(fails)))
sys.exit(1 if fails else 0)
