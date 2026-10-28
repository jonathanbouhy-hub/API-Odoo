import json

import httpx
import pytest
from fastapi.testclient import TestClient

from odoo_bridge.app import app, get_odoo, public_servers
from odoo_bridge.client import OdooClient, Settings

TOKEN = "test-only-connector-token-32-characters"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_KEY", TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as instance:
        yield instance
    app.dependency_overrides.clear()


def backend():
    calls = []
    def respond(request):
        params = json.loads(request.content)["params"]
        if params["service"] == "common":
            return httpx.Response(200, json={"result": 7})
        args = params["args"]
        calls.append(args)
        assert args[4] in {"fields_get", "search_read"}
        if args[4] == "fields_get":
            result = {name: {"string": name, "type": "char"} for name in
                      ("id", "display_name", "name", "state", "partner_id", "api_key", "password")}
            result["image"] = {"type": "binary"}
            result["html"] = {"type": "html"}
        else:
            result = [{"id": 3, "display_name": "Example", "name": "Example", "api_key": "hidden"}]
        return httpx.Response(200, json={"result": result})
    app.dependency_overrides[get_odoo] = lambda: OdooClient(
        Settings("https://odoo.example", "db", "reader", "test-key"),
        transport=httpx.MockTransport(respond))
    return calls


def test_catalog_includes_requested_business_objects(client):
    result = client.get("/models")
    assert result.status_code == 200
    models = {entry["model"] for entry in result.json()["models"]}
    assert {"res.partner", "sale.order", "sale.order.line", "account.move"} <= models
    assert "res.users" not in models


@pytest.mark.parametrize("model", ["res.partner", "sale.order", "account.move", "product.product", "stock.quant"])
def test_searches_business_objects_with_fixed_read_method(client, model):
    calls = backend()
    response = client.get("/records/" + model, params={"fields": "id,name", "limit": 5})
    assert response.status_code == 200
    assert response.json()["items"] == [{"id": 3, "name": "Example"}]
    assert calls[-1][3:5] == [model, "search_read"]
    assert calls[-1][6]["fields"] == ["id", "name"]
    assert calls[-1][6]["limit"] == 5


def test_quote_filter_and_pagination_reach_odoo(client):
    calls = backend()
    domain = [["state", "in", ["draft", "sent"]], ["partner_id", "=", 42]]
    result = client.get("/records/sale.order", params={"domain": json.dumps(domain), "offset": 20})
    assert result.status_code == 200
    assert calls[-1][5] == [domain]
    assert calls[-1][6]["offset"] == 20
    assert calls[-1][6]["fields"] == ["id", "display_name"]


def test_metadata_excludes_secrets_binary_and_html(client):
    backend()
    response = client.get("/models/res.partner/fields")
    assert response.status_code == 200
    assert set(response.json()["fields"]) == {"id", "display_name", "name", "state", "partner_id"}


@pytest.mark.parametrize("params", [
    {"fields": "password"}, {"fields": "api_key"}, {"fields": "unknown_field"},
    {"fields": "partner_id.name"}, {"domain": "__import__('os')"},
    {"domain": '[["state","write","sale"]]'},
    {"domain": '[["password","=","guess"]]'},
    {"domain": '[["name","in","wrong-type"]]'},
    {"domain": '[["unknown_field","=",1]]'},
    {"limit": 101}, {"offset": -1},
])
def test_invalid_or_sensitive_queries_never_search_records(client, params):
    calls = backend()
    assert client.get("/records/res.partner", params=params).status_code == 422
    assert all(call[4] != "search_read" for call in calls)


@pytest.mark.parametrize("model", ["res.users", "ir.config_parameter", "unknown.model"])
def test_unregistered_and_technical_models_never_reach_odoo(client, model):
    calls = backend()
    assert client.get("/records/" + model).status_code == 422
    assert not calls


def test_custom_business_models_can_be_registered_but_not_technical_models(client, monkeypatch):
    monkeypatch.setenv("ODOO_EXTRA_READ_MODELS", "x.custom_module,ir.config_parameter,res.users")
    models = {m["model"] for m in client.get("/models").json()["models"]}
    assert "x.custom_module" in models
    assert "ir.config_parameter" not in models and "res.users" not in models
    backend()
    assert client.get("/records/x.custom_module").status_code == 200


def test_every_business_endpoint_requires_authentication(client):
    for path in ("/models", "/models/res.partner/fields", "/records/res.partner"):
        assert client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_render_public_url_is_used_for_actions_schema(monkeypatch):
    monkeypatch.delenv("CONNECTOR_PUBLIC_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://example.onrender.com/")
    assert public_servers() == [{"url": "https://example.onrender.com"}]
    monkeypatch.setenv("CONNECTOR_PUBLIC_URL", "https://connector.example.com")
    assert public_servers() == [{"url": "https://connector.example.com"}]


@pytest.mark.parametrize("url", ["http://example.com", "https://user:key@example.com", "https://example.com/?key=secret"])
def test_public_url_does_not_expose_embedded_secrets(monkeypatch, url):
    monkeypatch.setenv("CONNECTOR_PUBLIC_URL", url)
    with pytest.raises(ValueError):
        public_servers()
