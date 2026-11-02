# -*- coding: utf-8 -*-
{
    'name': 'NATH - Dropshipping Veepee (batches automáticos)',
    'summary': 'Descarga los batches de dropshipment.veepee.com y crea los pedidos DP- '
               'con precio, transportista y fecha de entrega',
    'version': '13.0.0.1.2',
    'category': 'Sales',
    'author': 'NATH',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'sale_stock',
        'delivery',
        'sales_ext',
        'queue_job',
    ],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/vp_dropship_views.xml',
        'wizard/vp_dropship_import_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
}
