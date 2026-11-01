{
    'name': 'NATH - Devoluciones VP (piloto)',
    'version': '13.0.0.2.0',
    'license': 'LGPL-3',
    'depends': ['odoo_pink_connect', 'nath_shopify_returns'],
    'data': ['security/security.xml', 'security/ir.model.access.csv', 'views/returns.xml', 'data/ir_cron.xml'],
    'installable': True,
    'application': False,
}
