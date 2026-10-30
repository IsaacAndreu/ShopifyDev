# -*- coding: utf-8 -*-
"""Read-only comparison data for nath_shopify_returns on an Odoo server."""

import hashlib
import json
import os

from odoo.modules.module import get_module_path, load_information_from_description_file


MODULE = os.environ.get("SHOPIFY_MODULE", "nath_shopify_returns")
Module = env["ir.module.module"].sudo()
record = Module.search([("name", "=", MODULE)], limit=1)

data = {
    "module": MODULE,
    "db_record_found": bool(record),
    "state": getattr(record, "state", None) if record else None,
    "installed_version": getattr(record, "installed_version", None) if record else None,
    "latest_version": getattr(record, "latest_version", None) if record else None,
}

try:
    module_path = get_module_path(MODULE)
    data["module_path"] = module_path
except Exception as exc:
    module_path = None
    data["module_path_error"] = str(exc)

try:
    info = load_information_from_description_file(MODULE)
    data["manifest_version"] = info.get("version")
    data["manifest_name"] = info.get("name")
except Exception as exc:
    data["manifest_error"] = str(exc)

if module_path:
    for relative in (
        "__manifest__.py",
        "models/shopify_return_log.py",
        "models/shopify_return_followup.py",
    ):
        path = os.path.join(module_path, relative)
        if os.path.isfile(path):
            digest = hashlib.sha256()
            with open(path, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            data.setdefault("file_sha256", {})[relative] = digest.hexdigest()

print("READ-ONLY Shopify module version diagnosis")
print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, default=str))
env.cr.rollback()
print("ROLLBACK realitzat. Cap canvi a Odoo.")
