# -*- coding: utf-8 -*-
import logging
import requests
import base64
import json
import hashlib
import uuid
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(selection_add=[('fedex_rest', 'FedEx REST')])

    fedex_rest_api_key = fields.Char("API Key")
    fedex_rest_secret_key = fields.Char("Secret Key")
    fedex_rest_account_number = fields.Char("Account Number")
    fedex_rest_image_signature_id = fields.Char("ID Imagen Firma", default="IMAGE_1")
    fedex_rest_image_logo_id = fields.Char("ID Imagen Logo", default="IMAGE_2")
    
    fedex_rest_service_type = fields.Selection([
        ('INTERNATIONAL_ECONOMY', 'INTERNATIONAL_ECONOMY'),
        ('INTERNATIONAL_PRIORITY', 'INTERNATIONAL_PRIORITY'),
        ('FEDEX_INTERNATIONAL_PRIORITY', 'FEDEX_INTERNATIONAL_PRIORITY'),
        ('FEDEX_GROUND', 'FEDEX_GROUND'),
        ('FEDEX_REGIONAL_ECONOMY', 'FEDEX_REGIONAL_ECONOMY'),
    ], string="Servicio Fedex", default='FEDEX_INTERNATIONAL_PRIORITY')

    fedex_rest_label_format = fields.Selection([('PDF', 'PDF'), ('ZPLII', 'ZPLII')], string="Formato Etiqueta", default='PDF')
    fedex_rest_label_stock_type = fields.Selection([
        ('STOCK_4X6', 'STOCK_4X6'),
        ('PAPER_8.5X11_TOP_HALF_LABEL', 'PAPER_8.5X11_TOP_HALF_LABEL')
    ], string="Tipo de Papel", default='STOCK_4X6')

    def _get_fedex_rest_token(self):
        url = "https://apis-sandbox.fedex.com/oauth/token" if not self.prod_environment else "https://apis.fedex.com/oauth/token"
        payload = {'grant_type': 'client_credentials', 'client_id': self.fedex_rest_api_key, 'client_secret': self.fedex_rest_secret_key}
        headers = {'Content-Type': "application/x-www-form-urlencoded"}
        response = requests.post(url, data=payload, headers=headers, timeout=(10, 30))
        if response.status_code == 200:
            return response.json().get('access_token')
        raise UserError(_("Error de autenticación FedEx"))

    def _fedex_lock_and_check_picking(self, picking):
        """Lock a picking and prevent a second shipment creation.

        FedEx shipment creation is an external side effect and the API call is
        not safely repeatable.  The row lock prevents two Odoo workers from
        creating a shipment concurrently.  ``sending`` is deliberately kept
        after an unknown request outcome, so a timeout/error cannot cause an
        automatic duplicate on the next validation.
        """
        self.env.cr.execute(
            "SELECT id FROM stock_picking WHERE id = %s FOR UPDATE",
            (picking.id,),
        )
        picking.invalidate_cache()

        if picking.carrier_tracking_ref:
            return {
                'exact_price': 0.0,
                'tracking_number': picking.carrier_tracking_ref,
            }

        if picking.fedex_rest_shipment_state in ('sending', 'sent'):
            raise UserError(_(
                "El picking %s ya tiene una expedición FedEx iniciada (%s). "
                "No se reenvía automáticamente; hay que revisar FedEx y "
                "guardar el tracking antes de repetir."
            ) % (picking.name, picking.fedex_rest_send_request_id or '-'))
        return False

    def _fedex_mark_sending(self, picking, payload):
        """Persist the in-flight marker before calling FedEx.

        The commit is intentional: if FedEx accepts the request and the Odoo
        transaction later times out, a retry must see ``sending`` instead of
        creating a second shipment.
        """
        request_id = str(uuid.uuid4())
        request_text = json.dumps(payload, indent=4, sort_keys=True)
        picking.write({
            'fedex_rest_last_request': request_text,
            'fedex_rest_last_response': False,
            'fedex_rest_shipment_state': 'sending',
            'fedex_rest_send_request_id': request_id,
            'fedex_rest_request_hash': hashlib.sha256(
                request_text.encode('utf-8')
            ).hexdigest(),
            'fedex_rest_last_error': False,
            'fedex_rest_shipment_created_at': False,
        })
        self.env.cr.commit()
        picking.invalidate_cache()
        return request_id

    def fedex_rest_send_shipping(self, pickings):
        res = []
        for picking in pickings:
            existing = self._fedex_lock_and_check_picking(picking)
            if existing:
                res.append(existing)
                continue

            token = self._get_fedex_rest_token()
            base_url = "https://apis-sandbox.fedex.com" if not self.prod_environment else "https://apis.fedex.com"
            is_international = picking.company_id.country_id != picking.partner_id.country_id
            
            # --- PREPARAR COMMODITIES (ARTÍCULOS) ---
            commodities = []
            total_weight = 0.0
            for line in picking.move_line_ids:
                if line.product_id:
                    # Si el producto no tiene precio, usamos 1.0 por defecto para evitar errores
                    unit_price = line.product_id.list_price or 1.0
                    weight = line.product_id.weight or 0.1
                    line_weight = round(weight * line.qty_done, 3)
                    total_weight += line_weight
                    
                    commodity = {
                        "description": line.product_id.name[:450], # Límite FedEx
                        "numberOfPieces": 1,
                        "weight": {"units": "KG", "value": line_weight},
                        "quantity": int(line.qty_done),
                        "quantityUnits": "PCS",
                        "unitPrice": {"amount": unit_price, "currency": picking.company_id.currency_id.name},
                        "customsValue": {"amount": unit_price * line.qty_done, "currency": picking.company_id.currency_id.name},
                        "countryOfManufacture": line.product_id.country_id.code if line.product_id.country_id else ""
                    }
                    # Añadir Código HS si existe en Odoo (campo hs_code)
                    if hasattr(line.product_id, 'hs_code') and line.product_id.hs_code:
                        commodity["harmonizedCode"] = line.product_id.hs_code
                    
                    commodities.append(commodity)

            # El peso del paquete debe ser >= suma de commodities
            package_weight = max(picking.shipping_weight or 0.0, total_weight) or 1.0
            number_of_packages = float(len(picking.package_ids))
            package_weight = package_weight / (number_of_packages or 1.0)

            # PACKAGES
            shipping_reference = picking.name
            packages = []
            for i, package in enumerate(picking.package_ids, start=1):
                packages.append({
                    "sequenceNumber": i,
                    "weight": {
                        "units": "KG",
                        "value": package_weight or 1
                    },
                    "customerReferences": [
                        {
                            "customerReferenceType": "CUSTOMER_REFERENCE",
                            "value": shipping_reference
                        }
                    ]
                })

            payload = {
                "labelResponseOptions": "LABEL",
                "mergeLabelDocOption": "LABELS_AND_DOCS",
                "requestedShipment": {
                    "shipper": {
                        "address": {
                            "streetLines": [picking.company_id.street or ""],
                            "city": picking.company_id.city or "",
                            "stateOrProvinceCode": picking.company_id.state_id.code or "",
                            "postalCode": picking.company_id.zip or "",
                            "countryCode": picking.company_id.country_id.code or ""
                        },
                        "contact": {"personName": picking.company_id.name, "phoneNumber": picking.company_id.phone or "0000000000"}
                    },
                    "recipients": [{
                        "address": {
                            "streetLines": [picking.partner_id.street or ""],
                            "city": picking.partner_id.city or "",
                            "stateOrProvinceCode": picking.partner_id.state_id.code or "",
                            "postalCode": picking.partner_id.zip or "",
                            "countryCode": picking.partner_id.country_id.code or ""
                        },
                        "contact": {"personName": picking.partner_id.name, "phoneNumber": picking.partner_id.phone or "0000000000"}
                    }],
                    "serviceType": self.fedex_rest_service_type,
                    "packagingType": "YOUR_PACKAGING",
                    "pickupType": "CONTACT_FEDEX_TO_SCHEDULE",
                    "shippingChargesPayment": {
                        "paymentType": "SENDER",
                        "payor": {"responsibleParty": {"accountNumber": {"value": self.fedex_rest_account_number}}}
                    },
                    "labelSpecification": {
                        "labelFormatType": "COMMON2D",
                        "imageType": self.fedex_rest_label_format,
                        "labelStockType": self.fedex_rest_label_stock_type
                    },
                    "totalPackageCount": len(packages),
                    "requestedPackageLineItems": packages,
                },
                "accountNumber": {"value": self.fedex_rest_account_number},
                "oneLabelAtATime": False,
                "processingOptionType": "SYNCHRONOUS_ONLY"
            }

            if is_international:
                payload['requestedShipment']['shipmentSpecialServices'] = {
                    "specialServiceTypes": ["ELECTRONIC_TRADE_DOCUMENTS"],
                    "etdDetail": {"requestedDocumentTypes": ["COMMERCIAL_INVOICE"]}
                }
                payload['requestedShipment']['shippingDocumentSpecification'] = {
                    "shippingDocumentTypes": ["COMMERCIAL_INVOICE"],
                    "commercialInvoiceDetail": {
                        "customerImageUsages": [
                            {"id": self.fedex_rest_image_signature_id, "type": "SIGNATURE", "providedImageType": "SIGNATURE"},
                            {"id": self.fedex_rest_image_logo_id, "type": "LETTER_HEAD", "providedImageType": "LETTER_HEAD"}
                        ],
                        "documentFormat": {"stockType": "PAPER_LETTER", "docType": "PDF"}
                    }
                }
                payload['requestedShipment']['customsClearanceDetail'] = {
                    "dutiesPayment": {
                        "paymentType": "SENDER",
                        "payor": {"responsibleParty": {"accountNumber": {"value": self.fedex_rest_account_number}}}
                    },
                    "commodities": commodities # <--- Aquí inyectamos la lista de artículos
                }

            request_id = self._fedex_mark_sending(picking, payload)
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                # FedEx uses this value to correlate the API transaction.  It
                # is not relied on as idempotency; the Odoo marker above is
                # the actual duplicate protection.
                'x-customer-transaction-id': request_id,
            }
            try:
                response = requests.post(
                    f"{base_url}/ship/v1/shipments",
                    json=payload,
                    headers=headers,
                    timeout=(10, 90),
                )
            except requests.exceptions.RequestException as exc:
                _logger.exception(
                    "FedEx request outcome unknown for picking %s (%s)",
                    picking.name,
                    request_id,
                )
                # Keep state='sending'.  The next attempt must be reviewed
                # manually rather than blindly creating another shipment.
                picking.write({'fedex_rest_last_error': str(exc)[:4000]})
                self.env.cr.commit()
                raise UserError(_(
                    "FedEx no ha confirmado l'expedició de %s. "
                    "No ho tornis a enviar automàticament; revisa el seguiment "
                    "amb la referència %s. Detall: %s"
                ) % (picking.name, request_id, exc))

            picking.write({'fedex_rest_last_response': response.text})
            
            if response.status_code == 200:
                data = response.json()
                ship_details = data.get('output', {}).get('transactionShipments', [{}])[0]
                tracking_number = ship_details.get('masterTrackingNumber')
                if not tracking_number:
                    raise UserError(_(
                        "FedEx ha respost 200 però sense número de seguiment "
                        "per %s. No es repeteix la petició automàticament."
                    ) % picking.name)

                piece_tracking_numbers = []
                for piece in ship_details.get('pieceResponses', []):
                    piece_tracking = piece.get('trackingNumber')
                    if piece_tracking and piece_tracking not in piece_tracking_numbers:
                        piece_tracking_numbers.append(piece_tracking)
                
                attachment_ids = []
                for piece in ship_details.get('pieceResponses', []):
                    for doc in piece.get('packageDocuments', []):
                        content = doc.get('encodedLabel')
                        if content:
                            d_type = doc.get('contentType', 'LABEL')
                            ext = 'pdf' if d_type == 'COMMERCIAL_INVOICE' else self.fedex_rest_label_format.lower()
                            new_attach = self.env['ir.attachment'].create({
                                'name': f"{d_type}_{tracking_number}.{ext}",
                                'datas': content,
                                'res_model': 'stock.picking',
                                'res_id': picking.id,
                                'type': 'binary'
                            })
                            attachment_ids.append(new_attach.id)

                if attachment_ids:
                    picking.message_post(body=_("Documentos FedEx generados."), attachment_ids=attachment_ids)

                transaction_id = (
                    data.get('transactionId') or
                    ship_details.get('transactionId') or
                    request_id
                )
                picking.write({
                    'carrier_tracking_ref': tracking_number,
                    'fedex_rest_shipment_state': 'sent',
                    'fedex_rest_transaction_id': transaction_id,
                    'fedex_rest_piece_tracking_numbers': json.dumps(piece_tracking_numbers),
                    'fedex_rest_shipment_created_at': fields.Datetime.now(),
                    'fedex_rest_last_error': False,
                })
                # Make the tracking and the in-flight marker durable before
                # Odoo returns control to the validation workflow.
                self.env.cr.commit()
                picking.invalidate_cache()
                
                res.append({'exact_price': 0.0, 'tracking_number': tracking_number})
            else:
                # A 5xx/429 can mean FedEx accepted the request but the
                # response was lost or throttled.  Keep it blocked.  Only a
                # deterministic client-side rejection is retryable.
                unknown_outcome = response.status_code >= 500 or response.status_code == 429
                picking.write({
                    'fedex_rest_shipment_state': 'sending' if unknown_outcome else 'error',
                    'fedex_rest_last_error': response.text[:4000],
                })
                self.env.cr.commit()
                if unknown_outcome:
                    raise UserError(_(
                        "FedEx ha respost %s i el resultat de l'expedició és "
                        "incert. No es repetirà automàticament; revisa FedEx "
                        "amb l'ID %s."
                    ) % (response.status_code, request_id))
                raise UserError(_("Fallo FedEx: %s") % response.text)
        return res

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_fedex_reset_shipment_guard(self):
        """Release an unknown-outcome guard after a human has checked FedEx.

        This is intentionally a manual operation: clearing ``sending`` without
        checking FedEx first would re-enable the duplicate shipment that this
        module is designed to prevent.
        """
        for picking in self:
            if picking.carrier_tracking_ref:
                raise UserError(_(
                    "No es pot desbloquejar %s perquè ja té el seguiment %s."
                ) % (picking.name, picking.carrier_tracking_ref))
            if picking.fedex_rest_shipment_state not in ('sending', 'error'):
                raise UserError(_(
                    "El picking %s no té cap bloqueig FedEx per desbloquejar."
                ) % picking.name)
            old_request_id = picking.fedex_rest_send_request_id or '-'
            picking.write({'fedex_rest_shipment_state': False})
            picking.message_post(body=_(
                "Bloqueig FedEx desbloquejat manualment després de revisar "
                "que no hi havia cap expedició creada. Petició anterior: %s."
            ) % old_request_id)
        return True

    fedex_rest_last_request = fields.Text("FedEx Request", copy=False, readonly=True)
    fedex_rest_last_response = fields.Text("FedEx Response", copy=False, readonly=True)
    fedex_rest_shipment_state = fields.Selection([
        ('sending', 'Enviando a FedEx'),
        ('sent', 'Creada en FedEx'),
        ('error', 'Error de FedEx'),
    ], string="Estado expedición FedEx", copy=False, readonly=True)
    fedex_rest_send_request_id = fields.Char(
        "ID petición FedEx", copy=False, readonly=True)
    fedex_rest_transaction_id = fields.Char(
        "ID transacción FedEx", copy=False, readonly=True)
    fedex_rest_request_hash = fields.Char(
        "Hash petición FedEx", copy=False, readonly=True)
    fedex_rest_piece_tracking_numbers = fields.Text(
        "Seguimientos de bultos FedEx", copy=False, readonly=True)
    fedex_rest_shipment_created_at = fields.Datetime(
        "Creada en FedEx el", copy=False, readonly=True)
    fedex_rest_last_error = fields.Text(
        "Último error FedEx", copy=False, readonly=True)
