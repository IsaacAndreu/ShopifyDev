"""Boundary tests of actual methods; no Odoo server or accounting writes."""
import ast
import pathlib
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).parent / 'nath_exchange_billing'
TREE = ast.parse((ROOT / 'models/billing.py').read_text(encoding='utf-8'))


def method(cls, name, **extra):
    target = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == cls)
    node = next(n for n in target.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {'UserError': ValueError, '_': lambda s: s,
             'float_compare': lambda a, b, precision_rounding: 0 if abs(a-b) < precision_rounding/2 else (1 if a>b else -1)}
    scope.update(extra)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-method>', 'exec'), scope)
    return scope[name]


class Tests(unittest.TestCase):
    def test_exchange_8_return_6_plus_2_sends_creates_three_drafts(self):
        class Rows(list):
            def filtered(self, fn):
                return Rows(x for x in self if fn(x))

            def sorted(self, key):
                return Rows(sorted(self, key=lambda x: getattr(x, key)))

            def mapped(self, path):
                result = Rows()
                for row in self:
                    obj = row
                    for part in path.split('.'):
                        obj = getattr(obj, part)
                    if obj not in result:
                        result.append(obj)
                return result

        unit = NS(id=1, name='Units')
        product = NS(id=1, display_name='TEST')
        lines = Rows()
        for i, (qty, kind) in enumerate(((8, 'out_refund'), (6, 'out_invoice'), (2, 'out_invoice')), 1):
            picking = NS(id=i, name='PICK-%s' % i)
            lines.append(NS(id=i, existing_line_id=False, kind=kind, quantity=qty, price_unit=10,
                product_id=product, account_id=NS(id=7), tax_ids=NS(ids=[]),
                stock_move_id=NS(picking_id=picking, product_uom=unit)))
        generated = []

        def create(vals):
            generated.append(vals)
            invoice_lines = Rows(NS(nath_exchange_line_id=next(l for l in lines if l.id == cmd[2]['nath_exchange_line_id']))
                                 for cmd in vals['invoice_line_ids'])
            return NS(invoice_line_ids=invoice_lines)

        account = Mock()
        account.with_context.return_value = account
        account.create.side_effect = create
        plan = NS(id=1, state='prepared', checked=True, review_snapshot='same',
                  _access=Mock(), _lock=Mock(), _validate_header=Mock(), _validate_lines=Mock(),
                  _snapshot=lambda: 'same', sale_id=False, invoice_ids=[], line_ids=lines,
                  company_id=NS(id=1), partner_id=NS(id=1), journal_id=NS(id=1), currency_id=NS(id=1),
                  original_invoice_id=NS(id=77), name='TEST', message_post=Mock(),
                  action_open_documents=Mock(return_value={'documents': True}), env={'account.move': account})
        dates = NS(Date=NS(context_today=lambda record: '2026-10-28'))
        method('ExchangePlan', 'action_create_drafts', fields=dates)(plan)
        self.assertEqual([d['type'] for d in generated], ['out_refund', 'out_invoice', 'out_invoice'])
        self.assertEqual([d['invoice_line_ids'][0][2]['quantity'] for d in generated], [8, 6, 2])
        self.assertEqual(generated[0]['reversed_entry_id'], 77)
        self.assertTrue(all('sale_line_ids' not in cmd[2] for d in generated for cmd in d['invoice_line_ids']))
        self.assertEqual(plan.state, 'done')
        method('ExchangePlan', 'action_create_drafts', fields=dates)(plan)
        self.assertEqual(len(generated), 3)

    def test_syntax_and_manifest(self):
        for p in ROOT.rglob('*.py'):
            ast.parse(p.read_text(encoding='utf-8'), feature_version=(3, 7))
        manifest = ast.literal_eval((ROOT / '__manifest__.py').read_text(encoding='utf-8'))
        for filename in manifest['data']:
            self.assertTrue((ROOT / filename).exists())
            if filename.endswith('.xml'):
                ET.parse(ROOT / filename)

    def test_no_network_or_posting_reconciliation_calls(self):
        # This addon must not grow a hidden financial/network side effect.
        names = {n.attr for n in ast.walk(TREE) if isinstance(n, ast.Attribute)}
        for name in ('action_post', 'post', 'reconcile', '_shopify_graphql', 'request', 'get_token'):
            self.assertNotIn(name, names)

    def test_repeat_done_returns_existing_documents(self):
        plan = Mock(state='done')
        plan._lock = Mock()
        plan.action_open_documents.return_value = {'existing': True}
        result = method('ExchangePlan', 'action_create_drafts')(plan)
        self.assertEqual(result, {'existing': True})
        plan._validate_lines.assert_not_called()
        self.assertEqual(plan.env.mock_calls, [])

    def test_changed_snapshot_cannot_create(self):
        plan = Mock(state='prepared', checked=True, review_snapshot='old')
        plan._lock = Mock()
        plan._snapshot.return_value = 'changed'
        with self.assertRaises(ValueError):
            method('ExchangePlan', 'action_create_drafts')(plan)
        self.assertEqual(plan.env.mock_calls, [])

    def test_existing_documents_cannot_be_regenerated(self):
        plan = Mock(state='prepared', checked=True, review_snapshot='same', invoice_ids=[object()])
        plan._lock = Mock()
        plan._snapshot.return_value = 'same'
        with self.assertRaises(ValueError):
            method('ExchangePlan', 'action_create_drafts')(plan)
        self.assertEqual(plan.env.mock_calls, [])

    def test_refund_guard_blocks_protected_order(self):
        rec = Mock(sale_id=NS(id=12, nath_exchange_hold=True, invalidate_cache=Mock()))
        with self.assertRaises(ValueError):
            method('ShopifyReturn', '_exchange_refund_guard')(rec)

    def test_existing_line_requires_exact_product_quantity_and_type(self):
        unit = NS(rounding=0.01, _compute_quantity=lambda qty, target: qty)
        plan = NS(partner_id=NS(commercial_partner_id=1), currency_id=2)
        invoice = NS(state='posted', type='out_invoice', commercial_partner_id=1, currency_id=2)
        line = NS(product_uom_id=unit, quantity=2, move_id=invoice, company_id=3, product_id=4)
        coverage = NS(ensure_one=lambda: None, existing_line_id=line, plan_id=plan,
                      stock_move_id=NS(product_uom=unit), quantity=2, kind='out_invoice', company_id=3, product_id=4)
        fn = method('ExchangeLine', '_validate_existing')
        fn(coverage)
        for key, bad in [('quantity', 1), ('product_id', 99), ('company_id', 99)]:
            original = getattr(line, key)
            setattr(line, key, bad)
            with self.assertRaises(ValueError):
                fn(coverage)
            setattr(line, key, original)
        invoice.type = 'out_refund'
        with self.assertRaises(ValueError):
            fn(coverage)

    def test_uniqueness_guards_present(self):
        source = (ROOT / 'models/billing.py').read_text(encoding='utf-8')
        for constraint in ('unique(stock_move_id)', 'unique(existing_line_id)', 'unique(nath_exchange_line_id)'):
            self.assertIn(constraint, source)


if __name__ == '__main__':
    unittest.main()
