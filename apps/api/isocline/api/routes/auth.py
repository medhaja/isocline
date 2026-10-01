from __future__ import annotations

import hashlib
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import CSRF_COOKIE, SESSION_COOKIE, current_user, dump
from isocline.core.config import get_settings
from isocline.core.errors import AppError, bad_request
from isocline.core.security import create_session_token, hash_password, random_token, verify_password
from isocline.db.models import AuthToken, User, Workspace, WorkspaceMember, utcnow
from isocline.db.session import get_db
from isocline.services.audit import audit
from isocline.services.email import send_email

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    name: str = Field(default="", max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=200)


class TokenIn(BaseModel):
    token: str


def _set_session(resp: Response, user: User) -> None:
    s = get_settings()
    resp.set_cookie(SESSION_COOKIE, create_session_token(str(user.id)), httponly=True, secure=s.cookie_secure,
                    samesite="lax", max_age=s.session_ttl_minutes * 60, path="/")
    resp.set_cookie(CSRF_COOKIE, random_token(24), httponly=False, secure=s.cookie_secure, samesite="lax",
                    max_age=s.session_ttl_minutes * 60, path="/")


def _user_out(u: User) -> dict:
    return dump(u, "id", "email", "name", "email_verified", "is_admin", "created_at")


async def _issue_token(db: AsyncSession, user: User, kind: str, hours: int) -> str:
    raw = random_token(32)
    db.add(AuthToken(user_id=user.id, kind=kind, token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                     expires_at=utcnow() + timedelta(hours=hours)))
    return raw


async def _consume(db: AsyncSession, raw: str, kind: str) -> AuthToken:
    t = (await db.execute(select(AuthToken).where(AuthToken.token_hash == hashlib.sha256(raw.encode()).hexdigest(),
                                                  AuthToken.kind == kind))).scalar_one_or_none()
    exp = t.expires_at if t is None or t.expires_at.tzinfo else t.expires_at.replace(tzinfo=utcnow().tzinfo)
    if t is None or t.used_at is not None or exp < utcnow():
        raise bad_request("This link is invalid or has expired")
    t.used_at = utcnow()
    return t


@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    email = body.email.lower()
    if (await db.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none():
        raise AppError(409, "email_taken", "An account with this email already exists")
    first = (await db.execute(select(func.count(User.id)))).scalar() == 0
    if not first and not get_settings().allow_signup:
        raise AppError(403, "signup_closed", "Registration is closed on this installation. Ask its administrator for an "
                       "account (the administrator can set ISOCLINE_ALLOW_SIGNUP=true).")
    user, ws = await create_account(db, email, body.password, body.name, is_admin=first)
    token = await _issue_token(db, user, "email_verify", 72)
    await audit(db, "user_registered", user_id=user.id, workspace_id=ws.id, ip=request.client.host if request.client else None)
    await db.commit()
    await send_email(user.email, "Verify your Isocline email",
                     f"Verify your email: {get_settings().public_base_url}/verify-email?token={token}")
    _set_session(response, user)
    return {"user": _user_out(user), "workspace_id": str(ws.id)}


async def create_account(db: AsyncSession, email: str, password: str, name: str = "", *, is_admin: bool = False):
    """Creates a user with a personal workspace and a default project (single-tenant local mode: the workspace and
    project exist so a new installation is usable immediately). Does not commit."""
    from isocline.db.models import Project
    user = User(email=email, name=name or email.split("@")[0], password_hash=hash_password(password),
                is_admin=is_admin)  # the first account on an installation administers pricing/model metadata
    db.add(user)
    await db.flush()
    ws = Workspace(name=f"{user.name}'s workspace", owner_id=user.id)
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    db.add(Project(workspace_id=ws.id, name="Default project", description="Created automatically on sign-up."))
    await db.flush()
    return user, ws


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(func.lower(User.email) == body.email.lower()))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        await audit(db, "login_failed", data={"email": body.email.lower()}, ip=request.client.host if request.client else None,
                    commit=True)
        raise AppError(401, "invalid_credentials", "Email or password is incorrect")
    if get_settings().require_email_verification and not user.email_verified:
        raise AppError(403, "email_unverified", "Please verify your email before signing in")
    await audit(db, "login", user_id=user.id, ip=request.client.host if request.client else None, commit=True)
    _set_session(response, user)
    return {"user": _user_out(user)}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Workspace, WorkspaceMember.role).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                             .where(WorkspaceMember.user_id == user.id).order_by(Workspace.created_at))).all()
    return {"user": _user_out(user), "workspaces": [dump(w, "id", "name", "created_at", role=r) for w, r in rows]}


@router.post("/forgot-password")
async def forgot(body: ForgotIn, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(func.lower(User.email) == body.email.lower()))).scalar_one_or_none()
    if user:
        token = await _issue_token(db, user, "password_reset", 1)
        await db.commit()
        await send_email(user.email, "Reset your Isocline password",
                         f"Reset your password (valid for 1 hour): {get_settings().public_base_url}/reset-password?token={token}")
    return {"ok": True}  # identical response whether or not the account exists


@router.post("/reset-password")
async def reset(body: ResetIn, response: Response, db: AsyncSession = Depends(get_db)):
    t = await _consume(db, body.token, "password_reset")
    user = await db.get(User, t.user_id)
    user.password_hash = hash_password(body.password)
    await audit(db, "password_reset", user_id=user.id)
    await db.commit()
    _set_session(response, user)
    return {"ok": True}


@router.post("/verify-email")
async def verify(body: TokenIn, db: AsyncSession = Depends(get_db)):
    t = await _consume(db, body.token, "email_verify")
    user = await db.get(User, t.user_id)
    user.email_verified = True
    await db.commit()
    return {"ok": True}


@router.post("/resend-verification")
async def resend(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not user.email_verified:
        token = await _issue_token(db, user, "email_verify", 72)
        await db.commit()
        await send_email(user.email, "Verify your Isocline email",
                         f"Verify your email: {get_settings().public_base_url}/verify-email?token={token}")
    return {"ok": True}
