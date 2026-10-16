"""Admin-managed API credentials, encrypted at rest.

Credentials entered from the website are stored encrypted (Fernet, keyed from
SECRET_KEY) in the ``secrets`` table. They override the corresponding ``.env``
values at runtime, so an operator can rotate the Dhan access token (which Dhan
expires every ~24h) from the UI without touching the server or restarting.

Secrets are never returned to the browser in plaintext — only masked previews
and presence flags. :func:`resolve_config` produces a Config with DB secrets
merged over the environment, which every provider uses.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from sqlalchemy.orm import Session

from ..config import Config, get_config
from ..models import Secret

log = logging.getLogger(__name__)

# The credential keys the UI manages. ``secret=True`` ones are never revealed.
MANAGED_KEYS = {
    "dhan_client_id": {"secret": False, "label": "Dhan Client ID"},
    "dhan_access_token": {"secret": True, "label": "Dhan Access Token"},
    "openai_api_key": {"secret": True, "label": "OpenAI API Key"},
    "openai_model": {"secret": False, "label": "OpenAI Model"},
    "news_api_key": {"secret": True, "label": "News API Key"},
}


def _fernet():
    """Build a Fernet cipher from SECRET_KEY, or None if cryptography is absent."""
    try:
        from cryptography.fernet import Fernet
    except Exception:  # noqa: BLE001  (dependency optional)
        return None
    digest = hashlib.sha256(get_config().secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(raw: str) -> str:
    f = _fernet()
    if f is None:
        log.warning("cryptography unavailable; storing credential WITHOUT encryption")
        return "plain:" + raw
    return "enc:" + f.encrypt(raw.encode("utf-8")).decode("utf-8")


def _decrypt(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith("plain:"):
        return stored[len("plain:"):]
    if stored.startswith("enc:"):
        f = _fernet()
        if f is None:
            return ""
        try:
            return f.decrypt(stored[len("enc:"):].encode("utf-8")).decode("utf-8")
        except Exception:  # noqa: BLE001  (wrong key / corrupt)
            log.error("failed to decrypt stored credential (SECRET_KEY changed?)")
            return ""
    return stored  # legacy/plain fallback


def get_secret(db: Session, key: str) -> str:
    row = db.get(Secret, key)
    return _decrypt(row.value_encrypted) if row else ""


def set_secrets(db: Session, mapping: dict[str, str]) -> list[str]:
    """Upsert provided credentials. Blank/None values are skipped (keep existing).

    Returns the list of keys actually changed. An explicit empty-string delete is
    expressed by passing the sentinel ``"__clear__"``.
    """
    changed: list[str] = []
    for key, value in mapping.items():
        if key not in MANAGED_KEYS:
            continue
        if value is None or value == "":
            continue  # keep the existing value
        row = db.get(Secret, key)
        if row is None:
            row = Secret(key=key)
            db.add(row)
        row.value_encrypted = "" if value == "__clear__" else _encrypt(value)
        changed.append(key)
    db.commit()
    return changed


def status(db: Session) -> dict:
    """Masked presence report for the UI — never the raw secret values."""
    cfg = get_config()
    env_values = {
        "dhan_client_id": cfg.dhan_client_id,
        "dhan_access_token": cfg.dhan_access_token,
        "openai_api_key": cfg.openai_api_key,
        "openai_model": cfg.openai_model,
        "news_api_key": cfg.news_api_key,
    }
    out: dict[str, dict] = {}
    for key, meta in MANAGED_KEYS.items():
        db_val = get_secret(db, key)
        source = "database" if db_val else ("env" if env_values.get(key) else "none")
        value = db_val or env_values.get(key, "")
        out[key] = {
            "label": meta["label"],
            "secret": meta["secret"],
            "configured": bool(value),
            "source": source,
            "preview": _mask(value) if meta["secret"] else value,
            "updated_at": _updated_at(db, key),
        }
    return out


def resolve_config(db: Session) -> Config:
    """Return a Config with DB-stored secrets merged over the environment."""
    cfg = get_config()
    overrides: dict[str, str] = {}
    for key in MANAGED_KEYS:
        val = get_secret(db, key)
        if val:
            overrides[key] = val
    return cfg.model_copy(update=overrides) if overrides else cfg


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]


def _updated_at(db: Session, key: str):
    row = db.get(Secret, key)
    return row.updated_at.isoformat() if row and row.updated_at else None
