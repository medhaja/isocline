"""Request dependencies: authentication, workspace authorization, serialization helpers."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.errors import AppError, forbidden, not_found
from isocline.core.security import decode_session_token
from isocline.db.models import (
    EvaluationDataset, KnowledgeBase, Project, Run, User, Workflow, WorkspaceMember,
)
from isocline.db.session import get_db

SESSION_COOKIE = "isc_session"
CSRF_COOKIE = "isc_csrf"
ROLE_RANK = {"viewer": 0, "reviewer": 0, "operator": 1, "editor": 1, "developer": 1, "admin": 2, "owner": 3}  # legacy display only


def parse_uuid(v: Any, what: str = "Resource") -> uuid.UUID:
    try:
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    except (ValueError, TypeError) as e:
        raise not_found(what) from e


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer isc_pat_"):
        return await _pat_user(request, db, auth[7:].strip())
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:]
    uid = decode_session_token(token) if token else None
    if not uid:
        raise AppError(401, "unauthenticated", "Please sign in")
    user = await db.get(User, parse_uuid(uid))
    if user is None:
        raise AppError(401, "unauthenticated", "Please sign in")
    request.state.user_id = str(user.id)
    return user


async def _pat_user(request: Request, db: AsyncSession, raw: str) -> User:
    """Personal access tokens (SDK/CLI). Stored hashed; revocable; optional expiry."""
    import hashlib
    from isocline.db.models import utcnow
    from isocline.db.models_v2 import PersonalAccessToken
    t = (await db.execute(select(PersonalAccessToken).where(PersonalAccessToken.token_hash == hashlib.sha256(raw.encode()).hexdigest()))).scalar_one_or_none()
    exp = t.expires_at.replace(tzinfo=utcnow().tzinfo) if t and t.expires_at and t.expires_at.tzinfo is None else (t.expires_at if t else None)
    if t is None or t.revoked_at is not None or (exp and exp < utcnow()):
        raise AppError(401, "invalid_token", "Access token is invalid, expired or revoked")
    user = await db.get(User, t.user_id)
    if user is None:
        raise AppError(401, "invalid_token", "Access token is invalid")
    t.last_used_at = utcnow()
    await db.commit()
    request.state.user_id = str(user.id)
    request.state.via_token = True
    return user


async def effective_permissions(db: AsyncSession, member: WorkspaceMember, project_id=None) -> set[str]:
    """Permissions of a workspace member's built-in role (owner, admin, developer, operator, reviewer, viewer)."""
    from isocline.core.rbac import role_permissions
    return role_permissions(member.role, {})


async def membership(db: AsyncSession, user: User, workspace_id, min_role: str = "viewer", project_id=None) -> WorkspaceMember:
    """Checks workspace membership and a requirement: a role name (viewer/editor/admin/owner) or a
    permission such as "workflows:publish". Enforcement is always server-side."""
    from isocline.core.rbac import allowed
    m = (await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == parse_uuid(workspace_id, "Workspace"),
                                                        WorkspaceMember.user_id == user.id))).scalar_one_or_none()
    if m is None:
        raise not_found("Workspace")  # do not reveal existence across tenants
    if min_role in ("viewer", "workspace:read"):
        return m
    if not allowed(await effective_permissions(db, m, project_id), min_role):
        raise forbidden()
    return m


async def load_project(db: AsyncSession, user: User, project_id, min_role: str = "viewer") -> Project:
    p = await db.get(Project, parse_uuid(project_id, "Project"))
    if p is None:
        raise not_found("Project")
    await membership(db, user, p.workspace_id, min_role, project_id=p.id)
    return p


async def load_workflow(db: AsyncSession, user: User, workflow_id, min_role: str = "viewer") -> tuple[Workflow, Project]:
    wf = await db.get(Workflow, parse_uuid(workflow_id, "Workflow"))
    if wf is None:
        raise not_found("Workflow")
    return wf, await load_project(db, user, wf.project_id, min_role)


async def load_run(db: AsyncSession, user: User, run_id, min_role: str = "viewer") -> Run:
    r = await db.get(Run, parse_uuid(run_id, "Run"))
    if r is None:
        raise not_found("Run")
    await membership(db, user, r.workspace_id, min_role)
    return r


async def load_kb(db: AsyncSession, user: User, kb_id, min_role="viewer") -> tuple[KnowledgeBase, Project]:
    kb = await db.get(KnowledgeBase, parse_uuid(kb_id, "Knowledge base"))
    if kb is None:
        raise not_found("Knowledge base")
    return kb, await load_project(db, user, kb.project_id, min_role)


async def load_dataset(db: AsyncSession, user: User, ds_id, min_role="viewer") -> tuple[EvaluationDataset, Project]:
    ds = await db.get(EvaluationDataset, parse_uuid(ds_id, "Dataset"))
    if ds is None:
        raise not_found("Dataset")
    return ds, await load_project(db, user, ds.project_id, min_role)


def dump(obj, *fields: str, **extra) -> dict:
    """Explicit serialization: only whitelisted fields ever leave the API."""
    out = {}
    for f in fields:
        v = getattr(obj, f)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        out[f] = v
    out.update(extra)
    return out
