"""API-level tests: health, open settings, persistence, dashboard, safety.

Authentication has been removed, so settings/credentials/scan/order endpoints
are open. These tests assert the endpoints work without any login.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["integrations"]) == {"dhan", "openai", "news"}


def test_dashboard_offline_shows_no_setups(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["auto_trading"] in ("OFF", "ON", "ON (paper)", "KILL-SWITCH")
    assert body["message"] == "No qualified trade setups currently available."


def test_no_login_endpoints(client):
    # Login/logout were removed entirely.
    assert client.post("/api/login", json={"username": "x", "password": "y"}).status_code == 404
    assert client.post("/api/logout").status_code == 404


def test_settings_open_without_auth(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["universe"]["selected"] in ("NIFTY50", "NIFTY100", "NIFTY500", "CUSTOM")
    assert body["auto_trading"]["enabled"] is False
    # Secrets must never be exposed — only presence booleans.
    assert set(body["integrations"]) == {"dhan", "openai", "news"}
    assert all(isinstance(v, bool) for v in body["integrations"].values())


def test_settings_persist_after_update(client):
    r = client.put("/api/settings", json={"capital": {"total_capital": 2_500_000.0}})
    assert r.status_code == 200
    assert client.get("/api/settings").json()["capital"]["total_capital"] == 2_500_000.0


def test_enable_live_requires_confirmation(client):
    r = client.put("/api/settings", json={"auto_trading": {"enabled": True, "paper_trading": False}})
    assert r.status_code == 400
    assert "live_confirmed" in r.json()["detail"]
    # With confirmation it succeeds.
    r2 = client.put("/api/settings", json={
        "auto_trading": {"enabled": True, "paper_trading": False, "live_confirmed": True}})
    assert r2.status_code == 200


def test_kill_switch_open(client):
    r = client.post("/api/kill-switch?on=true")
    assert r.status_code == 200 and r.json()["kill_switch"] is True


def test_pages_render(client):
    for path in ("/", "/settings", "/orders"):
        assert client.get(path).status_code == 200


def test_scan_runs_endpoint(client):
    r = client.get("/api/scan/runs")
    assert r.status_code == 200 and isinstance(r.json(), list)
