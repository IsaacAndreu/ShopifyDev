# -*- coding: utf-8 -*-
"""Find Odoo automations that could call the FedEx shipping flow.

The chatter author “Almacen Automatizado [081]” is an Odoo user, not proof by
itself that a particular cron called FedEx.  This script reads server actions,
crons and automated actions from the database and prints only metadata and the
keywords they contain.  It never executes their code and makes no HTTP calls.
"""

import json
import re


KEYWORDS = (
    "send_shipping",
    "fedex_rest",
    "send_to_shipper",
    "carrier_id",
    "button_validate",
    "action_done",
    "almacen automatizado",
)


def field_names(record):
    return getattr(record, "_fields", {})


def value(record, name, default=False):
    if name not in field_names(record):
        return default
    return getattr(record, name, default)


def keywords(text):
    lower = (text or "").lower()
    return [keyword for keyword in KEYWORDS if keyword in lower]


def summary(record, code_field="code"):
    model = value(record, "model_id") or value(record, "binding_model_id")
    user = value(record, "user_id")
    code = value(record, code_field, "")
    name = value(record, "name", "")
    return {
        "id": record.id,
        "name": name,
        "active": value(record, "active", None),
        "model": getattr(model, "model", None) if model else None,
        "user": getattr(user, "display_name", None) if user else None,
        "state": value(record, "state", None),
        "trigger": value(record, "trigger", None),
        "keywords": sorted(set(keywords(name) + keywords(code))),
    }


def inspect_model(model_name, code_field="code", name_field="name"):
    if model_name not in env:
        return []
    model = env[model_name].sudo()
    records = model.search([], limit=1000)
    result = []
    for record in records:
        name = value(record, name_field, "")
        code = value(record, code_field, "")
        if keywords(name) or keywords(code):
            result.append(summary(record, code_field))
    return result


print("READ-ONLY FedEx automation diagnosis")
print("No s'executa cap acció de servidor, no hi ha crides HTTP i no es modifica Odoo.")

for model_name in ("ir.cron", "ir.actions.server", "base.automation"):
    rows = inspect_model(model_name)
    print("%s: %s" % (model_name, len(rows)))
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, sort_keys=True, indent=2, default=str))

print("Nota: el codi complet de les accions no es mostra per no exposar credencials ni dades internes.")
env.cr.rollback()
print("ROLLBACK realitzat. Només lectura.")
