import os
import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Path, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .client import ConfigurationError, OdooClient, OdooError, QueryError, Settings
from .catalog import catalog, parse_domain, safe_field


def public_servers():
    url = (os.environ.get("CONNECTOR_PUBLIC_URL") or
           os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")
    if not url:
        return []
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.path):
        raise ValueError("L'adresse publique du connecteur doit être une origine HTTPS")
    return [{"url": url}]


app = FastAPI(
    title="Odoo en lecture seule", version="0.2.0",
    description="Consultation des clients, devis, commandes, factures et autres modules métier. Aucune écriture.",
    servers=public_servers(),
)
bearer = HTTPBearer(auto_error=False)


def authorize(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    expected = os.environ.get("CONNECTOR_API_KEY", "")
    if len(expected) < 32:
        raise HTTPException(503, "Clé du connecteur absente ou trop courte")
    if (credentials is None or credentials.scheme.lower() != "bearer" or
            not secrets.compare_digest(credentials.credentials.encode(), expected.encode())):
        raise HTTPException(401, "Authentification requise", headers={"WWW-Authenticate": "Bearer"})


def get_odoo():
    try:
        return OdooClient(Settings.from_environment())
    except ConfigurationError:
        raise HTTPException(503, "Configuration Odoo incomplète ou invalide") from None


@app.get("/health", include_in_schema=False)
def health():
    """Vie du processus uniquement ; ne prouve pas l'accès à Odoo."""
    return {"status": "ok"}


@app.get("/models", operation_id="listBusinessModels", dependencies=[Depends(authorize)])
def models():
    """Catalogue des modèles autorisés. Leur installation et leurs droits ne sont pas encore vérifiés.

    Devis et commandes partagent sale.order : state=draft/sent pour les devis,
    state=sale/done pour les commandes. res.partner contient clients ET fournisseurs.
    """
    return {"models": [{"model": model, "description": label} for model, label in catalog().items()]}


@app.get("/models/{model}/fields", operation_id="getBusinessModelFields", dependencies=[Depends(authorize)])
async def model_fields(model: str, odoo: Annotated[OdooClient, Depends(get_odoo)]):
    """Champs consultables d'un modèle ; les relations donnent le modèle cible.

    Une erreur peut indiquer un module absent ou des droits insuffisants.
    Les champs binaires, HTML et noms évoquant des secrets sont exclus.
    """
    try:
        return {"model": model, "fields": await odoo.fields(model)}
    except QueryError as exc:
        raise HTTPException(422, str(exc)) from None
    except OdooError:
        raise HTTPException(502, "Champs Odoo indisponibles ; vérifier le module et les droits") from None


@app.get("/records/{model}", operation_id="searchBusinessRecords", dependencies=[Depends(authorize)])
async def records(
    model: str,
    odoo: Annotated[OdooClient, Depends(get_odoo)],
    fields: Annotated[str, Query(max_length=2000, description="Champs séparés par des virgules ; consulter /models/{model}/fields.")] = "",
    domain: Annotated[str, Query(max_length=8000, description='Critères JSON combinés par ET, par exemple [["name","ilike","Dupont"]]. Pas de code Python.')] = "[]",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Recherche paginée en lecture seule, dans les droits de l'utilisateur Odoo.

    Utiliser les identifiants relationnels pour consulter clients, lignes de
    commandes et factures liées. Une page ne représente pas la totalité des données.
    Par défaut, seuls id et display_name sont lus. Aucune agrégation implicite.
    """
    try:
        selected = [name.strip() for name in fields.split(",")] if fields else []
        if len(selected) > 40 or any(not safe_field(name) for name in selected):
            raise ValueError("Maximum 40 champs valides, sans champ de secret")
        criteria = parse_domain(domain)
        result = await odoo.records(model, selected, criteria, limit, offset)
        return {"model": model, "items": result, "limit": limit, "offset": offset}
    except (ValueError, QueryError) as exc:
        raise HTTPException(422, str(exc)) from None
    except OdooError:
        raise HTTPException(502, "Lecture Odoo impossible ; vérifier le module et les droits") from None


@app.get("/invoices", operation_id="listCustomerInvoices", dependencies=[Depends(authorize)])
async def invoices(
    odoo: Annotated[OdooClient, Depends(get_odoo)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Liste paginée de factures clients et avoirs accessibles à l'utilisateur Odoo.

    payment_state et amount_residual indiquent le statut de paiement, sans
    donner accès aux transactions bancaires. Ne pas additionner des devises distinctes.
    """
    try:
        return {"items": await odoo.invoices(limit=limit, offset=offset),
                "limit": limit, "offset": offset}
    except OdooError:
        raise HTTPException(502, "Lecture Odoo impossible ; vérifier l'accès et les droits") from None


@app.get("/invoices/{invoice_id}", operation_id="getCustomerInvoice", dependencies=[Depends(authorize)])
async def invoice(
    invoice_id: Annotated[int, Path(gt=0)],
    odoo: Annotated[OdooClient, Depends(get_odoo)],
):
    """Lit une facture client ou un avoir par identifiant Odoo."""
    try:
        rows = await odoo.invoices(limit=1, invoice_id=invoice_id)
    except OdooError:
        raise HTTPException(502, "Lecture Odoo impossible ; vérifier l'accès et les droits") from None
    if not rows:
        raise HTTPException(404, "Facture introuvable ou non accessible")
    return rows[0]
