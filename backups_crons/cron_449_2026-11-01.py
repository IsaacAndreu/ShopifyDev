# Enlaza variantes de Shopify sin producto con el producto de Odoo que tiene el mismo SKU.
# Solo enlaza los casos seguros: exactamente un producto activo con ese SKU, que no sea ANULADO_
# y que no esté enlazado ya con otra variante. El resto se avisa por correo.
# Si no hay SKU exacto, prueba la talla en rango: Shopify 3Y -> Odoo 3-4Y (p. ej. KIRA, MARIONA).
SIMULAR = True
INTEGRACION = 6
DESTINO = 'isaac.andreu@nath.es'
ADMIN = 'https://admin.shopify.com/store/new-tuc-tuc/products/'

Product = env['product.product'].with_context(active_test=False)
Map = env['integration.product.product.mapping']


def ficha(ext):
    return ADMIN + (ext.code or '').split('-')[0]


def esc(t):
    return (t or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


enlazados = []
dudosos = []
for m in Map.search([('integration_id', '=', INTEGRACION), ('product_id', '=', False)]):
    ext = m.external_product_id
    sku = ext.external_reference
    if not sku:
        dudosos.append((ficha(ext), ext.code, 'IT', 'La variante no tiene SKU en Shopify.'))
        continue
    prods = Product.search([('default_code', '=', sku)])
    regla = ''
    if not prods:
        ref, sep, talla = sku.rpartition('_')
        if ref and talla.endswith('Y') and talla[:-1].isdigit():
            n = int(talla[:-1])
            prods = Product.search([('default_code', '=', '%s_%d-%dY' % (ref, n, n + 1))])
            regla = ' (talla %s -> %d-%dY)' % (talla, n, n + 1)
    activos = prods.filtered(lambda p: p.active and not (p.default_code or '').startswith('ANULADO_'))
    if not prods:
        dudosos.append((ficha(ext), sku, 'SHOPIFY', 'No hay ningún producto en Odoo con este SKU: revisar el SKU en Shopify.'))
    elif len(activos) != 1:
        dudosos.append((ficha(ext), sku, 'IT', 'Hay %s productos activos en Odoo con este SKU.' % len(activos)))
    else:
        otro = Map.search([('integration_id', '=', INTEGRACION), ('product_id', '=', activos.id)], limit=1)
        if otro:
            dudosos.append((ficha(ext), sku, 'SHOPIFY', 'El producto ya está enlazado con otra ficha (%s): '
                                                       'posible ficha duplicada.' % ficha(otro.external_product_id)))
        else:
            if not SIMULAR:
                m.write({'product_id': activos.id})
            enlazados.append((ficha(ext), sku, activos.display_name + regla))

modo = ' (SIMULACIÓN)' if SIMULAR else ''
for r in enlazados:
    log('Enlazado%s %s -> %s (%s)' % (modo, r[1], r[2], r[0]))
for r in dudosos:
    log('Revisar %s [%s] %s (%s)' % (r[1], r[2], r[3], r[0]), level='warning')
log('Enlazar variantes%s: %s enlazadas, %s para revisar' % (modo, len(enlazados), len(dudosos)))

if enlazados or dudosos:
    body = '<p>Variantes de Shopify que no tenían producto de Odoo enlazado%s.</p>' % modo
    if enlazados:
        body += ('<h3>Enlazadas automáticamente: %s</h3><table border="1" cellpadding="4" '
                 'style="border-collapse:collapse;font-size:13px"><tr style="background:#eee">'
                 '<th>Ficha Shopify</th><th>SKU</th><th>Producto Odoo</th></tr>%s</table>'
                 % (len(enlazados), ''.join('<tr><td><a href="%s">%s</a></td><td>%s</td><td>%s</td></tr>'
                                            % (r[0], r[0].split('/')[-1], esc(r[1]), esc(r[2]))
                                            for r in sorted(enlazados))))
    if dudosos:
        body += ('<h3>Para revisar: %s</h3><table border="1" cellpadding="4" '
                 'style="border-collapse:collapse;font-size:13px"><tr style="background:#eee">'
                 '<th>Ficha Shopify</th><th>SKU</th><th>Quién</th><th>Qué pasa</th></tr>%s</table>'
                 % (len(dudosos), ''.join('<tr><td><a href="%s">%s</a></td><td>%s</td><td><b>%s</b></td><td>%s</td></tr>'
                                          % (r[0], r[0].split('/')[-1], esc(r[1]), r[2], esc(r[3]))
                                          for r in sorted(dudosos))))
    env['mail.mail'].create({
        'subject': 'Shopify: %s variantes enlazadas, %s para revisar%s' % (len(enlazados), len(dudosos), modo),
        'body_html': body,
        'email_to': DESTINO,
        'email_from': 'TUC TUC <no_reply@tuctuc.com>',
    }).send()
