# -*- coding: utf-8 -*-
"""Devolucions per FedEx (API REST), reaprofitant el transportista de delivery_fedex_rest2.

Replica el que fa la Lorena a la web de FedEx:
- Enviament "d'importació": remitent = client, destinatari = magatzem, tot a càrrec del nostre compte.
- Servei del transportista (FEDEX_REGIONAL_ECONOMY), 1 paquet, pes/mides per defecte, "Children's Clothing".
- Referència = TT/DEV, núm. ordre de compra = remarks.
- França: recollida a domicili l'endemà (finestra horària). Resta: el client el porta a un punt FedEx.
"""
import datetime
import json
import logging
import textwrap

import requests

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

EU_COUNTRIES = {'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR', 'HU', 'IE', 'IT',
                'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE'}


def _lines(text, size=35, max_lines=3):
    """FedEx accepta línies d'adreça de 35 caràcters com a màxim: talla per paraules."""
    out = textwrap.wrap((text or '').strip(), size)[:max_lines]
    return out or ['.']


def next_business_day(today=None):
    d = (today or datetime.date.today()) + datetime.timedelta(days=1)
    while d.weekday() >= 5:      # dissabte / diumenge
        d += datetime.timedelta(days=1)
    return d


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    def _fedex_base_url(self):
        return 'https://apis.fedex.com' if self.prod_environment else 'https://apis-sandbox.fedex.com'

    # ------------------------------------------------------------------
    def fedex_return_payload(self, log, pickup):
        self.ensure_one()
        config = log.config_id
        dest = config.dest_partner_id
        acct = {'value': self.fedex_rest_account_number}
        ship_date = next_business_day()
        qty = int(sum(log.line_ids.filtered(lambda l: not l.ignore).mapped('quantity'))) or 1
        value = round(log.amount_expected or 1.0, 2)
        currency = log.currency_code or 'EUR'
        payload = {
            'labelResponseOptions': 'LABEL',
            'accountNumber': acct,
            'requestedShipment': {
                'shipDatestamp': ship_date.isoformat(),
                'shipper': {   # el client (enviament d'importació)
                    'contact': {'personName': (log.partner_name or '.')[:70],
                                'phoneNumber': (log.phone or '0000000000')[:15],
                                'emailAddress': log.email or ''},
                    'address': {'streetLines': _lines(log.street),
                                'city': log.city or '',
                                'postalCode': log.zip or '',
                                'countryCode': log.country_code or ''},
                },
                'recipients': [{   # el nostre magatzem
                    'contact': {'personName': (dest.name or '.')[:70],
                                'companyName': (dest.commercial_company_name or dest.name or '')[:35],
                                'phoneNumber': (dest.phone or '0000000000')[:15]},
                    'address': {'streetLines': _lines(' '.join(filter(None, [dest.street, dest.street2]))),
                                'city': dest.city or '',
                                'postalCode': dest.zip or '',
                                'countryCode': dest.country_id.code or 'ES'},
                }],
                'serviceType': self.fedex_rest_service_type or 'FEDEX_REGIONAL_ECONOMY',
                'packagingType': 'YOUR_PACKAGING',
                'pickupType': 'CONTACT_FEDEX_TO_SCHEDULE' if pickup else 'DROPOFF_AT_FEDEX_LOCATION',
                # "Facturar a: Mi cuenta" (transport i aranzels)
                'shippingChargesPayment': {
                    'paymentType': 'RECIPIENT',
                    'payor': {'responsibleParty': {'accountNumber': acct}},
                },
                'customsClearanceDetail': {
                    'dutiesPayment': {
                        'paymentType': 'RECIPIENT',
                        'payor': {'responsibleParty': {'accountNumber': acct}},
                    },
                    'commodities': [{
                        'description': config.fedex_description or "Children's Clothing",
                        'countryOfManufacture': 'ES',
                        'numberOfPieces': 1,
                        'quantity': qty,
                        'quantityUnits': 'PCS',
                        'weight': {'units': 'KG', 'value': config.fedex_weight or 1.0},
                        'unitPrice': {'amount': round(value / qty, 2), 'currency': currency},
                        'customsValue': {'amount': value, 'currency': currency},
                    }],
                },
                # "Adjuntar documentos comerciales electrónicamente"
                'shipmentSpecialServices': {
                    'specialServiceTypes': ['ELECTRONIC_TRADE_DOCUMENTS'],
                    'etdDetail': {'requestedDocumentTypes': ['COMMERCIAL_INVOICE']},
                },
                # "Quiero que FedEx me ayude a crear una factura comercial", amb el membret i la
                # signatura guardats al compte de FedEx (sense: SHIPMENT.ELECTRONICIMAGE.REQUIRED)
                'shippingDocumentSpecification': {
                    'shippingDocumentTypes': ['COMMERCIAL_INVOICE'],
                    'commercialInvoiceDetail': {
                        'customerImageUsages': [
                            {'id': self.fedex_rest_image_signature_id or 'IMAGE_1',
                             'type': 'SIGNATURE', 'providedImageType': 'SIGNATURE'},
                            {'id': self.fedex_rest_image_logo_id or 'IMAGE_2',
                             'type': 'LETTER_HEAD', 'providedImageType': 'LETTER_HEAD'},
                        ],
                        'documentFormat': {'stockType': 'PAPER_LETTER', 'docType': 'PDF'},
                    },
                },
                'labelSpecification': {
                    'labelFormatType': 'COMMON2D',
                    'imageType': 'PDF',
                    'labelStockType': self.fedex_rest_label_stock_type or 'STOCK_4X6',
                },
                'requestedPackageLineItems': [{
                    'weight': {'units': 'KG', 'value': config.fedex_weight or 1.0},
                    'dimensions': {'length': int(config.fedex_length or 20), 'width': int(config.fedex_width or 20),
                                   'height': int(config.fedex_height or 10), 'units': 'CM'},
                    'customerReferences': [
                        {'customerReferenceType': 'CUSTOMER_REFERENCE', 'value': (log.dev_picking_id.name or '')[:30]},
                        {'customerReferenceType': 'P_O_NUMBER', 'value': (log.remarks or '')[:30]},
                    ],
                }],
            },
        }
        if config.fedex_eu_no_customs and (log.country_code or '').upper() in EU_COUNTRIES:
            # Dins la UE no hi ha duanes: sense factura comercial ni ETD (FedEx demana una imatge de signatura)
            rs = payload['requestedShipment']
            rs.pop('shipmentSpecialServices', None)
            rs.pop('shippingDocumentSpecification', None)
        return payload

    def fedex_return_pickup_payload(self, log, tracking):
        self.ensure_one()
        config = log.config_id
        day = next_business_day()
        return {
            'associatedAccountNumber': {'value': self.fedex_rest_account_number},
            'originDetail': {
                'pickupLocation': {
                    'contact': {'personName': (log.partner_name or '.')[:70],
                                'phoneNumber': (log.phone or '0000000000')[:15]},
                    'address': {'streetLines': _lines(log.street), 'city': log.city or '',
                                'postalCode': log.zip or '', 'countryCode': log.country_code or ''},
                },
                'readyDateTimestamp': '%sT%s:00' % (day.isoformat(), config.fedex_pickup_from or '12:00'),
                'customerCloseTime': '%s:00' % (config.fedex_pickup_to or '18:00'),
                'pickupDateType': 'FUTURE_DAY',
            },
            'carrierCode': 'FDXE',
            'packageCount': 1,
            'totalWeight': {'units': 'KG', 'value': config.fedex_weight or 1.0},
            'trackingNumber': tracking or '',
            'countryRelationships': 'INTERNATIONAL',
        }

    # ------------------------------------------------------------------
    def _fedex_post(self, path, payload):
        token = self._get_fedex_rest_token()
        headers = {'Authorization': 'Bearer %s' % token, 'Content-Type': 'application/json'}
        try:
            resp = requests.post(self._fedex_base_url() + path, json=payload, headers=headers, timeout=60)
        except requests.RequestException as e:
            raise Exception('FedEx %s: error de conexión: %s' % (path, e))
        _logger.info('FedEx %s -> %s %s', path, resp.status_code, resp.text[:500])
        if resp.status_code not in (200, 201):
            # Errors de negoci de FedEx -> revisió manual amb el missatge
            raise UserError(_('FedEx %s: %s') % (path, resp.text[:800]))
        return resp.json()

    def fedex_has_dropoff_location(self, log, radius_km=20):
        """Hi ha algun punt FedEx a prop del client? (API Locations Search)
        :return: (True/False/None, text del punt més proper). None = no s'ha pogut saber."""
        self.ensure_one()
        payload = {
            'location': {'address': {'streetLines': _lines(log.street)[:1], 'city': log.city or '',
                                     'postalCode': log.zip or '', 'countryCode': log.country_code or ''}},
            'locationsSummaryRequestControlParameters': {'distance': {'units': 'KM', 'value': radius_km}},
            'multipleMatchesAction': 'RETURN_ALL',
        }
        try:
            data = self._fedex_post('/location/v1/locations', payload)
        except Exception as e:
            _logger.info('FedEx locations %s: %s', log.remarks, e)
            return None, ''
        points = (data.get('output') or {}).get('locationDetailList') or []
        if not points:
            return False, ''
        p = points[0]
        contact = (p.get('contactAndAddress') or {})
        addr = contact.get('address') or {}
        name = (contact.get('contact') or {}).get('companyName') or p.get('locationId') or ''
        dist = (p.get('distance') or {}).get('value')
        text = '%s, %s, %s %s%s' % (name, ' '.join(addr.get('streetLines') or []), addr.get('postalCode') or '',
                                     addr.get('city') or '', (' (%.1f km)' % dist) if dist else '')
        return True, text

    def fedex_return_create(self, log, pickup):
        """:return: (tracking, label_base64)"""
        self.ensure_one()
        data = self._fedex_post('/ship/v1/shipments', self.fedex_return_payload(log, pickup))
        ship = (data.get('output', {}).get('transactionShipments') or [{}])[0]
        tracking = ship.get('masterTrackingNumber')
        label = False
        for piece in ship.get('pieceResponses', []):
            for doc in piece.get('packageDocuments', []):
                if doc.get('encodedLabel') and not label:
                    label = doc['encodedLabel']
        if not tracking:
            raise UserError(_('FedEx no ha devuelto número de seguimiento: %s') % json.dumps(data)[:800])
        return tracking, label

    def fedex_return_pickup(self, log, tracking):
        self.ensure_one()
        data = self._fedex_post('/pickup/v1/pickups', self.fedex_return_pickup_payload(log, tracking))
        return (data.get('output') or {}).get('pickupConfirmationCode') or ''

    # ------------------------------------------------------------------
    # Seguiment i cancel·lació
    # ------------------------------------------------------------------
    def fedex_return_cancel(self, tracking):
        """Cancel·la l'enviament (si el client cancel·la la devolució a Shopify)."""
        self.ensure_one()
        token = self._get_fedex_rest_token()
        headers = {'Authorization': 'Bearer %s' % token, 'Content-Type': 'application/json'}
        payload = {'accountNumber': {'value': self.fedex_rest_account_number},
                   'deletionControl': 'DELETE_ALL_PACKAGES', 'trackingNumber': tracking}
        resp = requests.put(self._fedex_base_url() + '/ship/v1/shipments/cancel',
                            json=payload, headers=headers, timeout=60)
        _logger.info('FedEx cancel %s -> %s %s', tracking, resp.status_code, resp.text[:300])
        if resp.status_code not in (200, 201):
            raise UserError(_('FedEx cancel: %s') % resp.text[:500])
        return True

    def fedex_get_status(self, tracking):
        """Estat de l'enviament (API Track).
        :return: (text de l'estat, entregat True/False)"""
        self.ensure_one()
        data = self._fedex_post('/track/v1/trackingnumbers', {
            'includeDetailedScans': False,
            'trackingInfo': [{'trackingNumberInfo': {'trackingNumber': tracking}}],
        })
        results = ((data.get('output') or {}).get('completeTrackResults') or [{}])[0].get('trackResults') or [{}]
        latest = results[0].get('latestStatusDetail') or {}
        desc = latest.get('description') or latest.get('statusByLocale') or ''
        loc = latest.get('scanLocation') or {}
        where = ', '.join(filter(None, [loc.get('city'), loc.get('countryCode')]))
        status = desc + ((' (%s)' % where) if where else '')
        return status[:250], latest.get('code') == 'DL'
