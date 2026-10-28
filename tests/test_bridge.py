import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from odoo_bridge.app import app, get_odoo
from odoo_bridge.client import ConfigurationError, OdooClient, OdooError, Settings

TOKEN = "test-only-connector-token-32-characters"
CFG = Settings("https://odoo.example", "test_db", "reader", "test-only-odoo-key")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_KEY", TOKEN)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def mock_odoo(result):
    calls = []

    def respond(request):
        assert str(request.url) == "https://odoo.example/jsonrpc"
        body = json.loads(request.content)
        calls.append(body["params"])
        value = 7 if len(calls) == 1 else result
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": value})

    return OdooClient(CFG, transport=httpx.MockTransport(respond)), calls


def test_invoice_list_reads_only_allowed_fields_and_model(client):
    odoo, calls = mock_odoo([{"id": 42, "name": "INV/42", "amount_residual": 12,
                              "currency_id": [1, "EUR"], "unexpected_secret": "hidden"}])
    app.dependency_overrides[get_odoo] = lambda: odoo
    response = client.get("/invoices?limit=5&offset=10", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "INV/42"
    assert "unexpected_secret" not in response.text
    assert calls[0]["service"] == "common"
    assert calls[0]["method"] == "authenticate"
    assert calls[1]["method"] == "execute_kw"
    args = calls[1]["args"]
    assert args[3:5] == ["account.move", "search_read"]
    assert args[5] == [[["move_type", "in", ["out_invoice", "out_refund"]]]]
    assert args[6]["limit"] == 5 and args[6]["offset"] == 10


def test_authentication_required(client):
    assert client.get("/invoices").status_code == 401
    assert client.get("/invoices", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_missing_connector_key_fails_closed(client, monkeypatch):
    monkeypatch.delenv("CONNECTOR_API_KEY")
    assert client.get("/invoices").status_code == 503


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_pagination_is_bounded(client, query):
    odoo, calls = mock_odoo([])
    app.dependency_overrides[get_odoo] = lambda: odoo
    assert client.get("/invoices?" + query, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 422
    assert not calls


def test_single_invoice_is_scoped_and_missing_is_404(client):
    odoo, calls = mock_odoo([])
    app.dependency_overrides[get_odoo] = lambda: odoo
    assert client.get("/invoices/42", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 404
    assert ["id", "=", 42] in calls[1]["args"][5][0]


def test_rpc_errors_do_not_leak_upstream_details(client):
    def respond(request):
        return httpx.Response(200, json={"error": {"data": "sensitive-upstream-trace"}})
    app.dependency_overrides[get_odoo] = lambda: OdooClient(CFG, transport=httpx.MockTransport(respond))
    response = client.get("/invoices", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 502
    assert "sensitive-upstream-trace" not in response.text
    assert CFG.api_key not in response.text


def test_invalid_odoo_login_stops_before_object_call():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"result": False})
    odoo = OdooClient(CFG, transport=httpx.MockTransport(respond))
    with pytest.raises(OdooError):
        asyncio.run(odoo.invoices())
    assert len(calls) == 1


def test_write_routes_are_absent(client):
    assert client.post("/invoices", json={}).status_code == 405
    schema = client.get("/openapi.json").json()
    assert all(set(methods) == {"get"} for methods in schema["paths"].values())
    assert schema["paths"]["/invoices"]["get"]["security"] == [{"HTTPBearer": []}]


def test_missing_odoo_configuration(client, monkeypatch):
    monkeypatch.delenv("ODOO_DB", raising=False)
    assert client.get("/invoices", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 503


@pytest.mark.parametrize("url", ["http://odoo.example", "https://user:key@odoo.example", "https://odoo.example/?key=secret"])
def test_url_requires_https_without_embedded_secrets(monkeypatch, url):
    for name, value in {"ODOO_URL": url, "ODOO_DB": "db", "ODOO_LOGIN": "reader", "ODOO_API_KEY": "test"}.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError):
        Settings.from_environment()
