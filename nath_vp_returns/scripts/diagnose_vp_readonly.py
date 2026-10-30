"""Run inside Odoo shell. Only GET to PinkConnect; always rollback Odoo.

Required environment: VP_ORDER_ID. Optional VP_CONNECTION_ID (default 1).
No API token or contact values are printed. No production test is executed
just by installing the addon.
"""
import json
import os
from urllib.parse import urlsplit

import requests


ENUMS = {'PENDING', 'PROCESSING', 'COMPLETE', 'COMPLETED', 'REJECTED',
         'CANCELLED', 'HOMEPICKUP', 'HOME_PICKUP', 'ES', 'FR'}


def shape(value, key='', depth=0):
    """Keep field names and JSON types, never arbitrary scalar values."""
    if depth > 12:
        return '<depth-limit>'
    if isinstance(value, dict):
        return {k: shape(v, k, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return {'_type': 'array', '_length': len(value),
                '_sample': [shape(v, key, depth + 1) for v in value[:2]]}
    if value is None:
        return '<null>'
    if key in ('status', 'type', 'countryIsoCode') and isinstance(value, str) and value in ENUMS:
        return value
    if isinstance(value, bool):
        return '<boolean>'
    if isinstance(value, (int, float)):
        return '<number>'
    return '<string>'


def run(env):
    order_id = os.environ.get('VP_ORDER_ID', '').strip()
    if not order_id.isdigit():
        raise ValueError('VP_ORDER_ID debe ser el ID numérico interno de PinkConnect.')
    config_id = int(os.environ.get('VP_CONNECTION_ID', '1'))
    config = env['pink.connect.channel.configuration'].browse(config_id).exists()
    if len(config) != 1:
        raise ValueError('No existe la conexión indicada.')
    parts = urlsplit(config.url or '')
    if (parts.scheme != 'https' or parts.netloc not in
            ('api.pink-connect.com', 'api-pinkstaging.pink-connect.com') or
            parts.path.rstrip('/') != '/v4' or parts.query or parts.fragment):
        raise ValueError('URL API oficial v4 no válida; no se envían credenciales.')
    if not config.api_key:
        raise ValueError('La conexión no tiene clave API.')
    print('Entorno:', parts.hostname)
    print('Conexión Odoo ID:', config_id)
    feeds = env['pink.connect.order.feed'].search([
        ('pink_connect_id', '=', config.id), ('order_id', '=', order_id)])
    print('Coincidencias feed:', len(feeds))
    print('Pedido Odoo vinculado:', len(feeds) == 1 and bool(feeds.sale_order_id))
    try:
        response = requests.get(
            config.url.rstrip('/') + '/return-requests',
            headers={'Authorization': 'Bearer ' + config.api_key, 'Accept': 'application/json'},
            params={'orderId': order_id, 'limit': 50}, timeout=(10, 45),
            allow_redirects=False)
    except requests.RequestException:
        print('ERROR de conexión; no se muestra la excepción para no revelar datos.')
        return
    print('HTTP:', response.status_code)
    if response.status_code != 200:
        print('No se muestra el cuerpo del error. No hay reintentos ni redirecciones.')
        return
    try:
        data = response.json()
    except ValueError:
        print('Respuesta no JSON; no se muestra el cuerpo.')
        return
    print('ESQUEMA ANONIMIZADO:')
    print(json.dumps(shape(data), ensure_ascii=False, indent=2))
    if isinstance(data, list):
        from collections import Counter
        states = Counter(row.get('status') for row in data if isinstance(row, dict))
        print('Estados:', {s: states[s] for s in sorted(ENUMS) if states[s]})
    print('Una sola página (máximo 50); no presupone que sea la lista completa.')


if __name__ == '__main__':
    try:
        run(env)  # env supplied by odoo shell
    except Exception as exc:
        # Do not print exception text: libraries can include server responses.
        print('Diagnóstico detenido:', type(exc).__name__)
    finally:
        env.cr.rollback()
        print('ROLLBACK realizado. Sin cambios en Odoo; solo GET en PinkConnect.')
