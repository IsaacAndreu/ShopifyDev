# =============================================================================
# DP: CONFIRMAR PEDIDOS DROPSHIPPING AUTOMATICAMENTE (a partir de las 17:15)
# Accion de servidor de Odoo 13. Modelo: sale.order. Tipo: Ejecutar codigo Python.
# La lanza un cron cada 5 minutos. Trabaja de 17:15 a 07:00 (hora de Madrid) y
# todo el dia el fin de semana. "Ejecutar manualmente" en el cron la lanza al momento.
#
# En cada ejecucion confirma pedidos DP- en presupuesto, uno a uno y guardando
# despues de cada uno, hasta gastar SEGUNDOS. Asi nunca bloquea Odoo mucho rato.
# Solo confirma los pedidos que ya tienen los datos actualizados (transportista,
# fecha de entrega, modo y plazo de pago). Los que fallan no se reintentan hasta
# el dia siguiente. Resultado de cada pedido en Ajustes > Tecnico > Registros.
#
# SIMULAR = True: no confirma nada y muestra un aviso con lo que haria (a cualquier
# hora). Para probarla: Ejecutar manualmente desde la accion.
# =============================================================================
SIMULAR = True
SEGUNDOS = 90           # tiempo maximo por ejecucion
INICIO = '17:15'       # entre semana, desde esta hora (Madrid)
FIN = '07:00'           # hasta esta hora del dia siguiente; sabado y domingo, todo el dia

ahora = datetime.datetime.now(timezone('Europe/Madrid'))
en_horario = SIMULAR or ahora.weekday() >= 5 or not (FIN <= ahora.strftime('%H:%M') < INICIO)
if en_horario:
    hace_un_dia = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    pedidos = env['sale.order'].search([('name', '=like', 'DP-%'), ('state', 'in', ['draft', 'sent'])], order='id')

    t0 = time.time()
    hechos = 0
    lineas = 0
    sin_datos = []
    for pedido in pedidos:
        if not SIMULAR and time.time() - t0 > SEGUNDOS:
            break
        faltan = []
        # transportista y fecha de entrega solo se ponen en el paso de "actualizacion de datos"
        if not pedido.carrier_id:
            faltan.append('transportista')
        if not pedido.commitment_date:
            faltan.append('fecha de entrega')
        if not pedido.payment_mode_id:
            faltan.append('modo de pago')
        if not pedido.payment_term_id:
            faltan.append('plazo de pago')
        if faltan:
            sin_datos.append(pedido.name)
            continue
        if env['ir.logging'].search_count([('func', '=', 'DP: confirmar pedidos automaticamente'),
                                           ('message', '=like', pedido.name + ' ERROR%'),
                                           ('create_date', '>=', hace_un_dia)]):
            continue  # ya fallo en las ultimas 24 h
        if SIMULAR:
            hechos += 1  # en simulacion no se apunta pedido a pedido, solo el resumen
            lineas += len(pedido.order_line)
            continue
        nombre = pedido.name
        t1 = time.time()
        try:
            pedido.with_context(confirm='yes').action_confirm()
            env.cr.commit()
            log('%s confirmado en %.1f s' % (nombre, time.time() - t1))
            hechos += 1
        except Exception as e:
            env.cr.rollback()
            log('%s ERROR: %s' % (nombre, str(e)[:300]), level='warning')

    resumen = 'Ejecucion: %s pedidos %s en %.0f s · %s pendientes · %s sin datos actualizados%s' % (
        hechos, 'por confirmar (SIMULACION, %s lineas)' % lineas if SIMULAR else 'confirmados', time.time() - t0,
        len(pedidos) - hechos - len(sin_datos), len(sin_datos),
        (' (p. ej. %s)' % ', '.join(sin_datos[:5])) if sin_datos else '')
    log(resumen)
    if SIMULAR:
        raise Warning(resumen)
