"""Auth + settings management (admin-protected). Secrets never leave the server."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from pydantic import BaseModel

from ..config import get_config
from ..database import get_db
from ..models import AuditLog, Settings, User
from ..providers.dhan import DhanClient
from ..providers.openai_client import OpenAIResearcher
from ..schemas import LoginRequest, SettingsOut, SettingsUpdate
from ..services import credentials
from ..security import (
    clear_session_cookie,
    current_user,
    require_admin,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/api", tags=["settings"])

_GROUPS = ("universe", "capital", "auto_trading", "scheduling", "scoring", "policy")


@router.post("/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    set_session_cookie(response, user.username)
    return {"status": "ok", "username": user.username}


@router.post("/logout")
def logout(response: Response) -> dict:
    clear_session_cookie(response)
    return {"status": "ok"}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"username": user.username, "is_admin": user.is_admin}


@router.get("/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> SettingsOut:
    s = _require_settings(db)
    resolved = credentials.resolve_config(db)  # env + DB-stored credentials
    return SettingsOut(
        universe=s.universe, capital=s.capital, auto_trading=s.auto_trading,
        scheduling=s.scheduling, scoring=s.scoring, policy=s.policy,
        updated_at=s.updated_at,
        integrations={
            "dhan": resolved.dhan_configured,
            "openai": resolved.openai_configured,
            "news": resolved.news_configured,
        },
    )


@router.put("/settings", response_model=SettingsOut)
def update_settings(
    body: SettingsUpdate, db: Session = Depends(get_db), user: User = Depends(require_admin),
) -> SettingsOut:
    s = _require_settings(db)
    changes: dict[str, dict] = {}
    for group in _GROUPS:
        incoming = getattr(body, group)
        if incoming is None:
            continue
        current = dict(getattr(s, group) or {})
        _guard_auto_trading(group, current, incoming)
        current.update(incoming)
        setattr(s, group, current)
        changes[group] = incoming

    db.add(AuditLog(actor=user.username, action="settings_update", detail=changes))
    db.commit()
    db.refresh(s)
    return get_settings(db, user)


def _guard_auto_trading(group: str, current: dict, incoming: dict) -> None:
    """Enabling LIVE auto-trading requires explicit confirmation in the payload."""
    if group != "auto_trading":
        return
    enabling = incoming.get("enabled") and not current.get("enabled")
    going_live = incoming.get("paper_trading") is False or current.get("paper_trading") is False
    if enabling and going_live and not incoming.get("live_confirmed"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Enabling LIVE auto-trading requires 'live_confirmed': true in the request.",
        )


class CredentialsUpdate(BaseModel):
    dhan_client_id: str | None = None
    dhan_access_token: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    news_api_key: str | None = None


@router.get("/credentials")
def get_credentials(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    """Masked credential status (never the raw secret values)."""
    return {"credentials": credentials.status(db)}


@router.put("/credentials")
def update_credentials(
    body: CredentialsUpdate, db: Session = Depends(get_db), user: User = Depends(require_admin),
) -> dict:
    """Save/update credentials. Blank fields keep the existing value.

    This is how the admin rotates the Dhan access token (expires every ~24h)
    without restarting the server. Values are stored encrypted at rest.
    """
    changed = credentials.set_secrets(db, body.model_dump())
    # Audit only WHICH keys changed, never the values.
    db.add(AuditLog(actor=user.username, action="credentials_update", detail={"changed": changed}))
    db.commit()
    return {"status": "ok", "changed": changed, "credentials": credentials.status(db)}


@router.post("/credentials/test/dhan")
def test_dhan(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    """Live test: is the Dhan API reachable & authorized with current creds?"""
    resolved = credentials.resolve_config(db)
    result = DhanClient(resolved).health_check()
    return {"provider": "dhan", **result}


@router.post("/credentials/test/openai")
def test_openai(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    """Live test: is the OpenAI API reachable & the key/model valid?"""
    resolved = credentials.resolve_config(db)
    result = OpenAIResearcher(resolved).test_connection()
    return {"provider": "openai", **result}


@router.get("/audit")
def audit(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[dict]:
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(50).all()
    return [{"ts": r.ts, "actor": r.actor, "action": r.action, "detail": r.detail} for r in rows]


def _require_settings(db: Session) -> Settings:
    s = db.get(Settings, 1)
    if s is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Settings not initialised")
    return s
