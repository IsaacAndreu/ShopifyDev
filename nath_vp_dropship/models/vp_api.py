# -*- coding: utf-8 -*-
"""Client de l'API de dropshipment.veepee.com (la mateixa que fa servir VentePriveeSync.exe).

  POST  /api/v{v}/auth/login                         -> access_token
  GET   /api/v{v}/operations                         -> campanyes
  GET   /api/v{v}/operations/{op}/batches            -> batches de la campanya
  GET   /api/v{v}/operations/{op}/batches/{batch}    -> deliveryOrders
  PATCH /api/v{v}/operations/{op}/batches/{batch}/close
"""
import logging

import requests

_logger = logging.getLogger(__name__)
TIMEOUT = 60


class VeepeeApiError(Exception):
    pass


class VeepeeApi(object):

    def __init__(self, base_url, version, user, password):
        self.base = (base_url or '').rstrip('/')
        self.version = version or '3'
        self.user = user
        self.password = password
        self.token = None

    def _url(self, path):
        return '%s/api/v%s/%s' % (self.base, self.version, path.lstrip('/'))

    def _call(self, method, path, **kw):
        headers = {'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer %s' % self.token
        try:
            r = requests.request(method, self._url(path), headers=headers, timeout=TIMEOUT, **kw)
        except requests.RequestException as e:
            raise VeepeeApiError('Sin conexión con Veepee (%s): %s' % (path, e))
        if r.status_code >= 400:
            raise VeepeeApiError('Veepee %s %s -> HTTP %s: %s' % (method, path, r.status_code, r.text[:300]))
        if not r.text:
            return {}
        try:
            return r.json()
        except ValueError:
            raise VeepeeApiError('Respuesta no JSON de Veepee (%s): %s' % (path, r.text[:300]))

    def login(self):
        if not (self.user and self.password):
            raise VeepeeApiError('Faltan el usuario o la contraseña de la API en la configuración.')
        data = self._call('POST', 'auth/login', json={'userName': self.user, 'password': self.password})
        self.token = data.get('access_token') or data.get('accessToken') or data.get('token')
        if not self.token:
            raise VeepeeApiError('Login de Veepee sin access_token.')
        return True

    @staticmethod
    def _items(data, *keys):
        if isinstance(data, list):
            return data
        for k in keys:
            if isinstance(data.get(k), list):
                return data[k]
        return []

    def operations(self):
        return self._items(self._call('GET', 'operations'), 'operations', 'items', 'data')

    def batches(self, operation_id):
        return self._items(self._call('GET', 'operations/%s/batches' % operation_id), 'batches', 'items', 'data')

    def batch(self, operation_id, batch_id):
        return self._call('GET', 'operations/%s/batches/%s' % (operation_id, batch_id))

    def close_batch(self, operation_id, batch_id):
        return self._call('PATCH', 'operations/%s/batches/%s/close' % (operation_id, batch_id))
