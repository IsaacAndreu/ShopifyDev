# -*- coding: utf-8 -*-
"""Read-only investigation of a duplicated FedEx tracking number.

Run this file through the Odoo shell.  It deliberately prints only metadata and
small, anonymised summaries of the FedEx request/response; it never calls FedEx
and rolls the Odoo cursor back before exiting.

Expected environment variables:
  FEDEX_TRACKING=879337633282
  FEDEX_PICKING=TT/OUT/0825526       (optional)
  FEDEX_LIMIT=100                     (optional)
"""

import hashlib
import json
import os


TRACKING = (os.environ.get("FEDEX_TRACKING") or "").strip()
PICKING_NAME = (os.environ.get("FEDEX_PICKING") or "").strip()
try:
    LIMIT = max(1, min(int(os.environ.get("FEDEX_LIMIT", "100")), 500))
except (TypeError, ValueError):
    LIMIT = 100


def field_names(record):
    return getattr(record, "_fields", {})


def value(record, name, default=False):
    if name not in field_names(record):
        return default
    return getattr(record, name, default)


def one(value_):
    """Return a JSON-friendly scalar for a many2one/record value."""
    if not value_:
        return None
    if hasattr(value_, "id"):
        return {"id": value_.id, "name": getattr(value_, "display_name", None)}
    return value_


def sha256(text):
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def parse_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def request_summary(text):
    parsed = parse_json(text)
    if not isinstance(parsed, dict):
        return {"present": bool(text), "sha256_16": sha256(text), "json": False}
    requested = parsed.get("requestedShipment") or {}
    packages = requested.get("requestedPackageLineItems") or []
    references = []
    for package in packages[:20]:
        for reference in package.get("customerReferences") or []:
            if reference.get("customerReferenceType") == "CUSTOMER_REFERENCE":
                references.append(reference.get("value"))
    return {
        "present": True,
        "sha256_16": sha256(text),
        "account_present": bool((parsed.get("accountNumber") or {}).get("value")),
        "serviceType": requested.get("serviceType"),
        "packagingType": requested.get("packagingType"),
        "pickupType": requested.get("pickupType"),
        "totalPackageCount": requested.get("totalPackageCount"),
        "requestedPackageLineItems": len(packages),
        "customerReferences": references,
    }


def response_summary(text):
    parsed = parse_json(text)
    if not isinstance(parsed, dict):
        return {"present": bool(text), "sha256_16": sha256(text), "json": False}
    output = parsed.get("output") or {}
    shipments = output.get("transactionShipments") or []
    shipment_summaries = []
    for shipment in shipments[:20]:
        pieces = shipment.get("pieceResponses") or []
        piece_summaries = []
        for piece in pieces[:50]:
            piece_summaries.append({
                "trackingNumber": piece.get("trackingNumber"),
                "packageDocuments": len(piece.get("packageDocuments") or []),
            })
        shipment_summaries.append({
            "masterTrackingNumber": shipment.get("masterTrackingNumber"),
            "serviceType": shipment.get("serviceType"),
            "pieceResponses": len(pieces),
            "pieces": piece_summaries,
        })
    return {
        "present": True,
        "sha256_16": sha256(text),
        "transactionId": parsed.get("transactionId"),
        "transactionShipments": shipment_summaries,
    }


def picking_summary(picking):
    carrier = value(picking, "carrier_id")
    sale = value(picking, "sale_id")
    package_ids = value(picking, "package_ids")
    moves = value(picking, "move_line_ids")
    request_text = value(picking, "fedex_rest_last_request", "")
    response_text = value(picking, "fedex_rest_last_response", "")
    attachments = env["ir.attachment"].search([
        ("res_model", "=", "stock.picking"),
        ("res_id", "=", picking.id),
    ], limit=LIMIT)
    messages = value(picking, "message_ids")
    return {
        "id": picking.id,
        "name": picking.name,
        "state": picking.state,
        "origin": value(picking, "origin"),
        "scheduled_date": str(value(picking, "scheduled_date")) if value(picking, "scheduled_date") else None,
        "date_done": str(value(picking, "date_done")) if value(picking, "date_done") else None,
        "carrier": one(carrier),
        "carrier_delivery_type": getattr(carrier, "delivery_type", None) if carrier else None,
        "carrier_tracking_ref": value(picking, "carrier_tracking_ref"),
        "carrier_tracking_url": value(picking, "carrier_tracking_url"),
        "sale_order": one(sale),
        "package_count": len(package_ids) if package_ids else 0,
        "move_line_count": len(moves) if moves else 0,
        "message_count": len(messages) if messages else 0,
        "attachment_count": len(attachments),
        "attachment_names": [attachment.name for attachment in attachments[:20]],
        "fedex_last_request": request_summary(request_text),
        "fedex_last_response": response_summary(response_text),
    }


print("READ-ONLY FedEx duplicate diagnosis")
print("Tracking consultat: %s" % (TRACKING or "(no especificat)"))
print("Picking consultat: %s" % (PICKING_NAME or "(no especificat)"))
print("No es fan crides HTTP a FedEx.")

picking_model = env["stock.picking"]
found = picking_model.browse()
if PICKING_NAME:
    found |= picking_model.search([("name", "=", PICKING_NAME)], limit=LIMIT)
if TRACKING and "carrier_tracking_ref" in field_names(picking_model):
    found |= picking_model.search([("carrier_tracking_ref", "=", TRACKING)], limit=LIMIT)

found = found.sorted(key=lambda record: (record.name or "", record.id))
print("Pickings coincidents: %s" % len(found))
for picking in found:
    print(json.dumps(picking_summary(picking), ensure_ascii=False, sort_keys=True, indent=2, default=str))

# Search chatter references too.  This helps distinguish one Odoo picking with
# two FedEx records from two Odoo pickings that share the number.
if TRACKING:
    attachment_model = env["ir.attachment"]
    tracking_attachments = attachment_model.search([("name", "ilike", TRACKING)], limit=LIMIT)
    print("Fitxers adjunts que contenen el tracking en el nom: %s" % len(tracking_attachments))
    for attachment in tracking_attachments:
        print(json.dumps({
            "id": attachment.id,
            "name": attachment.name,
            "res_model": attachment.res_model,
            "res_id": attachment.res_id,
            "create_date": str(attachment.create_date) if attachment.create_date else None,
        }, ensure_ascii=False, sort_keys=True, indent=2, default=str))

    message_model = env["mail.message"]
    chatter = message_model.search([("body", "ilike", TRACKING)], limit=LIMIT)
    print("Missatges que contenen el tracking: %s" % len(chatter))
    for message in chatter:
        print(json.dumps({
            "id": message.id,
            "date": str(message.date) if message.date else None,
            "model": message.model,
            "res_id": message.res_id,
            "subtype": one(message.subtype_id),
            "author": one(message.author_id),
        }, ensure_ascii=False, sort_keys=True, indent=2, default=str))

    # A second exact search catches pickings where the connector did not write
    # carrier_tracking_ref but the number appears in a carrier-related field.
    for field in ("carrier_tracking_url", "origin"):
        if field in field_names(picking_model):
            matches = picking_model.search([(field, "ilike", TRACKING)], limit=LIMIT)
            print("Pickings amb %s contenint el tracking: %s" % (field, len(matches)))
            for picking in matches:
                if picking not in found:
                    print(json.dumps(picking_summary(picking), ensure_ascii=False, sort_keys=True, indent=2, default=str))

try:
    env.cr.rollback()
    print("ROLLBACK realitzat. Només lectura; cap canvi a Odoo ni cap petició FedEx.")
except Exception as exc:
    print("No s'ha pogut fer rollback explícit: %s" % exc)
