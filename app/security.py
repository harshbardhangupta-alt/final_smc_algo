"""Authentication & authorization for backend controls.

A minimal cookie-session scheme protects settings and auto-trading endpoints.
Passwords are hashed with passlib (bcrypt). Read-only dashboard endpoints are
public; any mutation of settings / trading state requires an authenticated
admin. API credentials are never exposed to the browser.
"""

from __future__ import annotations

import hmac
import time
from hashlib import sha256

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import get_config
from .database import get_db
from .models import User

_COOKIE = "smc_session"
_MAX_AGE = 60 * 60 * 8  # 8 hours


def hash_password(raw: str) -> str:
    # bcrypt operates on at most 72 bytes; truncate deterministically.
    return bcrypt.hashpw(raw.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _sign(value: str) -> str:
    key = get_config().secret_key.encode()
    return hmac.new(key, value.encode(), sha256).hexdigest()


def issue_token(username: str) -> str:
    issued = str(int(time.time()))
    payload = f"{username}:{issued}"
    return f"{payload}:{_sign(payload)}"


def verify_token(token: str) -> str | None:
    try:
        username, issued, sig = token.rsplit(":", 2)
    except ValueError:
        return None
    payload = f"{username}:{issued}"
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    if int(time.time()) - int(issued) > _MAX_AGE:
        return None
    return username


def set_session_cookie(response, username: str) -> None:
    response.set_cookie(
        _COOKIE, issue_token(username), max_age=_MAX_AGE,
        httponly=True, samesite="lax",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(_COOKIE)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(_COOKIE)
    username = verify_token(token) if token else None
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin privileges required")
    return user


def ensure_admin_user(db: Session) -> None:
    """Seed the bootstrap admin from env on first run."""
    cfg = get_config()
    existing = db.query(User).filter(User.username == cfg.admin_username).first()
    if existing:
        return
    db.add(User(
        username=cfg.admin_username,
        password_hash=hash_password(cfg.admin_password),
        is_admin=True,
    ))
    db.commit()
