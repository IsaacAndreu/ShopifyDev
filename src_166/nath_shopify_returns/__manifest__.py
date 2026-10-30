# -*- coding: utf-8 -*-
{
    'name': 'NATH - Devoluciones Shopify automáticas',
    'summary': 'Shopify (devolución solicitada) -> TT/DEV -> Nacex eDevoluciones (44) -> '
               'aprobación Shopify -> recepción',
    'version': '13.0.1.6.6',
    'category': 'Inventory',
    'author': 'NATH',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'stock',
        'sale_stock',
        'integration_shopify',
        'delivery_nacex',
        'delivery_fedex_rest2',
        'sales_ext',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template.xml',
        'data/ir_cron.xml',
        'data/ir_cron_summary.xml',
        'views/shopify_return_views.xml',
    ],
    'installable': True,
    'application': False,
}
