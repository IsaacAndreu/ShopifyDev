# =============================================================================
# DP: CREAR AGRUPACIONES Y OLEADAS AUTOMATICAMENTE
# Accion de servidor de Odoo 13. Modelo: stock.picking. Tipo: Ejecutar codigo Python.
# La lanza un cron cada 2 minutos, en el mismo horario que la confirmacion de DP.
#
# Lo mismo que se hacia a mano (manual Dropshipping Privalia, "Creacion de
# agrupaciones y oleadas"):
#   - OUT de pedidos DP- reservados, sin agrupacion, sin backorder y aun en stock
#     (no en WH-OR/SORTER), agrupados por transportista y fecha prevista
#   - agrupaciones de hasta MAX_PEDIDOS OUT: B-DP_<transportista sin "Veepee - ">_<ddmmaa>;
#     si salen varias del mismo nombre, _1, _2, _3... (ddmmaa = dia anterior a la fecha prevista)
#   - "Crear transfer para oleada" de cada agrupacion (INT al SORTER)
# Espera a que no quede ningun pedido DP por confirmar, para que salgan completas.
# Cada ejecucion crea UNA agrupacion: asi nunca bloquea Odoo mucho rato.
#
# SIMULAR = True: no crea nada y muestra un aviso con las agrupaciones que haria
# (a cualquier hora). Para probarla: Ejecutar manualmente desde el cron.
# =============================================================================
SIMULAR = False
MAX_PEDIDOS = 150
INICIO = '17:00'       # entre semana, desde esta hora (Madrid)
FIN = '07:00'           # hasta esta hora del dia siguiente; sabado y domingo, todo el dia

madrid = timezone('Europe/Madrid')
utc = timezone('UTC')
ahora = datetime.datetime.now(madrid)
en_horario = SIMULAR or ahora.weekday() >= 5 or not (FIN <= ahora.strftime('%H:%M') < INICIO)

por_confirmar = env['sale.order'].search_count([
    ('name', '=like', 'DP-%'), ('state', 'in', ['draft', 'sent']),
    ('carrier_id', '!=', False), ('commitment_date', '!=', False)])

if en_horario and (SIMULAR or not por_confirmar):
    outs = env['stock.picking'].search([
        ('name', '=like', 'TT/OUT/%'), ('origin', '=like', 'DP-%'), ('state', '=', 'assigned'),
        ('batch_id', '=', False), ('backorder_id', '=', False),
        ('location_id.barcode', '!=', 'SORTER'),
    ], order='id')
    # como el cron de web/ECI: fuera los que ya tienen algo preparado
    outs = outs.filtered(lambda p: not p.move_line_ids_without_package.filtered(lambda l: l.qty_done > 0))

    # Grupos por transportista + fecha prevista (hora de Madrid)
    grupos = {}
    orden = []
    for p in outs:
        dia = utc.localize(p.scheduled_date).astimezone(madrid).date() if p.scheduled_date else ahora.date()
        clave = (p.carrier_id.id, dia)
        if clave not in grupos:
            grupos[clave] = env['stock.picking']
            orden.append(clave)
        grupos[clave] |= p

    def unidades(pickings):
        return sum(pickings.mapped('move_lines.product_uom_qty'))

    def nombre_base(pickings, dia):
        transp = (pickings[0].carrier_id.name or 'SIN_TRANSPORTISTA').replace('Veepee - ', '')
        transp = transp.replace(' - ', '_').replace(' ', '_')
        return 'B-DP_%s_%s' % (transp, (dia - datetime.timedelta(days=1)).strftime('%d%m%y'))

    def partes(pickings):
        return int((len(pickings) + MAX_PEDIDOS - 1) / MAX_PEDIDOS) or 1

    def siguiente_nombre(base, usados, total_partes):
        """Una sola agrupacion: sin numero. Varias del mismo nombre: _1, _2, _3..."""
        existentes = env['stock.picking.batch'].search([('name', '=like', base + '%')]).mapped('name') + usados
        n = 0   # safe_eval no deja comprensiones
        for x in existentes:
            if x == base or x.startswith(base + '_'):
                n += 1
        return base if n == 0 and total_partes == 1 else '%s_%d' % (base, n + 1)

    def primer_trozo(pickings):
        """OUT de la primera agrupacion: se reparte por igual, sin pasar de MAX_PEDIDOS."""
        tamano = int((len(pickings) + partes(pickings) - 1) / partes(pickings))
        return pickings[:tamano]

    if SIMULAR:
        lineas = []
        usados = []
        for clave in orden:
            restantes = grupos[clave]
            base = nombre_base(restantes, clave[1])
            total_partes = partes(restantes)
            while restantes:
                trozo = primer_trozo(restantes)
                nombre = siguiente_nombre(base, usados, total_partes)
                usados.append(nombre)
                lineas.append('%s: %s OUT, %s u.' % (nombre, len(trozo), int(unidades(trozo))))
                restantes -= trozo
        resumen = 'SIMULACION agrupaciones DP: %s OUT en %s agrupaciones%s\n%s' % (
            len(outs), len(lineas),
            (' (atencion: quedan %s pedidos DP por confirmar)' % por_confirmar) if por_confirmar else '',
            '\n'.join(lineas) or 'Nada que agrupar.')
        log(resumen)
        raise Warning(resumen)
    elif orden:
        clave = orden[0]
        trozo = primer_trozo(grupos[clave])
        nombre = siguiente_nombre(nombre_base(trozo, clave[1]), [], partes(grupos[clave]))
        t0 = time.time()
        try:
            batch = env['stock.picking.batch'].create({'name': nombre, 'company_id': trozo[0].company_id.id})
            trozo.write({'batch_id': batch.id})
            model.create_transfer_for_batch(trozo)
            env.cr.commit()
            log('%s creada: %s OUT, %s u., oleada en %.0f s' % (nombre, len(trozo), int(unidades(trozo)), time.time() - t0))
        except Exception as e:
            env.cr.rollback()
            log('%s ERROR: %s' % (nombre, str(e)[:300]), level='warning')
