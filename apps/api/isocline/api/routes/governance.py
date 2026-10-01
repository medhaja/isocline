"""Policies, MCP servers, personal access tokens and workspace quotas."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, load_project, load_workflow, membership, parse_uuid
from isocline.core.errors import bad_request, forbidden, not_found
from isocline.db.models import ProviderCredential, User, utcnow
from isocline.db.models_v2 import McpServer, PersonalAccessToken, Policy, PolicyRule, WorkspaceQuota
from isocline.db.session import get_db
from isocline.services.audit import audit
from isocline.services.policies import RuleIn, snapshot

router = APIRouter(tags=["governance"])


# ================================================================== policies
class PolicyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    scope_type: Literal["workspace", "project", "workflow"]
    scope_id: str
    enabled: bool = True
    rules: list[RuleIn] = Field(default_factory=list)


async def _scope_workspace(db, user, scope_type: str, scope_id: str, role: str):
    if scope_type == "workspace":
        await membership(db, user, scope_id, role)
        return parse_uuid(scope_id)
    if scope_type == "project":
        return (await load_project(db, user, scope_id, role)).workspace_id
    return (await load_workflow(db, user, scope_id, role))[1].workspace_id


def _policy_out(p: Policy, rules: list[PolicyRule]) -> dict:
    return dump(p, "id", "workspace_id", "scope_type", "scope_id", "name", "description", "enabled", "version", "created_at", "updated_at",
                rules=[dump(r, "id", "kind", "subject", "action", "effect", "condition", "value", "mandatory", "position") for r in rules])


@router.get("/workspaces/{workspace_id}/policies")
async def list_policies(workspace_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id)
    ps = (await db.execute(select(Policy).where(Policy.workspace_id == parse_uuid(workspace_id)).order_by(Policy.scope_type, Policy.name))).scalars().all()
    rules = (await db.execute(select(PolicyRule).where(PolicyRule.policy_id.in_([p.id for p in ps])).order_by(PolicyRule.position))).scalars().all() if ps else []
    return [_policy_out(p, [r for r in rules if r.policy_id == p.id]) for p in ps]


@router.post("/policies", status_code=201)
async def create_policy(body: PolicyIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    ws = await _scope_workspace(db, user, body.scope_type, body.scope_id, "admin")
    for r in body.rules:
        try:
            r.check()
        except ValueError as e:
            raise bad_request(str(e)) from e
    p = Policy(workspace_id=ws, scope_type=body.scope_type, scope_id=parse_uuid(body.scope_id), name=body.name,
               description=body.description, enabled=body.enabled, created_by=user.id)
    db.add(p)
    await db.flush()
    rules = [PolicyRule(policy_id=p.id, position=i, **r.model_dump()) for i, r in enumerate(body.rules)]
    db.add_all(rules)
    await audit(db, "policy_created", user_id=user.id, workspace_id=ws, target_type="policy", target_id=p.id,
                data={"scope": body.scope_type, "rules": len(rules)})
    await db.commit()
    return _policy_out(p, rules)


@router.put("/policies/{policy_id}")
async def update_policy(policy_id: str, body: PolicyIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Policy, parse_uuid(policy_id, "Policy"))
    if p is None:
        raise not_found("Policy")
    await _scope_workspace(db, user, p.scope_type, str(p.scope_id), "admin")
    for r in body.rules:
        try:
            r.check()
        except ValueError as e:
            raise bad_request(str(e)) from e
    before = [dump(r, "kind", "subject", "action", "effect", "mandatory") for r in
              (await db.execute(select(PolicyRule).where(PolicyRule.policy_id == p.id))).scalars()]
    await db.execute(delete(PolicyRule).where(PolicyRule.policy_id == p.id))
    p.name, p.description, p.enabled, p.version = body.name, body.description, body.enabled, p.version + 1
    rules = [PolicyRule(policy_id=p.id, position=i, **r.model_dump()) for i, r in enumerate(body.rules)]
    db.add_all(rules)
    await audit(db, "policy_updated", user_id=user.id, workspace_id=p.workspace_id, target_type="policy", target_id=p.id,
                data={"version": p.version, "before": before, "after": [r.model_dump() for r in body.rules]})
    await db.commit()
    return _policy_out(p, rules)


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(policy_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Policy, parse_uuid(policy_id, "Policy"))
    if p is None:
        raise not_found("Policy")
    await _scope_workspace(db, user, p.scope_type, str(p.scope_id), "admin")
    await audit(db, "policy_deleted", user_id=user.id, workspace_id=p.workspace_id, target_id=p.id, data={"name": p.name})
    await db.execute(delete(PolicyRule).where(PolicyRule.policy_id == p.id))
    await db.delete(p)
    await db.commit()


@router.get("/workflows/{workflow_id}/effective-policy")
async def effective_policy(workflow_id: str, user: User = Depends(current_user),
                           db: AsyncSession = Depends(get_db)):
    """The merged rule set a run of this workflow would be governed by."""
    wf, p = await load_workflow(db, user, workflow_id)
    snap = await snapshot(db, workspace_id=p.workspace_id, project_id=p.id,
                          workflow_id=wf.id)
    from isocline.engine.policy import budget_clamps
    return {"rules": snap, "budget_clamps": budget_clamps(snap),
            "resolution": "Mandatory rules always apply (most restrictive wins); otherwise the most specific scope wins."}


# ================================================================== MCP
class McpIn(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    endpoint: str = Field(max_length=500)
    transport: Literal["streamable_http"] = "streamable_http"
    credential_id: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=6000)


def _mcp_out(m: McpServer) -> dict:
    return dump(m, "id", "workspace_id", "name", "transport", "endpoint", "allowed_tools", "tools", "status", "last_error",
                "rate_limit_per_minute", "synced_at", "created_at",
                credential_id=str(m.credential_id) if m.credential_id else None,
                grants=[f"mcp:{m.name}/{t}" for t in m.allowed_tools or []])


@router.get("/workspaces/{workspace_id}/mcp")
async def list_mcp(workspace_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id)
    rows = (await db.execute(select(McpServer).where(McpServer.workspace_id == parse_uuid(workspace_id)).order_by(McpServer.name))).scalars().all()
    return [_mcp_out(m) for m in rows]


@router.post("/workspaces/{workspace_id}/mcp", status_code=201)
async def create_mcp(workspace_id: str, body: McpIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id, "admin")
    if not body.endpoint.startswith(("https://", "http://")):
        raise bad_request("Only HTTP(S) MCP endpoints are supported (stdio servers would run commands on the Isocline host)")
    wid = parse_uuid(workspace_id)
    if body.credential_id:
        c = await db.get(ProviderCredential, parse_uuid(body.credential_id, "Credential"))
        if c is None or c.workspace_id != wid:
            raise not_found("Credential")
    m = McpServer(workspace_id=wid, name=body.name, endpoint=body.endpoint, transport=body.transport,
                  credential_id=parse_uuid(body.credential_id) if body.credential_id else None, allowed_tools=body.allowed_tools,
                  rate_limit_per_minute=body.rate_limit_per_minute)
    db.add(m)
    await db.flush()
    await audit(db, "mcp_registered", user_id=user.id, workspace_id=wid, target_id=m.id, data={"name": m.name, "endpoint": m.endpoint})
    await db.commit()
    return _mcp_out(m)


@router.put("/mcp/{server_id}")
async def update_mcp(server_id: str, body: McpIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    m = await db.get(McpServer, parse_uuid(server_id, "MCP server"))
    if m is None:
        raise not_found("MCP server")
    await membership(db, user, m.workspace_id, "admin")
    unknown = [t for t in body.allowed_tools if m.tools and t not in {x.get("name") for x in m.tools}]
    if unknown:
        raise bad_request(f"Not offered by this server: {unknown}. Sync tools first.")
    before = list(m.allowed_tools or [])
    m.endpoint, m.allowed_tools, m.rate_limit_per_minute = body.endpoint, body.allowed_tools, body.rate_limit_per_minute
    m.credential_id = parse_uuid(body.credential_id) if body.credential_id else None
    await audit(db, "mcp_permissions_changed", user_id=user.id, workspace_id=m.workspace_id, target_id=m.id,
                data={"before": before, "after": body.allowed_tools})
    await db.commit()
    return _mcp_out(m)


@router.post("/mcp/{server_id}/sync")
async def sync_mcp(server_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Lists the server's tools. Syncing grants nothing: tools must be allowlisted here AND granted per agent."""
    from isocline.core.security import decrypt_secret
    from isocline.services.mcp import McpClient
    m = await db.get(McpServer, parse_uuid(server_id, "MCP server"))
    if m is None:
        raise not_found("MCP server")
    await membership(db, user, m.workspace_id, "admin")
    token = None
    if m.credential_id:
        c = await db.get(ProviderCredential, m.credential_id)
        token = decrypt_secret(c.encrypted_value) if c and c.encrypted_value else None
    try:
        tools = await McpClient(m.endpoint, token).list_tools()
        m.tools = [{"name": t.get("name"), "description": (t.get("description") or "")[:1000], "inputSchema": t.get("inputSchema") or {},
                    "annotations": t.get("annotations") or {}} for t in tools]
        m.status, m.last_error, m.synced_at = "ok", None, utcnow()
    except Exception as e:
        m.status, m.last_error = "error", str(e)[:500]
    await db.commit()
    return _mcp_out(m)


@router.delete("/mcp/{server_id}", status_code=204)
async def delete_mcp(server_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    m = await db.get(McpServer, parse_uuid(server_id, "MCP server"))
    if m is None:
        raise not_found("MCP server")
    await membership(db, user, m.workspace_id, "admin")
    await audit(db, "mcp_removed", user_id=user.id, workspace_id=m.workspace_id, target_id=m.id, data={"name": m.name})
    await db.delete(m)
    await db.commit()


# ================================================================== personal access tokens
class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    expires_in_days: int | None = Field(default=90, ge=1, le=3650)


@router.get("/tokens")
async def list_tokens(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id).order_by(PersonalAccessToken.created_at.desc()))).scalars().all()
    return [dump(t, "id", "name", "prefix", "created_at", "last_used_at", "expires_at", "revoked_at") for t in rows]


@router.post("/tokens", status_code=201)
async def create_token(body: TokenIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    raw = "isc_pat_" + secrets.token_hex(24)
    t = PersonalAccessToken(user_id=user.id, name=body.name, prefix=raw[:12], token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                            expires_at=utcnow() + timedelta(days=body.expires_in_days) if body.expires_in_days else None)
    db.add(t)
    await db.flush()
    await audit(db, "access_token_created", user_id=user.id, target_id=t.id, data={"name": body.name})
    await db.commit()
    return {**dump(t, "id", "name", "prefix", "created_at", "expires_at"), "token": raw,
            "warning": "Copy this token now. It will not be shown again."}


@router.post("/tokens/{token_id}/revoke")
async def revoke_token(token_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    t = await db.get(PersonalAccessToken, parse_uuid(token_id, "Token"))
    if t is None or t.user_id != user.id:
        raise not_found("Token")
    t.revoked_at = t.revoked_at or utcnow()
    await audit(db, "access_token_revoked", user_id=user.id, target_id=t.id)
    await db.commit()
    return {"ok": True}


# ================================================================== quotas
class QuotaIn(BaseModel):
    max_concurrent_runs: int = Field(ge=1, le=1000)
    max_concurrent_nodes: int = Field(ge=1, le=1000)
    monthly_token_quota: int | None = Field(default=None, ge=0)
    monthly_cost_quota: float | None = Field(default=None, ge=0)
    sandbox_concurrency: int = Field(ge=1, le=200)
    artifact_storage_bytes: int = Field(ge=0)
    rate_limit_per_minute: int = Field(ge=1, le=100000)


@router.get("/workspaces/{workspace_id}/quota")
async def get_quota_route(workspace_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func
    from isocline.db.models_v2 import Artifact
    from isocline.services.quotas import get_quota, month_usage, running_count
    await membership(db, user, workspace_id)
    wid = parse_uuid(workspace_id)
    q = await get_quota(db, wid)
    tokens, cost = await month_usage(db, wid)
    storage = (await db.execute(select(func.coalesce(func.sum(Artifact.size_bytes), 0)).where(Artifact.workspace_id == wid))).scalar() or 0
    return {"limits": dump(q, "max_concurrent_runs", "max_concurrent_nodes", "monthly_token_quota", "monthly_cost_quota",
                           "sandbox_concurrency", "artifact_storage_bytes", "rate_limit_per_minute"),
            "usage": {"running_runs": await running_count(db, wid), "month_tokens": tokens, "month_cost_usd": round(cost, 4),
                      "artifact_bytes": int(storage)}}


@router.put("/workspaces/{workspace_id}/quota")
async def set_quota(workspace_id: str, body: QuotaIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not user.is_admin:
        raise forbidden("Only installation administrators can change workspace quotas")
    wid = parse_uuid(workspace_id)
    q = await db.get(WorkspaceQuota, wid) or WorkspaceQuota(workspace_id=wid)
    for k, v in body.model_dump().items():
        setattr(q, k, v)
    db.add(q)
    await audit(db, "quota_updated", user_id=user.id, workspace_id=wid, data=body.model_dump())
    await db.commit()
    return {"ok": True}
