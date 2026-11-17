"""Local password authentication, opaque database sessions, and RBAC."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import (
    DBAuditEvent,
    DBAuthSession,
    DBLoginAttempt,
    DBUser,
    SessionLocal,
    get_db,
)

LOGGER = logging.getLogger("vidyutsetu.auth")
SESSION_COOKIE = "vidyutsetu_session"
PASSWORD_ROUNDS = 310_000
ROLES = {"admin", "operator", "viewer"}
router = APIRouter(prefix="/auth", tags=["authentication"])


@dataclass(frozen=True)
class Principal:
    user_id: int | None
    username: str
    role: str
    session_id: int | None
    cookie_authenticated: bool


class LoginInput(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class UserCreateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str = Field(..., min_length=12, max_length=256)
    role: Literal["admin", "operator", "viewer"]

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()


class UserUpdateInput(BaseModel):
    role: Literal["admin", "operator", "viewer"] | None = None
    is_active: bool | None = None


class PasswordResetInput(BaseModel):
    password: str = Field(..., min_length=12, max_length=256)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ROUNDS)
    return f"pbkdf2_sha256${PASSWORD_ROUNDS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds_text, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        rounds = int(rounds_text)
        if not 100_000 <= rounds <= 2_000_000:
            return False
        calculated = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), rounds
        )
        return hmac.compare_digest(calculated.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _csrf_token(session_token: str) -> str:
    return hmac.new(
        session_token.encode("ascii"), b"vidyutsetu-csrf-v1", hashlib.sha256
    ).hexdigest()


def _audit(
    db: Session,
    event_type: str,
    *,
    user_id: int | None = None,
    outcome: str = "success",
    metadata: dict | None = None,
) -> None:
    db.add(
        DBAuditEvent(
            user_id=user_id,
            event_type=event_type,
            outcome=outcome,
            metadata_json=json.dumps(metadata or {}, separators=(",", ":")),
        )
    )


def ensure_bootstrap_admin() -> None:
    """Create the first administrator only; never reset an existing password."""
    if settings.auth_mode == "disabled":
        return
    with SessionLocal() as db:
        if db.query(DBUser.id).limit(1).first():
            return
        username = (settings.demo_admin_username or "admin").lower()
        password = settings.initial_admin_password
        generated = False
        if settings.auth_mode == "demo" and not password:
            password = secrets.token_urlsafe(18)
            generated = True
        if not password:
            raise RuntimeError(
                "Set VIDYUTSETU_INITIAL_ADMIN_PASSWORD before first startup in password mode"
            )
        if len(password) < 12:
            raise RuntimeError("The initial administrator password must contain at least 12 characters")
        db.add(
            DBUser(
                username=username,
                password_hash=_password_hash(password),
                role="admin",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        if generated:
            LOGGER.warning(
                "One-time local demo administrator created: username=%s password=%s. "
                "Change it after signing in.",
                username,
                password,
            )


def _principal(request: Request, db: Session) -> Principal:
    if settings.auth_mode == "disabled":
        principal = Principal(None, "development", "admin", None, False)
        request.state.principal = principal
        return principal

    authorization = request.headers.get("authorization", "")
    bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    cookie_token = request.cookies.get(SESSION_COOKIE, "")
    token = bearer or cookie_token
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    session = (
        db.query(DBAuthSession)
        .filter(DBAuthSession.token_hash == _token_hash(token))
        .first()
    )
    now = datetime.now(timezone.utc)
    if not session or _utc(session.expires_at) <= now:
        raise HTTPException(status_code=401, detail="Session is invalid or expired.")
    user = db.query(DBUser).filter(DBUser.id == session.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account is inactive.")
    principal = Principal(user.id, user.username, user.role, session.id, bool(cookie_token and not bearer))
    request.state.principal = principal
    request.state.session_token = token
    return principal


def require_roles(*roles: str, write: bool = False):
    allowed = set(roles)
    if not allowed.issubset(ROLES):
        raise ValueError("Unknown role in authorization policy")

    def dependency(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
    ) -> Principal:
        principal = _principal(request, db)
        if principal.role not in allowed:
            raise HTTPException(status_code=403, detail="You are not authorized to perform this action.")
        if write and principal.cookie_authenticated:
            provided = request.headers.get("x-csrf-token", "")
            expected = _csrf_token(request.state.session_token)
            if not hmac.compare_digest(provided, expected):
                raise HTTPException(status_code=403, detail="Missing or invalid CSRF token.")
        return principal

    return dependency


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )


def _delete_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _rate_limit_key(request: Request) -> str:
    address = request.client.host if request.client else "unknown"
    return hashlib.sha256(address.encode("utf-8")).hexdigest()


def _user_summary(user: DBUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": _utc(user.created_at).isoformat(),
    }


@router.post("/login")
def login(
    request: Request,
    response: Response,
    body: LoginInput,
    db: Annotated[Session, Depends(get_db)],
):
    if settings.auth_mode == "disabled":
        return {"auth_enabled": False, "user": None}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=settings.login_attempt_window_seconds)
    rate_key = _rate_limit_key(request)
    db.query(DBLoginAttempt).filter(DBLoginAttempt.attempted_at < cutoff).delete(
        synchronize_session=False
    )
    db.commit()
    attempts = (
        db.query(func.count(DBLoginAttempt.id))
        .filter(DBLoginAttempt.address_hash == rate_key, DBLoginAttempt.attempted_at >= cutoff)
        .scalar()
    )
    if attempts >= settings.login_attempt_limit:
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")

    username = body.username.strip()
    user = db.query(DBUser).filter(func.lower(DBUser.username) == username.lower()).first()
    if not user or not user.is_active or not _verify_password(body.password, user.password_hash):
        db.add(DBLoginAttempt(address_hash=rate_key, attempted_at=now))
        _audit(db, "auth.login", outcome="failure")
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=settings.session_ttl_minutes)
    db.query(DBAuthSession).filter(DBAuthSession.expires_at <= now).delete(
        synchronize_session=False
    )
    session = DBAuthSession(
        user_id=user.id,
        token_hash=_token_hash(token),
        expires_at=expires_at,
        created_at=now,
    )
    user.last_login_at = now
    db.add(session)
    db.query(DBLoginAttempt).filter(DBLoginAttempt.address_hash == rate_key).delete()
    _audit(db, "auth.login", user_id=user.id, metadata={"role": user.role})
    db.commit()
    _set_session_cookie(response, token)
    return {"auth_enabled": True, "user": _user_summary(user), "csrf_token": _csrf_token(token)}


@router.get("/me")
def current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    if settings.auth_mode == "disabled":
        return {"auth_enabled": False, "user": None, "csrf_token": None}
    principal = _principal(request, db)
    token = request.state.session_token
    return {
        "auth_enabled": True,
        "user": {"id": principal.user_id, "username": principal.username, "role": principal.role},
        "csrf_token": _csrf_token(token),
    }


@router.post("/logout")
def logout(
    response: Response,
    principal: Annotated[Principal, Depends(require_roles("admin", "operator", "viewer", write=True))],
    db: Annotated[Session, Depends(get_db)],
):
    if principal.session_id is not None:
        db.query(DBAuthSession).filter(DBAuthSession.id == principal.session_id).delete()
        _audit(db, "auth.logout", user_id=principal.user_id)
        db.commit()
    _delete_session_cookie(response)
    return {"status": "logged_out"}


@router.get("/users")
def list_users(
    _principal: Annotated[Principal, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
):
    return [_user_summary(user) for user in db.query(DBUser).order_by(DBUser.username).all()]


@router.post("/users", status_code=201)
def create_user(
    body: UserCreateInput,
    principal: Annotated[Principal, Depends(require_roles("admin", write=True))],
    db: Annotated[Session, Depends(get_db)],
):
    user = DBUser(
        username=body.username,
        password_hash=_password_hash(body.password),
        role=body.role,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="That username is already in use.") from error
    _audit(db, "auth.user.create", user_id=principal.user_id, metadata={"role": body.role})
    db.commit()
    db.refresh(user)
    return _user_summary(user)


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdateInput,
    principal: Annotated[Principal, Depends(require_roles("admin", write=True))],
    db: Annotated[Session, Depends(get_db)],
):
    user = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide a role or active-state change.")
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Role and active-state values cannot be null.")
    resulting_role = changes.get("role", user.role)
    resulting_active = changes.get("is_active", user.is_active)
    if user.role == "admin" and user.is_active and (resulting_role != "admin" or not resulting_active):
        active_admins = db.query(DBUser).filter(DBUser.role == "admin", DBUser.is_active.is_(True)).count()
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="The last active administrator cannot be disabled or demoted.")
    for field, value in changes.items():
        setattr(user, field, value)
    if not user.is_active:
        db.query(DBAuthSession).filter(DBAuthSession.user_id == user.id).delete()
    _audit(db, "auth.user.update", user_id=principal.user_id, metadata={"target_user_id": user.id, **changes})
    db.commit()
    db.refresh(user)
    return _user_summary(user)


@router.post("/users/{user_id}/password")
def reset_user_password(
    user_id: int,
    body: PasswordResetInput,
    principal: Annotated[Principal, Depends(require_roles("admin", write=True))],
    db: Annotated[Session, Depends(get_db)],
):
    user = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.password_hash = _password_hash(body.password)
    db.query(DBAuthSession).filter(DBAuthSession.user_id == user.id).delete()
    _audit(db, "auth.user.password_reset", user_id=principal.user_id, metadata={"target_user_id": user.id})
    db.commit()
    return {"status": "password_updated"}


@router.get("/audit")
def list_audit_events(
    _principal: Annotated[Principal, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 100,
):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    return [
        {
            "id": event.id,
            "user_id": event.user_id,
            "event_type": event.event_type,
            "outcome": event.outcome,
            "created_at": _utc(event.created_at).isoformat(),
            "metadata": json.loads(event.metadata_json or "{}"),
        }
        for event in db.query(DBAuditEvent).order_by(DBAuditEvent.id.desc()).limit(limit).all()
    ]


@router.get("/analytics")
def auth_analytics(
    _principal: Annotated[Principal, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
):
    totals = (
        db.query(DBAuditEvent.event_type, DBAuditEvent.outcome, func.count(DBAuditEvent.id))
        .group_by(DBAuditEvent.event_type, DBAuditEvent.outcome)
        .all()
    )
    return {
        "events": [
            {"event_type": event_type, "outcome": outcome, "count": count}
            for event_type, outcome, count in totals
        ],
        "active_users": db.query(DBUser).filter(DBUser.is_active.is_(True)).count(),
    }
