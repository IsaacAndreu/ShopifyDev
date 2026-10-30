"""Odoo shell: compare existing deliveries/returns, never creates anything.
Uses VP_ORDER_ID and optional VP_CONNECTION_ID=1. No HTTP calls.
"""
import os


def run(env):
    order_id = os.environ.get('VP_ORDER_ID', '').strip()
    if not order_id.isdigit():
        raise ValueError('VP_ORDER_ID must be numeric')
    connection_id = int(os.environ.get('VP_CONNECTION_ID', '1'))
    feeds = env['pink.connect.order.feed'].search([
        ('pink_connect_id', '=', connection_id), ('order_id', '=', order_id)])
    if len(feeds) != 1 or not feeds.sale_order_id:
        print('No hay un único feed vinculado a un pedido. Revisión manual.')
        return
    sale = feeds.sale_order_id
    company = feeds.pink_connect_id.company_id
    if sale.company_id != company:
        print('Compañía del pedido incompatible. Se detiene la consulta.')
        return
    outs = sale.picking_ids.filtered(lambda p: p.picking_type_id.code == 'outgoing')
    print('OUT totales:', len(outs))
    print('OUT hechos:', len(outs.filtered(lambda p: p.state == 'done')))
    print('OUT abiertos:', len(outs.filtered(lambda p: p.state not in ('done', 'cancel'))))
    original = outs.move_lines.filtered(lambda m: m.state == 'done')
    returns = env['stock.move'].search([
        ('origin_returned_move_id', 'in', original.ids),
        ('company_id', '=', company.id), ('state', '!=', 'cancel')])
    picks = returns.mapped('picking_id')
    print('Albaranes de retorno vinculados:', len(picks))
    for index, pick in enumerate(picks.sorted('id'), 1):
        moves = returns.filtered(lambda m: m.picking_id == pick)
        # State is an Odoo enum; no names, remarks, SKU or customer fields.
        print('Retorno #%s: estado=%s; líneas=%s' % (index, pick.state, len(moves)))
    products = original.mapped('product_id').sorted('id')
    print('CANTIDADES POR PRODUCTO ANONIMIZADO (unidad base del producto):')
    for index, product in enumerate(products, 1):
        delivered_moves = original.filtered(lambda m: m.product_id == product)
        returned_moves = returns.filtered(lambda m: m.product_id == product)

        def total(moves, field):
            return sum(m.product_uom._compute_quantity(m[field], product.uom_id) for m in moves)

        delivered = total(delivered_moves, 'quantity_done')
        received = total(returned_moves.filtered(lambda m: m.state == 'done'), 'quantity_done')
        pending = total(returned_moves.filtered(lambda m: m.state != 'done'), 'product_uom_qty')
        print('Producto #%s: entregado=%g; retorno recibido=%g; retorno abierto=%g; '
              'disponible sin nuevo retorno=%g' %
              (index, delivered, received, pending, delivered - received - pending))
    print('EJEMPLOS DE LORENA (solo si pertenecen a esta compañía):')
    for name in ('TT/DEV/0082546', 'TT/DEV/0082547'):
        examples = env['stock.picking'].search([
            ('name', '=', name), ('company_id', '=', company.id)])
        if len(examples) != 1:
            print(name, ': no encontrado de forma inequívoca')
            continue
        pick = examples
        moves = pick.move_lines.filtered(lambda m: m.state != 'cancel')
        related = moves.mapped('origin_returned_move_id')
        belongs = bool(related) and all(m.id in original.ids for m in related)
        print('%s: estado=%s; líneas=%s; origen coincide con OUT consultado=%s' %
              (name, pick.state, len(moves), belongs))
        if belongs:
            included = moves.mapped('product_id')
            print('Productos del OUT omitidos en TT/DEV:', len(products - included))
    print('No compara todavía cantidades solicitadas VP: ese paso requiere el JSON real '
          'y su correspondencia de SKU/GTIN. No concluye por sí solo la política de Lorena.')


if __name__ == '__main__':
    try:
        run(env)
    except Exception as exc:
        print('Diagnóstico detenido:', type(exc).__name__)
    finally:
        env.cr.rollback()
        print('ROLLBACK realizado. Sin cambios en Odoo ni llamadas a PinkConnect.')
