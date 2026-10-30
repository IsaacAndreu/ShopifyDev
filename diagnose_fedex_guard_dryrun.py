# -*- coding: utf-8 -*-
"""Dry-run of the minimal FedEx duplicate guard.

This script intentionally does not write Odoo and never calls FedEx.  It
reports what the proposed guard would do for existing pickings and simulates a
second call arriving immediately after the first one.

Environment variables:
  FEDEX_PICKINGS=TT/OUT/0824695,TT/OUT/0825952,TT/OUT/0826365
"""

import json
import os
import re


PICKING_NAMES = [
    item.strip() for item in (os.environ.get("FEDEX_PICKINGS") or "").split(",")
    if item.strip()
]


def field_names(record):
    return getattr(record, "_fields", {})


def value(record, name, default=False):
    if name not in field_names(record):
        return default
    return getattr(record, name, default)


def tracking_numbers(text):
    if not text:
        return []
    return sorted(set(re.findall(r"(?<!\d)\d{12}(?!\d)", text)))


def picking_report(picking):
    attachments = env["ir.attachment"].search([
        ("res_model", "=", "stock.picking"),
        ("res_id", "=", picking.id),
        ("name", "ilike", "LABEL_"),
    ])
    messages = value(picking, "message_ids") or env["mail.message"].browse()
    shipment_events = []
    for message in messages:
        body = message.body or ""
        if "shipment sent to carrier" in body.lower() or "envío enviado" in body.lower():
            shipment_events.extend(tracking_numbers(body))

    current_tracking = value(picking, "carrier_tracking_ref") or ""
    current_guard_state = value(picking, "fedex_rest_shipment_state") or ""
    if current_tracking:
        decision = "REUTILITZAR tracking actual; 0 POST a FedEx"
        first_call = "REUTILITZAR"
        second_call = "REUTILITZAR"
    elif current_guard_state in ("sending", "sent"):
        decision = "BLOQUEJAR; expedició iniciada o pendent de revisió"
        first_call = "BLOQUEJAR"
        second_call = "BLOQUEJAR"
    else:
        decision = "PERMETRE 1 POST i marcar sending abans de cridar FedEx"
        first_call = "CREAR 1 expedició"
        second_call = "BLOQUEJAR per estat sending"

    return {
        "id": picking.id,
        "name": picking.name,
        "state": picking.state,
        "carrier_tracking_ref": current_tracking,
        "fedex_guard_state_field_present": "fedex_rest_shipment_state" in field_names(picking),
        "fedex_guard_state": current_guard_state,
        "label_count": len(attachments),
        "label_names": sorted(attachments.mapped("name")),
        "shipment_events": shipment_events,
        "decision_now": decision,
        "simulation_first_call": first_call,
        "simulation_immediate_second_call": second_call,
    }


print("READ-ONLY FedEx guard dry-run")
print("Pickings: %s" % (", ".join(PICKING_NAMES) or "(none)"))
print("No es fan canvis a Odoo i no es fan crides HTTP a FedEx.")

picking_model = env["stock.picking"]
pickings = picking_model.search([("name", "in", PICKING_NAMES)]) if PICKING_NAMES else picking_model.browse()
print("Pickings trobats: %s" % len(pickings))
for picking in pickings.sorted(key=lambda record: record.name or ""):
    print(json.dumps(picking_report(picking), ensure_ascii=False, sort_keys=True, indent=2, default=str))

env.cr.rollback()
print("ROLLBACK realitzat. Simulació finalitzada.")
