# -*- coding: utf-8 -*-
"""Lògica pura (sense Odoo) per convertir un batch de Veepee en files i comandes.

Una "fila" té les mateixes columnes que l'Excel que exporta VentePriveeSync.exe
(PE, Product_Code, EAN_Code, QTY, LI_Intitule, LI_Pays...). Així el mateix codi
serveix per a l'API real i per al mode simulat, que llegeix aquests Excel.
Es pot provar fora d'Odoo: scripts/check_vp_dropship.py.
"""
from collections import OrderedDict

# Columnes de l'Excel de VentePriveeSync (ordre original)
EXCEL_COLUMNS = ['PE', 'Style', 'COLOR', 'SIZE', 'Product_Code', 'EAN_Code', 'QTY', 'Leido', 'SEQ',
                 'Caja', 'LI_Intitule', 'LI_Adresse', 'LI_Complement', 'LI_CodePostal', 'LI_Ville',
                 'LI_CodeRegion', 'LI_Pays', 'LI_Telephone', 'CT_Email', 'DO_DateLivr', 'DO_Date']

TARIFAS = ('es', 'fr_benelux', 'it')


def _txt(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def veepee_product_id(product_code):
    """83787536_KG07C403X1#7-8A -> 83787536 (el que va al camp de la variant)."""
    code = _txt(product_code)
    return code.split('_', 1)[0] if '_' in code else ''


def tarifa_from_text(text):
    """'Veepee - FR_BENELUX' / 'Demo - ES' / 'Tarifa IT' -> 'fr_benelux' / 'es' / 'it'."""
    t = _txt(text).upper()
    if 'FR' in t or 'BENELUX' in t:
        return 'fr_benelux'
    if t.endswith('IT') or ' IT' in t or '-IT' in t:
        return 'it'
    if t.endswith('ES') or ' ES' in t or '-ES' in t:
        return 'es'
    return ''


# ----------------------------------------------------------------------
# API -> files
# ----------------------------------------------------------------------
def _first(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ''):
            return d.get(k)
    return None


def rows_from_api(batch_json, operation_code, batch_ref):
    """Resposta de GET /operations/{op}/batches/{batch} -> files com les de l'Excel.

    Camps que fa servir VentePriveeSync: deliveryOrders[].orderId, zipCode, city,
    country, carrierKey, details[].productId, supplierReference, name, quantity,
    ean13List. LI_Pays = country#carrierKey, Product_Code = productId_supplierReference.
    """
    orders = batch_json.get('deliveryOrders') if isinstance(batch_json, dict) else batch_json
    rows = []
    for do in orders or []:
        # 04/11: com l'Excel de VentePriveeSync: PE (nom DP-) i 3a part = id del delivery order (92...),
        # 4a part = orderId (53...). L'1.1-1.3 els tenia girats i l'app del magatzem donava 404 a Veepee.
        do_ref = _txt(_first(do, 'id', 'deliveryOrderId', 'reference'))
        order_id = _txt(_first(do, 'orderId'))
        country = _txt(_first(do, 'country', 'countryCode'))
        carrier_key = _txt(_first(do, 'carrierKey', 'carrier'))
        commitment = _txt(_first(do, 'logisticCommitmentDate'))
        intitule = '#'.join([_txt(operation_code), _txt(batch_ref), do_ref, order_id])
        for det in do.get('details') or do.get('lines') or []:
            eans = det.get('ean13List') or []
            if isinstance(eans, str):
                eans = [eans]
            eans = [_txt(e) for e in eans if _txt(e)]
            product_id = _txt(_first(det, 'productId'))
            supplier_ref = _txt(_first(det, 'supplierReference'))
            rows.append({
                'PE': do_ref,
                'Style': _txt(det.get('name')),
                'SIZE': supplier_ref.split('#', 1)[1] if '#' in supplier_ref else '',
                'Product_Code': '%s_%s' % (product_id, supplier_ref) if product_id else supplier_ref,
                'EAN_Code': eans[0] if eans else '',
                'EANS': eans,
                'QTY': _txt(det.get('quantity')),
                'LI_Intitule': intitule,
                'LI_CodePostal': _txt(do.get('zipCode')),
                'LI_Ville': _txt(do.get('city')),
                'LI_Pays': '%s#%s' % (country, carrier_key),
                'DO_DateLivr': commitment,
            })
    return rows


# ----------------------------------------------------------------------
# Excel (mode simulat i fitxers de preus / transportistes)
# ----------------------------------------------------------------------
def read_xlsx(path_or_bytes, sheet_index=0):
    """Retorna (capçalera, files) de la fulla indicada. openpyxl si hi és, si no xlrd."""
    import io
    data = path_or_bytes
    if isinstance(path_or_bytes, str):
        with open(path_or_bytes, 'rb') as f:
            data = f.read()
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[sheet_index]
        values = [list(r) for r in ws.iter_rows(values_only=True)]
    except ImportError:
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        sh = book.sheet_by_index(sheet_index)
        values = [sh.row_values(i) for i in range(sh.nrows)]
    values = [r for r in values if any(_txt(c) for c in r)]
    if not values:
        return [], []
    header = [_txt(h) for h in values[0]]
    return header, values[1:]


def rows_from_xlsx(path_or_bytes):
    """Excel de VentePriveeSync (TTUC<campanya>_<batch>_<data>.xlsx) -> files.
    Busca la fulla que té la columna PE (l'Excel d'importació la té en segona posició)."""
    import io
    for idx in range(4):
        try:
            header, values = read_xlsx(path_or_bytes, idx)
        except (IndexError, Exception):
            break
        if 'PE' in header and 'EAN_Code' in header:
            rows = []
            for v in values:
                row = {h: _txt(v[i]) if i < len(v) else '' for i, h in enumerate(header) if h}
                row['EANS'] = [row['EAN_Code']] if row.get('EAN_Code') else []
                rows.append(row)
            return rows
    raise ValueError('El Excel no tiene las columnas del batch de Veepee (PE, EAN_Code...).')


# ----------------------------------------------------------------------
# Files -> comandes
# ----------------------------------------------------------------------
def group_orders(rows):
    """Agrupa les files per comanda Veepee (PE), mantenint l'ordre del batch.
    Si un mateix EAN surt dues vegades a la mateixa comanda, se sumen les unitats."""
    orders = OrderedDict()
    for row in rows:
        pe = row.get('PE')
        if not pe:
            continue
        o = orders.setdefault(pe, {
            'name': 'DP-%s' % pe,
            'intitule': row.get('LI_Intitule', ''),
            'carrier_key': row.get('LI_Pays', ''),
            'lines': OrderedDict(),
        })
        ean = row.get('EAN_Code', '')
        try:
            qty = float(row.get('QTY') or 0)
        except ValueError:
            qty = 0.0
        key = ean or row.get('Product_Code', '')
        line = o['lines'].setdefault(key, {
            'ean': ean, 'eans': row.get('EANS') or ([ean] if ean else []),
            'product_code': row.get('Product_Code', ''),
            'veepee_id': veepee_product_id(row.get('Product_Code')),
            'qty': 0.0,
        })
        line['qty'] += qty
    for o in orders.values():
        o['lines'] = list(o['lines'].values())
    return orders


def plan_orders(rows, find_product, find_carrier, find_price, existing_names=(), require_price=True):
    """Decideix què es crearà. Les funcions de cerca les posa Odoo (o el test):
      find_product(eans) -> id o None
      find_carrier(carrier_key) -> (carrier_id, tarifa) o (None, None)
      find_price(ean, tarifa) -> preu o None
    require_price=False: les comandes es creen a preu 0 (a TUCTUC els preus es posen en facturar).
    Retorna una llista de comandes amb 'errors' (buit = es pot crear)."""
    plan = []
    existing = set(existing_names)
    for o in group_orders(rows).values():
        o = dict(o)
        o['errors'] = []
        o['exists'] = o['name'] in existing
        carrier_id, tarifa = find_carrier(o['carrier_key'])
        o['carrier_id'], o['tarifa'] = carrier_id, tarifa
        if not carrier_id:
            o['errors'].append('Transportista sin mapear: %s' % o['carrier_key'])
        for line in o['lines']:
            line['product_id'] = find_product(line['eans'])
            if not line['product_id']:
                o['errors'].append('EAN %s no existe en Odoo' % (line['ean'] or line['product_code']))
            if line['qty'] <= 0:
                o['errors'].append('EAN %s sin unidades' % line['ean'])
            if not require_price:
                line['price'] = 0.0
                continue
            line['price'] = find_price(line['ean'], tarifa) if tarifa else None
            if tarifa and line['price'] is None:
                o['errors'].append('EAN %s sin precio en la tarifa %s' % (line['ean'], tarifa))
        plan.append(o)
    return plan
