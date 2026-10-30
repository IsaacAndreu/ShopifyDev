"""Exercise actual DEV construction method with lightweight Odoo doubles."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import unittest


class Rows(list):
    def sorted(self, key):
        return Rows(sorted(self, key=lambda x: getattr(x, key)))

    def filtered(self, fn):
        return Rows(x for x in self if fn(x))

    def mapped(self, field):
        return Rows(item for row in self for item in getattr(row, field))

    def __getitem__(self, item):
        value = super().__getitem__(item)
        return Rows(value) if isinstance(item, slice) else value

    @property
    def id(self):
        return self[0].id if len(self) == 1 else False

    @property
    def ids(self):
        return [row.id for row in self]


class Tests(unittest.TestCase):
    def execute(self, quantities, requested=None, previous=False):
        tree = ast.parse(Path('nath_shopify_returns/models/shopify_return_log.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ShopifyReturnLog')
        node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_step_create_dev')
        scope = {'UserError': ValueError, '_': lambda s: s}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-method>', 'exec'), scope)
        unit = NS(rounding=0.01, _compute_quantity=lambda qty, unit: qty)
        product = NS(id=1, uom_id=unit)
        outs = Rows(NS(id=i, state='done', message_post=Mock(), move_lines=Rows([
            NS(id=i + 10, state='done', quantity_done=q, product_id=product, product_uom=unit)
        ])) for i, q in enumerate(quantities, 1))
        stock_moves = Mock()
        stock_moves.search.return_value = [object()] if previous else []
        wizard = Mock()
        wizard.with_context.return_value = wizard
        wizard.create.return_value.create_returns.return_value = {'res_id': 100}
        dev = Mock(name='dev')
        dev.name = 'TEST/DEV'
        pickings = Mock()
        pickings.browse.return_value = dev
        rec = NS(out_picking_ids=outs, out_picking_id=outs[:1],
                 config_id=NS(return_full_order=requested is None, return_location_id=NS(id=2)),
                 line_ids=Rows(NS(ignore=False, quantity=q, product_id=product, sku='TEST')
                               for q in (requested or [])),
                 env={'stock.move': stock_moves, 'stock.return.picking': wizard, 'stock.picking': pickings},
                 shopify_return_name='TEST', remarks='TEST')
        scope['_step_create_dev'](rec)
        return wizard.create.call_args.args[0]['product_return_moves']

    def test_full_17_plus_1(self):
        moves = self.execute([17, 1])
        self.assertEqual([x[2]['quantity'] for x in moves], [17, 1])
        self.assertEqual([x[2]['move_id'] for x in moves], [11, 12])

    def test_partial_across_outs(self):
        self.assertEqual([x[2]['quantity'] for x in self.execute([1, 2], [2])], [1, 1])

    def test_duplicate_requests_cannot_reuse_units(self):
        with self.assertRaises(ValueError):
            self.execute([1, 1], [2, 1])

    def test_existing_return_blocks_creation(self):
        with self.assertRaises(ValueError):
            self.execute([17, 1], previous=True)


if __name__ == '__main__':
    unittest.main()
