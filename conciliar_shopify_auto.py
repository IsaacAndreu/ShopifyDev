# =============================================================================
# CONCILIAR AUTOMATICAMENTE LO QUE CUADRA (extractos Shopify)
# Accion de servidor de Odoo 13. Modelo: account.bank.statement. Ejecutar codigo Python.
# Se lanza desde el extracto (Accion), despues de "Asignar terceros para conciliacion".
#
# Para cada linea sin conciliar que tiene pedido (nombre de la linea = pedido, p. ej.
# WT#349724): busca las facturas validadas de ese pedido y, si hay EXACTAMENTE un
# apunte pendiente con el mismo importe al centimo (cobro -> factura, devolucion ->
# rectificativa), la concilia igual que el boton "Validar" de la conciliacion.
# Lo que no cuadra (liquidaciones, comisiones, importes distintos, varias facturas...)
# se queda para hacerlo a mano como siempre.
#
# SIMULAR = True: no concilia nada y muestra cuantas lineas conciliaria.
# =============================================================================
SIMULAR = True

Sale = env['sale.order']
resumen = []
for st in records:
    if st.state != 'open':
        resumen.append('%s: el extracto no esta en estado Nuevo, no se toca.' % (st.name or st.date))
        continue
    hechas = 0
    revisar = []
    for line in st.line_ids:
        if line.journal_entry_ids or not line.partner_id or not line.amount:
            continue
        if line.currency_id and line.currency_id != line.company_id.currency_id:
            revisar.append('%s: otra moneda' % line.name)
            continue
        pedido = Sale.search([('name', '=', line.name), ('company_id', '=', line.company_id.id)], limit=1)
        if not pedido and line.ref:
            pedido = Sale.search([('ref_remarks', '=', line.ref), ('company_id', '=', line.company_id.id)], limit=1)
        if not pedido:
            continue   # liquidaciones, comisiones, ingresos...
        tipo = 'out_invoice' if line.amount > 0 else 'out_refund'
        candidatos = []   # sin lambdas con variables de fuera: safe_eval
        for factura in pedido.invoice_ids:
            if factura.state != 'posted' or factura.type != tipo:
                continue
            for aml in factura.line_ids:
                if aml.account_id.internal_type in ('receivable', 'payable') and not aml.reconciled \
                        and round(aml.amount_residual - line.amount, 2) == 0:
                    candidatos.append(aml)
        if len(candidatos) != 1:
            revisar.append('%s: %s' % (line.name, 'sin factura con el mismo importe' if not candidatos
                                       else '%s facturas con el mismo importe' % len(candidatos)))
            continue
        aml = candidatos[0]
        if not SIMULAR:
            line.process_reconciliation(counterpart_aml_dicts=[{
                'name': aml.move_id.name,
                'debit': -aml.amount_residual if aml.amount_residual < 0 else 0.0,
                'credit': aml.amount_residual if aml.amount_residual > 0 else 0.0,
                'move_line': aml,
            }])
        hechas += 1
    texto = '%s lineas %s · %s para revisar a mano' % (
        hechas, 'se conciliarian (SIMULACION)' if SIMULAR else 'conciliadas automaticamente', len(revisar))
    if revisar:
        texto += ':<br/>' + '<br/>'.join(revisar[:60])
    if not SIMULAR:
        st.message_post(body='Conciliacion automatica: ' + texto)
    resumen.append('%s: %s' % (st.name or st.date, texto.replace('<br/>', '\n')))

if SIMULAR:
    raise Warning('\n\n'.join(resumen) or 'Nada que hacer.')
