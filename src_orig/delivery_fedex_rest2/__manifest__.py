# -*- coding: utf-8 -*-
{
    'name': "FedEx REST API Integration",
    'summary': """
        Integración de envío con FedEx utilizando la nueva API REST (OAuth 2.0) para Odoo 13.
    """,
    'description': """
        Este módulo permite conectar Odoo 13 con los servicios de FedEx 
        mediante su API REST moderna, reemplazando la integración SOAP antigua.
        
        Funcionalidades:
        - Autenticación dinámica OAuth 2.0.
        - Configuración de credenciales desde el Método de Envío.
        - Generación de etiquetas en PDF/ZPL directamente en el Albarán.
        - Panel técnico en el Picking para auditoría de Request/Response.
    """,
    'author': "Tu Nombre / Empresa",
    'website': "https://www.tusitio.com",
    'category': 'Operations/Inventory',
    'version': '13.0.1.1.0',
    'license': 'LGPL-3',

    # Dependencias necesarias
    'depends': [
        'base',
        'delivery',
        'stock',
        'mail',
    ],

    # Archivos de vista cargados en orden
    'data': [
        'views/delivery_carrier_views.xml',
        'views/stock_picking_views.xml',
    ],
    
    'installable': True,
    'application': False,
    'auto_install': False,
    
    # Requisito de librería externa
    'external_dependencies': {
        'python': ['requests'],
    },
}
