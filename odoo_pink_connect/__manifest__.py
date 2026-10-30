# -*- coding: utf-8 -*-
{
    'name': "Pink Connect Odoo",

    'summary': """
        Connect Odoo With PinkConnect""",
    'author': "Brain Station 23 LTD",
    'website': "http://www.brainstation-23.com",
    'license': 'OPL-1',
    'category': 'Sales',
    'version': '',
    'depends': ['base', 'mail', 'sales_ext'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/menus.xml',
        'views/base/product_product.xml',
        'wizard/import_operation.xml',
        'views/base/pink_connect_channel_configuration.xml',
        # 'views/base/shops_view.xml',
        'views/feeds/order_feed.xml',
        'views/base/res_partner.xml',
        'views/base/sale_order.xml',
        'views/mapping/order_mapping.xml',
        'data/ir_cron.xml',
        'views/base/pink_synchronization.xml',
        'data/so_sequence.xml'

    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
