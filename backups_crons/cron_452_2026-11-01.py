# =============================================================================
# OUT ONLINE QUE NO HA HECHO EL ALMACEN AUTOMATIZADO (correo diario)
# Accion de servidor de Odoo 13. Modelo: stock.picking. Tipo: Ejecutar codigo Python.
# La lanza un cron cada manana.
#
# OUT de pedidos online (WT# Shopify, VP- Veepee) validados AYER (el lunes, desde
#    el viernes) por alguien
#    que no es el usuario "Almacen Automatizado". Quien valida se saca de las
#    lineas del albaran: el ultimo que modifica el albaran no sirve (luego lo
#    tocan para poner el seguimiento, etc.).
# =============================================================================
DESTINO = 'l.callau@nath.es'
COPIA = 'isaac.andreu@nath.es'
ORIGENES = ['WT#%', 'VP-%']
LOGIN_ROBOT = 'oleadas@a.es'      # Almacen Automatizado [081]
MAX_FILAS = 150

madrid = timezone('Europe/Madrid')
utc = timezone('UTC')
hoy = datetime.datetime.now(madrid).date()
ayer = hoy - datetime.timedelta(days=3 if hoy.weekday() == 0 else 1)   # lunes: viernes a domingo
periodo = ayer.strftime('%d/%m/%Y') if (hoy - ayer).days == 1 else '%s al %s' % (
    ayer.strftime('%d/%m'), (hoy - datetime.timedelta(days=1)).strftime('%d/%m/%Y'))


def a_utc(dia):
    inicio = madrid.localize(datetime.datetime(dia.year, dia.month, dia.day))
    return inicio.astimezone(utc).strftime('%Y-%m-%d %H:%M:%S')


def hora(dt):
    return utc.localize(dt).astimezone(madrid).strftime('%d/%m %H:%M') if dt else ''


def esc(t):
    return (t or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def dominio_origen():
    dom = ['|'] * (len(ORIGENES) - 1)
    for o in ORIGENES:
        dom.append(('origin', '=like', o))
    return dom


robot = env['res.users'].with_context(active_test=False).search([('login', '=', LOGIN_ROBOT)], limit=1)
Picking = env['stock.picking']

# Validados ayer sin el robot
hechos = Picking.search([('name', '=like', 'TT/OUT/%'), ('state', '=', 'done'),
                         ('date_done', '>=', a_utc(ayer)), ('date_done', '<', a_utc(hoy))]
                        + dominio_origen(), order='date_done')
quien = {}
for g in env['stock.move.line'].read_group([('picking_id', 'in', hechos.ids)],
                                           ['picking_id', 'write_uid'], ['picking_id', 'write_uid'], lazy=False):
    if g['picking_id'] and g['write_uid']:
        quien.setdefault(g['picking_id'][0], []).append(g['write_uid'])
sin_robot = []
for p in hechos:
    usuarios = quien.get(p.id, [])
    nombres = []
    del_robot = False
    for u in usuarios:      # safe_eval no deja comprensiones ni generadores
        nombres.append(u[1])
        if robot and u[0] == robot.id:
            del_robot = True
    if not del_robot:
        sin_robot.append((p, ', '.join(nombres) or (p.write_uid.name or '')))

base = env['ir.config_parameter'].sudo().get_param('web.base.url')


def enlace(p):
    return '<a href="%s/web#id=%d&amp;model=stock.picking&amp;view_type=form">%s</a>' % (base, p.id, esc(p.name))


celda = 'style="padding:3px 8px;border:1px solid #ccc"'
cab = 'style="padding:3px 8px;border:1px solid #ccc;background:#eee"'

body = '<p>OUT de pedidos online (Shopify WT# y Veepee VP-) del %s.</p>' % periodo
body += '<h3>Validados sin el Almacen Automatizado: %s de %s</h3>' % (len(sin_robot), len(hechos))
if sin_robot:
    filas = ''
    for p, usuarios in sin_robot[:MAX_FILAS]:
        filas += '<tr><td %s>%s</td><td %s>%s</td><td %s>%s</td><td %s>%s</td><td %s>%s</td></tr>' % (
            celda, enlace(p), celda, esc(p.origin), celda, esc(usuarios), celda, hora(p.date_done),
            celda, esc(p.carrier_id.name or ''))
    body += ('<table style="border-collapse:collapse;font-size:13px"><tr><th %s>OUT</th><th %s>Pedido</th>'
             '<th %s>Validado por</th><th %s>Hora</th><th %s>Transportista</th></tr>%s</table>'
             % (cab, cab, cab, cab, cab, filas))
else:
    body += '<p>Ninguno: todos los ha hecho el Almacen Automatizado.</p>'
if len(sin_robot) > MAX_FILAS:
    body += '<p style="color:#666">Solo se muestran los %s primeros.</p>' % MAX_FILAS

log('OUT online sin robot %s: %s de %s validados' % (periodo, len(sin_robot), len(hechos)))
env['mail.mail'].create({
    'subject': 'OUT online sin el Almacen Automatizado: %s del %s' % (len(sin_robot), periodo),
    'body_html': body,
    'email_to': DESTINO,
    'email_cc': COPIA,
    'email_from': 'TUC TUC <no_reply@tuctuc.com>',
}).send()
