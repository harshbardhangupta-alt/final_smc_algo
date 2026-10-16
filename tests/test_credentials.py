"""Credential vault + API tests: encryption at rest, masking, rotation, resolve."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Secret
from app.services import credentials


def test_encrypt_roundtrip_and_not_plaintext(db_session):
    credentials.set_secrets(db_session, {"dhan_access_token": "super-secret-token"})
    row = db_session.get(Secret, "dhan_access_token")
    # Stored value must not contain the raw secret.
    assert "super-secret-token" not in row.value_encrypted
    assert credentials.get_secret(db_session, "dhan_access_token") == "super-secret-token"


def test_blank_values_keep_existing(db_session):
    credentials.set_secrets(db_session, {"openai_api_key": "sk-abc123"})
    changed = credentials.set_secrets(db_session, {"openai_api_key": "", "dhan_client_id": "110"})
    assert "openai_api_key" not in changed and "dhan_client_id" in changed
    assert credentials.get_secret(db_session, "openai_api_key") == "sk-abc123"


def test_status_masks_secrets(db_session):
    credentials.set_secrets(db_session, {"dhan_access_token": "abcdefgh1234",
                                         "dhan_client_id": "1100001234"})
    st = credentials.status(db_session)
    assert st["dhan_access_token"]["secret"] is True
    assert st["dhan_access_token"]["preview"].endswith("1234")
    assert "abcdefgh" not in st["dhan_access_token"]["preview"]
    # Non-secret client id is shown in full.
    assert st["dhan_client_id"]["preview"] == "1100001234"
    assert st["dhan_client_id"]["configured"] is True


def test_resolve_config_overrides_env(db_session):
    credentials.set_secrets(db_session, {"dhan_client_id": "DB_ID",
                                         "dhan_access_token": "DB_TOKEN"})
    resolved = credentials.resolve_config(db_session)
    assert resolved.dhan_client_id == "DB_ID"
    assert resolved.dhan_access_token == "DB_TOKEN"
    assert resolved.dhan_configured is True


# ---- API-level ----

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _login(client):
    assert client.post("/api/login", json={"username": "admin", "password": "pw123"}).status_code == 200


def test_credentials_endpoints_require_admin(client):
    assert client.get("/api/credentials").status_code == 401
    assert client.put("/api/credentials", json={"dhan_client_id": "x"}).status_code == 401
    assert client.post("/api/credentials/test/dhan").status_code == 401


def test_update_and_mask_via_api(client):
    _login(client)
    r = client.put("/api/credentials", json={"dhan_access_token": "tok-999988887777"})
    assert r.status_code == 200 and "dhan_access_token" in r.json()["changed"]
    status = client.get("/api/credentials").json()["credentials"]
    assert status["dhan_access_token"]["configured"] is True
    assert status["dhan_access_token"]["preview"].endswith("7777")
    # The raw token must never come back from the API.
    assert "tok-999988887777" not in client.get("/api/credentials").text


def test_test_connection_reports_not_configured_when_empty(client):
    _login(client)
    # Clear any stored creds so the test reflects an unconfigured provider.
    client.put("/api/credentials", json={"dhan_access_token": "__clear__",
                                         "dhan_client_id": "__clear__"})
    r = client.post("/api/credentials/test/dhan").json()
    assert r["provider"] == "dhan" and r["ok"] is False


def test_openai_test_endpoint_shape(client):
    _login(client)
    r = client.post("/api/credentials/test/openai").json()
    assert r["provider"] == "openai" and "ok" in r
