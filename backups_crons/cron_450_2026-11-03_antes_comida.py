# =============================================================================
# DP: CONFIRMAR PEDIDOS DROPSHIPPING AUTOMATICAMENTE (a partir de las 17:15)
# Accion de servidor de Odoo 13. Modelo: sale.order. Tipo: Ejecutar codigo Python.
# La lanza un cron cada 2 minutos. Trabaja de 17:15 a 07:00 (hora de Madrid) y
# todo el dia el fin de semana. "Ejecutar manualmente" en el cron la lanza al momento.
#
# En cada ejecucion confirma pedidos DP- en presupuesto, uno a uno y guardando
# despues de cada uno, hasta gastar SEGUNDOS. Asi nunca bloquea Odoo mucho rato.
# Solo confirma los pedidos que ya tienen los datos actualizados (transportista,
# fecha de entrega, modo y plazo de pago). Los que fallan no se reintentan hasta
# el dia siguiente. Resultado de cada pedido en Ajustes > Tecnico > Registros.
#
# SIMULAR = True: no confirma nada y muestra un aviso con lo que haria (a cualquier
# hora). Para probarla: Ejecutar manualmente desde el cron.
# =============================================================================
SIMULAR = False
SEGUNDOS = 600          # tiempo maximo por ejecucion (el limite real es MAX_POR_EJECUCION)
MAX_POR_EJECUCION = 20  # pedidos confirmados por ejecucion (03/11: 20 en horas de almacen)
INICIO = '11:00'       # entre semana, desde esta hora (Madrid) -- 03/11: batch del dia (sale 11:31-12:00), 20 hasta las 17:00
FIN = '07:00'           # hasta esta hora del dia siguiente; sabado y domingo, todo el dia

ahora = datetime.datetime.now(timezone('Europe/Madrid'))
en_horario = SIMULAR or ahora.weekday() >= 5 or not (FIN <= ahora.strftime('%H:%M') < INICIO)
# 03/11: no confirmar mientras algun batch Veepee aun este creando pedidos
por_crear = env['vp.dropship.batch'].search_count([('state', 'in', ('downloaded', 'creating'))])
if en_horario and por_crear and not SIMULAR:
    log('Esperando: %s batch(es) Veepee aun creando pedidos' % por_crear)
    en_horario = False
# 03/11: la 1.1 del modulo no pone el modo de pago (sales_ext lo deja vacio): 118 CONFIRMING / SIN AVISO / SIN RECURSO
if en_horario and not SIMULAR:
    sin_modo = env['sale.order'].search([('name', '=like', 'DP-%'), ('state', 'in', ['draft', 'sent']),
                                         ('payment_mode_id', '=', False)])
    if sin_modo:
        sin_modo.write({'payment_mode_id': 118})
        env.cr.commit()
        log('Modo de pago 118 puesto en %s pedidos DP' % len(sin_modo))
if en_horario:
    hace_un_dia = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    pedidos = env['sale.order'].search([('name', '=like', 'DP-%'), ('state', 'in', ['draft', 'sent'])], order='id')

    t0 = time.time()
    hechos = 0
    lineas = 0
    sin_datos = []
    # 02/11: como a mano. Un LOTE con la accion "Confirm to Sales Order" (795), la misma del menu
    # Accion (uno a uno con commit iba 10 veces mas lento). 40 por lote en horas de almacen y 100
    # a partir de las 17:00 y el fin de semana. Si el lote falla, se prueban uno a uno.
    tope = MAX_POR_EJECUCION if (ahora.weekday() < 5 and FIN <= ahora.strftime('%H:%M') < '17:00') else 100
    accion = env['ir.actions.server'].browse(795)
    lote = env['sale.order']
    for pedido in pedidos:
        if len(lote) >= tope:
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
        lote |= pedido
    if SIMULAR:
        hechos = len(lote)
        lineas = len(lote.mapped('order_line'))
    elif lote:
        ids = lote.ids
        nombres = lote.mapped('name')
        t1 = time.time()
        try:
            accion.with_context(active_model='sale.order', active_ids=ids, active_id=ids[0]).run()
            env.cr.commit()
            log('Lote de %s confirmado en %.0f s (%s ... %s)' % (len(ids), time.time() - t1, nombres[0], nombres[-1]))
            hechos = len(ids)
        except Exception as e:
            env.cr.rollback()
            log('Lote de %s con error, se confirman uno a uno: %s' % (len(ids), str(e)[:300]), level='warning')
            for pedido in env['sale.order'].browse(ids):
                if pedido.state not in ('draft', 'sent'):
                    continue
                nombre = pedido.name
                t1 = time.time()
                try:
                    accion.with_context(active_model='sale.order', active_ids=[pedido.id], active_id=pedido.id).run()
                    env.cr.commit()
                    log('%s confirmado en %.1f s' % (nombre, time.time() - t1))
                    hechos += 1
                except Exception as e2:
                    env.cr.rollback()
                    log('%s ERROR: %s' % (nombre, str(e2)[:300]), level='warning')

    resumen = 'Ejecucion: %s pedidos %s en %.0f s · %s pendientes · %s sin datos actualizados%s' % (
        hechos, 'por confirmar (SIMULACION, %s lineas)' % lineas if SIMULAR else 'confirmados', time.time() - t0,
        len(pedidos) - hechos - len(sin_datos), len(sin_datos),
        (' (p. ej. %s)' % ', '.join(sin_datos[:5])) if sin_datos else '')
    log(resumen)
    if SIMULAR:
        raise Warning(resumen)
