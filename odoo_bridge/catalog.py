"""Catalogue métier explicite ; les modèles techniques ne sont pas exposés."""

import json
import os
import re

MODELS = {
    "res.partner": "Clients, contacts et fournisseurs",
    "sale.order": "Devis et commandes clients",
    "sale.order.line": "Lignes de devis et commandes clients",
    "account.move": "Factures, avoirs et pièces comptables",
    "account.move.line": "Lignes de factures et écritures comptables",
    "account.payment": "Paiements",
    "account.bank.statement.line": "Lignes de relevés bancaires",
    "purchase.order": "Demandes de prix et commandes fournisseurs",
    "purchase.order.line": "Lignes de commandes fournisseurs",
    "product.template": "Fiches produits",
    "product.product": "Variantes de produits",
    "product.pricelist": "Listes de prix",
    "stock.quant": "Stocks par emplacement",
    "stock.picking": "Livraisons et réceptions",
    "stock.move": "Mouvements de stock",
    "stock.location": "Emplacements de stock",
    "crm.lead": "Pistes et opportunités CRM",
    "project.project": "Projets",
    "project.task": "Tâches",
    "account.analytic.line": "Lignes analytiques et feuilles de temps",
    "mrp.production": "Ordres de fabrication",
    "helpdesk.ticket": "Tickets d'assistance",
    "res.company": "Sociétés",
    "res.currency": "Devises",
}


def catalog():
    result = dict(MODELS)
    for model in os.environ.get("ODOO_EXTRA_READ_MODELS", "").split(","):
        model = model.strip()
        if (re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+", model)
                and not model.startswith(("ir.", "res.users", "auth.", "base."))):
            result.setdefault(model, "Module métier supplémentaire")
    return result


def safe_field(name):
    return (isinstance(name, str) and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*", name)
            and not any(part in name.lower() for part in
                        ("password", "passwd", "token", "secret", "api_key", "apikey")))


def parse_domain(raw):
    """Seulement une liste JSON de critères ET ; jamais d'expression Python."""
    try:
        domain = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("Le filtre doit être une liste JSON") from None
    if not isinstance(domain, list) or len(domain) > 20:
        raise ValueError("Maximum 20 critères de recherche")
    operators = {"=", "!=", ">", ">=", "<", "<=", "in", "not in", "ilike", "not ilike"}
    for term in domain:
        if (not isinstance(term, list) or len(term) != 3 or not safe_field(term[0])
                or not isinstance(term[1], str) or term[1] not in operators):
            raise ValueError("Chaque critère doit être [champ, opérateur, valeur]")
        value = term[2]
        if term[1] in {"in", "not in"}:
            if (not isinstance(value, list) or len(value) > 100
                    or any(not isinstance(v, (str, int, float, bool, type(None))) for v in value)):
                raise ValueError("Les opérateurs in/not in exigent une liste de 100 valeurs maximum")
        elif not isinstance(value, (str, int, float, bool, type(None))):
            raise ValueError("Valeur de filtre invalide")
    return domain
