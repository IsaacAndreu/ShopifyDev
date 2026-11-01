# Pedidos de Shopify que no han entrado en Odoo: diagnóstico por pedido.
# Cada resultado se guarda en Ajustes > Técnico > Registros (ir.logging).
DIAS = 15
INTEGRACION = 6
ADMIN = 'https://admin.shopify.com/store/new-tuc-tuc/products/'

desde = (datetime.datetime.now() - datetime.timedelta(days=DIAS)).strftime('%Y-%m-%d %H:%M:%S')
Ext = env['integration.product.product.external']
Map = env['integration.product.product.mapping']


def lineas(raw):
    # raw_data es JSON con sangría: se sacan los pares product_id / variant_id de cada línea
    res = []
    pos = 0
    while True:
        i = raw.find('"product_id": ', pos)
        if i < 0:
            break
        pid = raw[i + 14:raw.find(',', i)].strip()
        j = raw.find('"variant_id": ', i)
        vid = raw[j + 14:raw.find(',', j)].strip() if j >= 0 else ''
        res.append((pid, vid))
        pos = i + 14
    return res


def exc_previa(job):
    return bool(job.exc_info)


def diagnostico(f, job):
    exc = job.exc_info or ''
    if not job:
        return ('IT', 'No tiene job de creación de pedido.')
    if job.state != 'failed' and not exc:
        return ('ESPERAR', 'El job está en estado "%s": todavía se está procesando.' % job.state)
    if 'external_reference)=(' in exc:
        sku = exc.split('external_reference)=(')[1].split(', ', 1)[1].split(')')[0]
        nueva = Ext.search([('integration_id', '=', INTEGRACION), ('external_reference', '=', sku)], limit=1)
        nueva_pid = nueva.code.split('-')[0] if nueva else '?'
        antiguas = set()
        for pid, vid in lineas(f.raw_data or ''):
            if pid.isdigit() and vid.isdigit() and pid != nueva_pid and not Ext.search_count(
                    [('integration_id', '=', INTEGRACION), ('code', '=', pid + '-' + vid)]):
                antiguas.add(pid)
        return ('SHOPIFY', 'SKU duplicado %s: la ficha antigua %s sigue a la venta (la nueva es %s%s). '
                           'Archivar la antigua.' % (sku.rsplit('_', 1)[0],
                                                     ', '.join(ADMIN + a for a in sorted(antiguas)) or '?',
                                                     ADMIN, nueva_pid))
    if 'Failed to find external variant with code "' in exc:
        code = exc.split('external variant with code "')[1].split('"')[0]
        ficha = ADMIN + code.split('-')[0]
        ext = Ext.search([('integration_id', '=', INTEGRACION), ('code', '=', code)], limit=1)
        if not ext or not ext.external_reference:
            return ('IT', 'Variante %s nueva en Shopify sin importar en Odoo (%s).' % (code, ficha))
        sku = ext.external_reference
        if Map.search_count([('external_product_id', '=', ext.id), ('product_id', '!=', False)]):
            return ('REINTENTAR', 'SKU %s ya está enlazado: se puede reintentar (%s).' % (sku, ficha))
        if env['product.product'].with_context(active_test=False).search_count([('default_code', '=', sku)]):
            return ('IT', 'SKU %s existe en Odoo pero no está enlazado (%s).' % (sku, ficha))
        return ('SHOPIFY', 'SKU %s de la ficha %s no existe en Odoo: revisar el SKU en Shopify.' % (sku, ficha))
    if 'external tax with code "' in exc:
        tax = exc.split('external tax with code "')[1].split('"')[0]
        return ('CONTABILIDAD', 'Falta el impuesto "%s" en el conector.' % tax)
    if "multiple 'Season' or 'Brand'" in exc:
        return ('IT', 'Pedido con productos de varias temporadas o marcas: Odoo no deja crearlo. Crear a mano.')
    if 'integration_res_partner_external' in exc:
        return ('REINTENTAR', 'Error puntual al crear el cliente.')
    ultima = exc.strip().split('\n')[-1] if exc else job.state
    return ('IT', 'Otro error: %s' % ultima[:200])


def skus(raw):
    res = []
    pos = 0
    while True:
        i = raw.find('"sku": "', pos)
        if i < 0:
            break
        res.append(raw[i + 8:raw.find('"', i + 8)])
        pos = i + 8
    return res


def fecha_pedido(f):
    # fecha del pedido en Shopify (hora local de la tienda); si no se encuentra, la de entrada en Odoo
    raw = f.raw_data or ''
    i = raw.find('"created_at": "')
    if i >= 0 and raw[i + 15:i + 19].isdigit():
        return datetime.datetime.strptime(raw[i + 15:i + 34], '%Y-%m-%dT%H:%M:%S')
    return f.create_date


extra = {}
filas = []
for f in env['sale.integration.input.file'].search(
        [('si_id', '=', INTEGRACION), ('order_id', '=', False), ('create_date', '>=', desde)], order='id'):
    ref = f.order_reference or f.name
    if env['sale.order'].search_count([('ref_remarks', '=', ref)]):
        continue  # creado a mano
    job = env['queue.job'].search([('name', 'ilike', '"%s"' % f.name)], order='id desc', limit=1)
    responsable, texto = diagnostico(f, job)
    if job and job.state != 'failed' and exc_previa(job):
        texto += ' (Reintento en cola, aún sin procesar.)'
    filas.append((ref, job, responsable, texto))
    extra[ref] = (fecha_pedido(f), f.name, skus(f.raw_data or ''))


# Pedidos de los que Shopify ha avisado (webhook orders/create) pero que no han llegado a Odoo.
# No tienen input file, asi que arriba no salen (p. ej. si la recepcion del conector se para).
def primer_id(raw):
    pos = 0
    while True:
        i = raw.find('"id": ', pos)
        if i < 0:
            return ''
        k = i + 6
        while k < len(raw) and raw[k].isdigit():
            k += 1
        if k - (i + 6) >= 10:
            return raw[i + 6:k]
        pos = i + 6


def nombre_webhook(raw):
    i = raw.find('"name": "#')
    return raw[i + 9:raw.find('"', i + 9)] if i >= 0 else ''


hace_una_hora = (datetime.datetime.now() - datetime.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
vistos = {}
for w in env['ir.logging'].search([('func', '=', 'ShopifyWebhook'), ('name', '=', 'shopify: orders_create'),
                                   ('message', 'like', '"integration_id": %s' % INTEGRACION),
                                   ('create_date', '>=', desde), ('create_date', '<', hace_una_hora)], order='id'):
    raw = w.message or ''
    shop_id = primer_id(raw)
    if not shop_id or shop_id in vistos:
        continue
    vistos[shop_id] = True
    if env['sale.integration.input.file'].search_count([('si_id', '=', INTEGRACION), ('name', '=', shop_id)]):
        continue
    ref = nombre_webhook(raw) or shop_id
    if env['sale.order'].search_count([('ref_remarks', '=', ref)]):
        continue  # creado a mano
    i = raw.find('"created_at": "')
    fecha = datetime.datetime.strptime(raw[i + 15:i + 34], '%Y-%m-%dT%H:%M:%S') \
        if i >= 0 and raw[i + 15:i + 19].isdigit() else w.create_date
    filas.append((ref, False, 'RECEPCION', 'Shopify ha avisado del pedido pero no ha llegado a Odoo.'))
    extra[ref] = (fecha, shop_id, skus(raw))


DESTINO = 'isaac.andreu@nath.es'
PEDIDOS = 'https://admin.shopify.com/store/new-tuc-tuc/orders/'
QUE_HACER = {
    'SHOPIFY': 'Avisar al equipo online para que lo corrija en Shopify. Este pedido hay que crearlo a mano en Odoo.',
    'IT': 'Lo revisa IT.',
    'CONTABILIDAD': 'Confirmar con contabilidad qué impuesto usar.',
    'REINTENTAR': 'Lanzar la acción planificada "Shopify: reintentar pedidos sin entrar".',
    'RECEPCION': 'Avisar a IT: la recepcion de pedidos de Shopify puede estar parada (IT lo hace entrar desde la integracion).',
    'ESPERAR': 'Nada por ahora: si mañana sigue aquí, avisar a IT.',
}


def esc(t):
    return (t or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def fila_html(r):
    fecha, shop_id, lista = extra[r[0]]
    dias = (datetime.datetime.now() - fecha).days
    return ('<tr><td>%s<br/><small>hace %s días</small></td>'
            '<td><a href="%s%s">%s</a></td><td>%s</td><td><b>%s</b></td><td>%s</td><td>%s</td></tr>'
            % (fecha.strftime('%d/%m/%Y'), dias, PEDIDOS, shop_id, esc(r[0]), esc(', '.join(lista)),
               esc(r[2]), esc(r[3]), esc(QUE_HACER.get(r[2], ''))))


for r in filas:
    log('%s [%s] %s' % (r[0], r[2], r[3]), level='warning')
log('Correo diario: %s pedidos sin entrar en Odoo' % len(filas))
if filas:
    asunto = 'Shopify: %s pedidos sin entrar en Odoo' % len(filas)
    body = ('<p>Pedidos de Shopify de los últimos %s días que no han entrado en Odoo y tampoco se han creado a mano: '
            '<b>%s</b></p>'
            '<table border="1" cellpadding="5" style="border-collapse:collapse;font-size:13px">'
            '<tr style="background:#eee"><th>Fecha</th><th>Pedido</th><th>Productos (SKU)</th><th>Quién</th>'
            '<th>Qué pasa</th><th>Qué hacer</th></tr>%s</table>'
            % (DIAS, len(filas), ''.join(fila_html(r) for r in filas)))
else:
    asunto = 'Shopify: todos los pedidos han entrado en Odoo'
    body = '<p>Todos los pedidos de Shopify de los últimos %s días están en Odoo.</p>' % DIAS
body += ('<p style="color:#666;font-size:12px">Los pedidos creados a mano en Odoo no salen en la lista. '
         'Detalle de cada revisión en Ajustes &gt; Técnico &gt; Registros.</p>')
env['mail.mail'].create({
    'subject': asunto,
    'body_html': body,
    'email_to': DESTINO,
    'email_cc': 'l.callau@nath.es,salvador.ridaura@nath.es',
    'email_from': 'TUC TUC <no_reply@tuctuc.com>',
}).send()
