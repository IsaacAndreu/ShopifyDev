# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ShopifyReturnConfig(models.Model):
    _name = 'shopify.return.config'
    _description = 'Configuración devoluciones Shopify'

    name = fields.Char('Nombre', required=True)
    active = fields.Boolean('Activo', default=True)
    integration_id = fields.Many2one(
        'sale.integration', string='Integración Shopify', required=True,
        help='Tienda Shopify (conector VentorTech) de la que se leen las devoluciones.')
    company_id = fields.Many2one(
        'res.company', string='Compañía', required=True,
        default=lambda self: self.env.company)
    carrier_id = fields.Many2one(
        'delivery.carrier', string='Transportista Nacex (servicio 44)', required=True,
        domain=[('delivery_type', '=', 'nacex')],
        help='Transportista Nacex con tip_ser = 44 y el abonado de la marca '
             '(p. ej. 4307 / 60527 TUC TUC).')
    nacex_country_ids = fields.Many2many(
        'res.country', 'shopify_return_config_nacex_country_rel', 'config_id', 'country_id',
        string='Países por Nacex',
        default=lambda self: self.env.ref('base.es', raise_if_not_found=False),
        help='Las devoluciones de estos países van por Nacex. Las demás, por FedEx.')
    fedex_carrier_id = fields.Many2one(
        'delivery.carrier', string='Transportista FedEx',
        domain=[('delivery_type', '=', 'fedex_rest')],
        help='Transportista FedEx REST (con el servicio FEDEX_REGIONAL_ECONOMY). '
             'Si está vacío, las devoluciones de fuera de los países Nacex quedan para revisar.')
    fedex_pickup_country_ids = fields.Many2many(
        'res.country', 'shopify_return_config_fedex_pickup_rel', 'config_id', 'country_id',
        string='FedEx: países con recogida a domicilio',
        default=lambda self: self.env.ref('base.fr', raise_if_not_found=False),
        help='En estos países FedEx pasa a recoger el paquete. En el resto, el cliente lo lleva a un punto FedEx.')
    fedex_check_locations = fields.Boolean(
        'FedEx: si no hay puntos cerca, recogida a domicilio', default=True,
        help='Antes de crear el envío pregunta a FedEx si hay puntos FedEx cerca del cliente. '
             'Si no hay ninguno, se programa recogida a domicilio (como en Francia).')
    fedex_location_radius = fields.Integer('FedEx: radio de búsqueda de puntos (km)', default=20)
    fedex_pickup_fallback = fields.Boolean(
        'FedEx: si falla la recogida, entrega en punto', default=True,
        help='Si FedEx no acepta la recogida a domicilio, la devolución sigue adelante: '
             'se aprueba en Shopify con la etiqueta y el cliente la lleva a un punto FedEx.')
    fedex_pickup_from = fields.Char('FedEx: recogida desde', default='12:00')
    fedex_pickup_to = fields.Char('FedEx: recogida hasta', default='18:00')
    fedex_weight = fields.Float('FedEx: peso (kg)', default=1.0)
    fedex_length = fields.Integer('FedEx: largo (cm)', default=20)
    fedex_width = fields.Integer('FedEx: ancho (cm)', default=20)
    fedex_height = fields.Integer('FedEx: alto (cm)', default=10)
    fedex_description = fields.Char('FedEx: descripción contenido', default="Children's Clothing")
    simulate_fedex = fields.Boolean(
        'Simular FedEx', default=False,
        help='No llama a FedEx: escribe en el chat la petición que se enviaría y pone un seguimiento ficticio TESTFX/...')
    return_location_id = fields.Many2one(
        'stock.location', string='Ubicación de devolución', required=True,
        help='p. ej. WH-OR/Stock/DEVOLUCION_ONLINE o MODAI/Stock/DEVOLUCION_ONLINE')
    dest_partner_id = fields.Many2one(
        'res.partner', string='Dirección de entrega Nacex', required=True,
        help='Dónde llega la devolución (p. ej. TUC TUC, C/Rin 6-8, 43870 Amposta).')

    auto_process = fields.Boolean(
        'Procesar automáticamente', default=False,
        help='Desactivado (piloto): el cron solo crea los registros y alguien los '
             'procesa con el botón. Activado: el cron lo hace todo solo.')
    return_full_order = fields.Boolean(
        'TT/DEV con todo el pedido', default=True,
        help='Marcado: como la acción "Devs masivas ONLINE" actual (todas las líneas del OUT). '
             'Desmarcado: solo los artículos y cantidades de la devolución de Shopify.')
    nacex_return_method = fields.Selection(
        [('label', 'Etiqueta eDevolución abierta (el cliente elige el NACEX.shop)'),
         ('expedition', 'Expedición con punto NACEX.shop fijo')],
        string='Nacex: tipo de devolución', default='label', required=True,
        help='Etiqueta abierta = lo mismo que la web de Nacex: el cliente la lleva al NACEX.shop que quiera.')
    nacex_tip_cob = fields.Selection(
        [('D', 'Destino (paga TucTuc)'), ('T', 'Tercera'), ('O', 'Origen')],
        string='Nacex: portes', default='D',
        help='En una devolución el remitente es el cliente: los portes van a Destino (nuestro abonado).')
    nacex_shop_code = fields.Char(
        'Nacex: código NACEX.shop por defecto',
        help='Punto NACEX.shop de la recogida (campo shop_codigo). Obligatorio para el servicio 44. '
             'Se puede cambiar en cada devolución antes de procesarla.')
    fedex_eu_no_customs = fields.Boolean(
        'FedEx: sin factura comercial dentro de la UE', default=True,
        help='Entre países de la UE no hay aduanas: no se pide factura comercial ni ETD.')
    nacex_prealert_customer = fields.Boolean(
        'Prealerta Nacex por email al cliente', default=True)
    send_label_email = fields.Boolean(
        'Enviar etiqueta PDF desde Odoo', default=False,
        help='Alternativa si el email de Nacex no le llega al cliente: Odoo le envía '
             'la etiqueta PDF con la plantilla indicada.')
    mail_template_id = fields.Many2one(
        'mail.template', string='Plantilla email etiqueta',
        domain=[('model', '=', 'shopify.return.log')],
        default=lambda self: self.env.ref(
            'nath_shopify_returns.mail_template_return_label', raise_if_not_found=False))
    shopify_notify_customer = fields.Boolean(
        'Shopify: notificar al cliente al aprobar', default=True,
        help='Envía el email personalizado "Se aprobó tu devolución". '
             'Requiere una versión de la API que acepte notifyCustomer.')
    shopify_add_tracking = fields.Boolean(
        'Shopify: subir el seguimiento Nacex', default=True,
        help='Después de aprobar, añade a la devolución de Shopify el albarán y el enlace de '
             'seguimiento de Nacex. Así no hace falta usar "No se requiere envío".')
    shopify_upload_label = fields.Boolean(
        'Shopify: subir también la etiqueta PDF', default=True,
        help='Sube la etiqueta (Nacex o FedEx) a la devolución de Shopify, como "Subir una etiqueta de devolución". '
             'Shopify se la envía al cliente con el seguimiento.')
    shopify_notify_tracking = fields.Boolean(
        'Shopify: email al cliente con el seguimiento', default=False)
    auto_accept_if_ok = fields.Boolean(
        'Reembolsar automáticamente si llega todo bien', default=False,
        help='Cuando el almacén valida la TT/DEV y llega todo lo esperado (sin nota de incidencia), '
             'el cron hace el reembolso en Shopify y la rectificativa con el importe de Shopify. '
             'Con diferencias, siempre queda para revisar.')
    refund_journal_id = fields.Many2one(
        'account.journal', string='Diario rectificativas', domain=[('type', '=', 'sale')],
        help='Diario donde se crean las rectificativas (p. ej. FRAS WEB). '
             'Vacío: el de la factura original.')
    auto_post_refund = fields.Boolean(
        'Validar la rectificativa automáticamente', default=False,
        help='Desmarcado: la rectificativa queda en borrador, como hacía Prestashop.')
    refund_notify_customer = fields.Boolean(
        'Shopify: email al cliente al reembolsar', default=True)
    # --- Proves (base de dades demo) ---
    simulate_shopify = fields.Boolean(
        'Simular Shopify', default=False,
        help='No se conecta a Shopify: las devoluciones se crean a mano con '
             '"Crear devolución de prueba" y la aprobación solo se registra en el chat.')
    simulate_nacex = fields.Boolean(
        'Simular Nacex', default=False,
        help='No llama al WS de Nacex: escribe en el chat la cadena que se enviaría '
             'y pone un albarán ficticio TEST/...')
    max_attempts = fields.Integer('Reintentos máximos (errores técnicos)', default=3)

    def action_open_test_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Crear devolución de prueba',
            'res_model': 'shopify.return.test.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_config_id': self.id},
        }

    def action_fetch_returns(self):
        Log = self.env['shopify.return.log']
        for config in self:
            Log._fetch_for_config(config)
        return True
