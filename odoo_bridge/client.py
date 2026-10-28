"""Client JSON-RPC pour Odoo 17, sans opération d'écriture."""

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from .catalog import catalog, safe_field


class ConfigurationError(Exception):
    pass


class OdooError(Exception):
    pass


class QueryError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    url: str
    database: str
    login: str
    api_key: str = field(repr=False)

    @classmethod
    def from_environment(cls):
        values = [os.environ.get(name, "").strip() for name in
                  ("ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY")]
        if not all(values):
            raise ConfigurationError("Configuration Odoo incomplète")
        url = urlsplit(values[0])
        if (url.scheme != "https" or not url.hostname or url.username or
                url.password or url.query or url.fragment or url.path not in ("", "/")):
            raise ConfigurationError("ODOO_URL doit être une origine HTTPS")
        return cls(values[0].rstrip("/"), *values[1:])


INVOICE_FIELDS = [
    "id", "name", "move_type", "partner_id", "invoice_date", "invoice_date_due",
    "state", "payment_state", "amount_total", "amount_residual", "currency_id",
]


class OdooClient:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.transport = transport

    async def _rpc(self, client, service, method, args):
        try:
            response = await client.post(self.settings.url + "/jsonrpc", json={
                "jsonrpc": "2.0", "method": "call", "id": 1,
                "params": {"service": service, "method": method, "args": args},
            })
            response.raise_for_status()
            payload = response.json()
            if (not isinstance(payload, dict) or payload.get("error") or
                    "result" not in payload):
                raise OdooError("Réponse Odoo invalide")
            return payload["result"]
        except (httpx.HTTPError, ValueError) as exc:
            # Ne pas renvoyer les traces Odoo ni les paramètres d'authentification.
            raise OdooError("Communication avec Odoo impossible") from exc

    async def invoices(self, *, limit=20, offset=0, invoice_id=None):
        domain = [["move_type", "in", ["out_invoice", "out_refund"]]]
        if invoice_id is not None:
            domain.append(["id", "=", invoice_id])
        result = await self._execute("account.move", "search_read", [domain],
                                     {"fields": INVOICE_FIELDS, "limit": limit,
                                      "offset": offset, "order": "id desc"})
        return self._rows(result, INVOICE_FIELDS)

    async def _execute(self, model, method, args, kwargs):
        if model not in catalog() or method not in {"fields_get", "search_read"}:
            raise QueryError("Modèle ou méthode non autorisé")
        async with httpx.AsyncClient(timeout=20, follow_redirects=False,
                                     transport=self.transport) as client:
            cfg = self.settings
            uid = await self._rpc(client, "common", "authenticate",
                                  [cfg.database, cfg.login, cfg.api_key, {}])
            if type(uid) is not int or uid <= 0:
                raise OdooError("Authentification Odoo refusée")
            return await self._rpc(client, "object", "execute_kw", [
                cfg.database, uid, cfg.api_key, model, method, args, kwargs,
            ])

    @staticmethod
    def _rows(result, fields):
        if not isinstance(result, list) or not all(isinstance(r, dict) for r in result):
            raise OdooError("Format de données Odoo invalide")
        return [{k: row[k] for k in fields if k in row} for row in result]

    async def fields(self, model):
        result = await self._execute(model, "fields_get", [],
                                     {"attributes": ["string", "type", "relation", "selection"]})
        if not isinstance(result, dict):
            raise OdooError("Format des champs Odoo invalide")
        return {name: {k: data[k] for k in ("string", "type", "relation", "selection") if k in data}
                for name, data in result.items() if safe_field(name) and isinstance(data, dict)
                and data.get("type") not in {"binary", "html"}}

    async def records(self, model, fields, domain, limit, offset):
        available = await self.fields(model)
        # Ne jamais laisser fields absent : Odoo lirait alors tous les champs.
        selected = fields or [name for name in ("id", "display_name") if name in available]
        if not selected or any(name not in available for name in selected):
            raise QueryError("Champ absent, inaccessible ou non autorisé ; consulter les champs du modèle")
        if any(term[0] not in available for term in domain):
            raise QueryError("Champ de filtre absent, inaccessible ou non autorisé")
        result = await self._execute(model, "search_read", [domain],
                                     {"fields": selected, "limit": limit,
                                      "offset": offset, "order": "id desc"})
        return self._rows(result, selected)
