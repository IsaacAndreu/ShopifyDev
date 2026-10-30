# -*- coding: utf-8 -*-
"""
COMPROVACIÓ NOMÉS DE LECTURA per a PRODUCCIÓ (no cal tenir el mòdul instal·lat).

- Llegeix de Shopify les devolucions sol·licitades (query GraphQL, cap mutation).
- Comprova els permisos (scopes) de l'app de Shopify.
- Per cada devolució, fa a Odoo les mateixes validacions que faria el mòdul:
  comanda per ref_remarks, OUT Hecho, parcials, TT/DEV existent, SKU.
- No crida Nacex, no aprova res i acaba amb rollback.

Ús (al servidor, amb l'usuari d'Odoo):
    odoo shell -c /ruta/odoo.conf -d NOM_BD --no-http < check_shopify_returns_readonly.py
"""

ORDERS_QUERY = """
{
  orders(first: 25, query: "return_status:return_requested") {
    edges { node {
      id name email
      customer { displayName }
      shippingAddress { name zip city countryCodeV2 phone }
      returns(first: 10) { edges { node {
        id name status
        returnLineItems(first: 100) { edges { node {
          quantity
          ... on ReturnLineItem { fulfillmentLineItem { lineItem { sku } } }
        } } }
      } } }
    } }
  }
}
"""
SCOPES_QUERY = "{ currentAppInstallation { accessScopes { handle } } }"


def _gql(adapter, query):
    import json
    res = adapter.execute_graphql(query)
    if isinstance(res, (str, bytes)):
        res = json.loads(res)
    if res.get('errors'):
        raise Exception(res['errors'])
    return res.get('data') or {}


def _check_odoo(remarks, lines):
    Sale = env['sale.order']
    sales = Sale.search([('ref_remarks', '=', remarks)])
    if len(sales) != 1:
        return 'REVISIO: %s comandes amb aquest remarks' % len(sales)
    outs_done = sales.picking_ids.filtered(
        lambda p: p.picking_type_code == 'outgoing' and p.state == 'done')
    pending = sales.picking_ids.filtered(
        lambda p: p.picking_type_code == 'outgoing' and p.state not in ('done', 'cancel'))
    if not outs_done:
        return 'REVISIO: cap OUT Hecho'
    if len(outs_done) > 1 or pending or outs_done.backorder_id:
        return 'REVISIO: parcials (%s)' % ', '.join((outs_done | pending).mapped('name'))
    out = outs_done
    has_dev = env['stock.picking'].search([
        ('move_lines.origin_returned_move_id', 'in', out.move_lines.ids),
        ('state', '!=', 'cancel')])
    if has_dev:
        return 'JA TÉ DEV: %s' % ', '.join(has_dev.mapped('name'))
    for sku, qty in lines:
        move = out.move_lines.filtered(
            lambda m: sku and sku in (m.product_id.default_code, m.product_id.barcode))
        if not move:
            return 'REVISIO: SKU %s no és a %s' % (sku, out.name)
    return 'OK -> es crearia la DEV de %s (%s línies)' % (out.name, len(out.move_lines))


integrations = env['sale.integration'].search([])
print('\n=== Integracions ===')
for integ in integrations:
    print(integ.id, integ.name, getattr(integ, 'type_api', '?'))

for integ in integrations:
    if 'shopify' not in str(getattr(integ, 'type_api', '')).lower():
        continue
    print('\n=== %s ===' % integ.name)
    try:
        adapter = integ._build_adapter()
        try:
            print('API version:', adapter._client.api_version)
        except Exception:
            pass
        scopes = [s['handle'] for s in
                  _gql(adapter, SCOPES_QUERY)['currentAppInstallation']['accessScopes']]
        for needed in ('read_returns', 'write_returns', 'read_orders'):
            print('  scope %-14s %s' % (needed, 'SÍ' if needed in scopes else 'NO  <-- falta'))

        data = _gql(adapter, ORDERS_QUERY)
        edges = data.get('orders', {}).get('edges', [])
        print('Comandes amb devolució sol·licitada: %s' % len(edges))
        for e in edges:
            o = e['node']
            for r in o['returns']['edges']:
                r = r['node']
                if r['status'] != 'REQUESTED':
                    continue
                lines = []
                for li in r['returnLineItems']['edges']:
                    li = li['node']
                    sku = ((li.get('fulfillmentLineItem') or {}).get('lineItem') or {}).get('sku')
                    lines.append((sku, li['quantity']))
                name = (o.get('customer') or {}).get('displayName') or (o.get('shippingAddress') or {}).get('name')
                print('- %s | %s | %s | %s | %s' % (o['name'], r['name'], name, o.get('email'), lines))
                print('    Odoo: %s' % _check_odoo(o['name'], lines))
    except Exception as ex:
        print('ERROR:', ex)

env.cr.rollback()
print('\nFet (només lectura, rollback).')
