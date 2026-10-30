"""Odoo shell, only reads; EXCHANGE_REMARKS defaults to #349292.
No invoice creation, posting, reconciliation or Shopify calls.
"""
import os


def run(env):
    remarks = os.environ.get('EXCHANGE_REMARKS', '#349292').strip()
    orders = env['sale.order'].search([('ref_remarks', 'in', [remarks, remarks.lstrip('#')])])
    print('Comandes trobades:', len(orders))
    if len(orders) != 1:
        print('Cal identificar una única comanda abans de continuar.')
        return
    order = orders
    print('COMANDA:', order.name, 'estat:', order.state, 'facturació:', order.invoice_status)
    lines = order.order_line.filtered(lambda l: not l.display_type)
    print('LÍNIES VENDA: id | producte | política | demanat | entregat net | facturat net | pendent facturar')
    for line in lines:
        print(line.id, line.product_id.default_code or '(sense SKU)',
              line.product_id.invoice_policy, line.product_uom_qty,
              line.qty_delivered, line.qty_invoiced, line.qty_to_invoice)
    pickings = order.picking_ids
    # Include manual/exchange pickings carrying the same remarks, even if the
    # sale line link is missing. Field availability varies in custom addons.
    Picking = env['stock.picking']
    for field in ('ref_remarks', 'remarks'):
        if field in Picking._fields and Picking._fields[field].store:
            pickings |= Picking.search([
                (field, 'in', [remarks, remarks.lstrip('#')]),
                ('company_id', '=', order.company_id.id)])
    print('MOVIMENTS: albarà | estat | SKU | demanda | fet | UoM | sale_line_id | origen retorn | to_refund')
    unlinked = 0
    for picking in pickings.sorted('id'):
        print('ALBARÀ:', picking.name, picking.state, picking.picking_type_id.code)
        for move in picking.move_lines:
            if not move.sale_line_id:
                unlinked += 1
            print(picking.name, move.state, move.product_id.default_code or '(sense SKU)',
                  move.product_uom_qty, move.quantity_done, move.product_uom.name,
                  move.sale_line_id.id or '-', move.origin_returned_move_id.id or '-', move.to_refund)
    print('Moviments sense línia de venda:', unlinked)
    print('FACTURES/RECTIFICATIVES VINCULADES: document | tipus | estat | total | pendent')
    invoices = order.invoice_ids | lines.mapped('invoice_lines.move_id')
    for invoice in invoices.sorted('id'):
        print(invoice.name, invoice.type, invoice.state, invoice.amount_total, invoice.amount_residual)
        for line in invoice.invoice_line_ids.filtered(lambda l: not l.display_type):
            print('  línia:', line.id, 'SKU:', line.product_id.default_code or '-',
                  'quantitat:', line.quantity, 'subtotal:', line.price_subtotal,
                  'sale_line_ids:', line.sale_line_ids.ids)
    print('No es crea ni es concilia cap document. La rectificativa no demostra per si sola '
          'que la comanda estigui cancel·lada: veure estat de comanda i documents.')


if __name__ == '__main__':
    try:
        run(env)
    except Exception as exc:
        print('Diagnòstic aturat:', type(exc).__name__)
    finally:
        env.cr.rollback()
        print('ROLLBACK realitzat. Sense canvis ni crides a Shopify.')
