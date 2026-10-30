"""Checks of pilot boundaries without an Odoo installation."""
import ast
import pathlib
import types
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET
import importlib.util
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).parent / 'nath_vp_returns'
source = ast.parse((ROOT / 'models/vp_returns.py').read_text(encoding='utf-8'))
config = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'VPReturnConfig')


def method(name, **namespace):
    node = next(n for n in config.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {'UserError': ValueError, '_': lambda s: s, 'urlsplit': urlsplit, **namespace}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<pilot>', 'exec'), scope)
    return scope[name]


class PilotTests(unittest.TestCase):
    def test_reimport_does_not_duplicate(self):
        class Rows(list):
            def write(self, vals):
                for item in self:
                    item.update(vals)

        class Logs:
            def __init__(self):
                self.rows = Rows()

            def search(self, domain):
                return Rows(row for row in self.rows if all(row[k] == v for k, op, v in domain))

            def create(self, vals):
                self.rows.append(vals)

        logs = Logs()
        rec = Mock(id=1, order_id_filter='123', connection_id=types.SimpleNamespace(id=1))
        rec.env = {'vp.return.request': logs, 'pink.connect.order.feed': Mock(), 'sale.order': []}
        rec.env['pink.connect.order.feed'].search.return_value = []
        fn = method('_import_response', json=__import__('json'))
        raw = '[{"returnRequestId":"a","orderId":"123","status":"PENDING"}]'
        fn(rec, raw, True)
        fn(rec, raw, True)
        self.assertEqual(len(logs.rows), 1)
        fn(rec, raw, False)
        self.assertEqual(len(logs.rows), 2)  # test fixtures never overwrite real data

    def test_anonymized_diagnostic(self):
        spec = importlib.util.spec_from_file_location('vp_diagnostic', ROOT / 'scripts/diagnose_vp_readonly.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        payload = [{'id': 'private-id', 'email': 'private@example.com',
                    'phone': 'private-phone', 'address': 'private-address',
                    'status': 'PENDING', 'quantity': 3, 'api_key': 'private-secret'}]
        output = __import__('json').dumps(module.shape(payload))
        self.assertNotIn('private-', output)
        self.assertNotIn('private@example.com', output)
        self.assertIn('PENDING', output)
        self.assertIn('quantity', output)

    def test_python_and_xml(self):
        for path in ROOT.rglob('*.py'):
            ast.parse(path.read_text(encoding='utf-8'), feature_version=(3, 7))
        for path in ROOT.rglob('*.xml'):
            ET.parse(path)

    def test_rejects_foreign_api_before_transmitting_key(self):
        http = Mock()
        rec = Mock(connection_id=types.SimpleNamespace(url='https://example.com/v4', api_key='dummy'))
        with self.assertRaises(ValueError):
            method('action_read', requests=http)(rec)
        http.get.assert_not_called()

    def test_bounded_get_without_redirects(self):
        http = Mock()
        http.get.return_value.status_code = 200
        http.get.return_value.json.return_value = []
        rec = Mock(connection_id=types.SimpleNamespace(
            url='https://api-pinkstaging.pink-connect.com/v4', api_key='dummy'), order_id_filter='123')
        dates = types.SimpleNamespace(Datetime=types.SimpleNamespace(now=lambda: 'now'))
        method('action_read', requests=http, fields=dates, json=__import__('json'))(rec)
        args, kw = http.get.call_args
        self.assertEqual(args[0], 'https://api-pinkstaging.pink-connect.com/v4/return-requests')
        self.assertEqual(kw['params'], {'orderId': '123', 'limit': 50})
        self.assertFalse(kw['allow_redirects'])
        http.post.assert_not_called()
        http.put.assert_not_called()

    def test_rejects_unknown_schema_and_cross_order_before_import(self):
        rec = Mock(order_id_filter='123')
        fn = method('_import_response', json=__import__('json'))
        for raw in ('{}', '[{"returnRequestId":"a","orderId":"456","status":"PENDING"}]', '[{"unknown":1}]'):
            with self.assertRaises(ValueError):
                fn(rec, raw, False)
        self.assertEqual(rec.env.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
