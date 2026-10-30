# -*- coding: utf-8 -*-
"""Read-only audit of FedEx tracking history on one or more Odoo pickings.

This does not call FedEx and does not change Odoo.  It inspects chatter,
tracking-value history and attached labels so repeated shipment attempts can be
distinguished from a duplicate result in the FedEx tracking web page.

Environment variables:
  FEDEX_PICKINGS=TT/OUT/0824695,TT/OUT/0825952,TT/OUT/0826365
  FEDEX_TRACKINGS=879269721181,879287863834,879340873575,879287834117
  FEDEX_LIMIT=200
"""

import html
import json
import os
import re


PICKING_NAMES = [
    item.strip() for item in (os.environ.get("FEDEX_PICKINGS") or "").split(",")
    if item.strip()
]
TRACKING_INPUT = [
    item.strip() for item in (os.environ.get("FEDEX_TRACKINGS") or "").split(",")
    if item.strip()
]
try:
    LIMIT = max(1, min(int(os.environ.get("FEDEX_LIMIT", "200")), 500))
except (TypeError, ValueError):
    LIMIT = 200


def field_names(record):
    return getattr(record, "_fields", {})


def value(record, name, default=False):
    if name not in field_names(record):
        return default
    return getattr(record, name, default)


def one(record):
    if not record:
        return None
    return {"id": record.id, "name": getattr(record, "display_name", None)}


def tracking_numbers(text):
    if not text:
        return []
    return sorted(set(re.findall(r"(?<!\d)\d{12}(?!\d)", text)))


def event_kind(body):
    text = re.sub(r"<[^>]*>", " ", body or "")
    text = html.unescape(text).lower()
    kinds = []
    if "shipment sent to carrier" in text or "envío enviado" in text:
        kinds.append("shipment_sent")
    if "documentos fedex" in text:
        kinds.append("documents_generated")
    if "estado del transportista" in text:
        kinds.append("carrier_status")
    return kinds


def tracking_value_summary(message):
    values = value(message, "tracking_value_ids")
    result = []
    for item in values or []:
        field_name = value(item, "field", "")
        field_desc = value(item, "field_desc", "")
        if field_name == "carrier_tracking_ref" or "tracking" in (field_desc or "").lower():
            result.append({
                "field": field_name,
                "field_desc": field_desc,
                "old": value(item, "old_value_char", ""),
                "new": value(item, "new_value_char", ""),
            })
    return result


def message_summary(message):
    body = value(message, "body", "")
    return {
        "id": message.id,
        "date": str(value(message, "date")) if value(message, "date") else None,
        "subject": value(message, "subject", ""),
        "kind": event_kind(body),
        "tracking_numbers_in_body": tracking_numbers(body),
        "tracking_value_changes": tracking_value_summary(message),
    }


def picking_summary(picking):
    attachments = env["ir.attachment"].search([
        ("res_model", "=", "stock.picking"),
        ("res_id", "=", picking.id),
    ], limit=LIMIT)
    messages = value(picking, "message_ids")
    message_data = []
    for message in messages.sorted(key=lambda record: (str(value(record, "date", "")), record.id)):
        summary = message_summary(message)
        if summary["kind"] or summary["tracking_numbers_in_body"] or summary["tracking_value_changes"]:
            message_data.append(summary)
    return {
        "id": picking.id,
        "name": picking.name,
        "state": picking.state,
        "origin": value(picking, "origin", ""),
        "date_done": str(value(picking, "date_done")) if value(picking, "date_done") else None,
        "carrier": one(value(picking, "carrier_id")),
        "carrier_delivery_type": getattr(value(picking, "carrier_id"), "delivery_type", None),
        "carrier_tracking_ref": value(picking, "carrier_tracking_ref", ""),
        "package_count": len(value(picking, "package_ids") or []),
        "message_count": len(messages or []),
        "fedex_state": value(picking, "fedex_rest_shipment_state", None),
        "fedex_send_request_id": value(picking, "fedex_rest_send_request_id", None),
        "fedex_transaction_id": value(picking, "fedex_rest_transaction_id", None),
        "labels": [{
            "id": attachment.id,
            "name": attachment.name,
            "create_date": str(attachment.create_date) if attachment.create_date else None,
        } for attachment in attachments],
        "fedex_events": message_data,
    }


print("READ-ONLY FedEx history diagnosis")
print("Pickings: %s" % (", ".join(PICKING_NAMES) or "(none)"))
print("Trackings inicials: %s" % (", ".join(TRACKING_INPUT) or "(none)"))
print("No es fan crides HTTP a FedEx.")

picking_model = env["stock.picking"]
pickings = picking_model.search([("name", "in", PICKING_NAMES)], limit=LIMIT) if PICKING_NAMES else picking_model.browse()
print("Pickings trobats: %s" % len(pickings))
found_trackings = set(TRACKING_INPUT)
for picking in pickings:
    data = picking_summary(picking)
    found_trackings.add(data["carrier_tracking_ref"] or "")
    for message in data["fedex_events"]:
        found_trackings.update(message["tracking_numbers_in_body"])
        for change in message["tracking_value_changes"]:
            found_trackings.update(tracking_numbers(change.get("old")))
            found_trackings.update(tracking_numbers(change.get("new")))
    print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, default=str))

found_trackings.discard("")
if found_trackings and "carrier_tracking_ref" in field_names(picking_model):
    matches = picking_model.search([
        ("carrier_tracking_ref", "in", sorted(found_trackings)),
    ], limit=LIMIT)
    print("Pickings que comparteixen algun tracking: %s" % len(matches))
    for picking in matches.sorted(key=lambda record: (record.carrier_tracking_ref or "", record.name or "")):
        print(json.dumps({
            "id": picking.id,
            "name": picking.name,
            "state": picking.state,
            "carrier_tracking_ref": picking.carrier_tracking_ref,
        }, ensure_ascii=False, sort_keys=True, indent=2, default=str))

env.cr.rollback()
print("ROLLBACK realitzat. Només lectura; cap canvi a Odoo ni cap petició FedEx.")
