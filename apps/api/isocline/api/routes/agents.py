from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, membership, parse_uuid
from isocline.core.errors import AppError, not_found
from isocline.db.models import Agent, User
from isocline.db.session import get_db
from isocline.engine.agent_templates import AGENT_TEMPLATES
from isocline.schemas.workflow import AgentConfig
from isocline.services.audit import audit

router = APIRouter(tags=["agents"])


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    template: str = "custom"
    config: dict = Field(default_factory=dict)
    slug: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,62}$")
    contract: dict | None = None


def _validate_config(cfg: dict) -> dict:
    cfg = {k: v for k, v in cfg.items() if k != "library_agent_id"}
    try:
        return AgentConfig.model_validate(cfg).model_dump(mode="json", exclude_none=False)
    except ValidationError as e:
        raise AppError(422, "invalid_agent", "Agent configuration is invalid",
                       [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]) from e


def agent_out(a: Agent, extra: dict | None = None) -> dict:
    return dump(a, "id", "workspace_id", "name", "description", "template", "config", "slug", "created_at", "updated_at",
                contract=a.draft_contract, **(extra or {}))


async def _registry_info(db, agents: list[Agent]) -> dict:
    """Library agents are reusable agent configurations (no versions or aliases in this edition)."""
    return {}


async def _unique_slug(db, workspace_id, base: str) -> str:
    from isocline.core.text import slugify
    base, n, slug = slugify(base), 1, None
    slug = base
    while (await db.execute(select(Agent.id).where(Agent.workspace_id == workspace_id, Agent.slug == slug))).first():
        n += 1
        slug = f"{base}-{n}"
    return slug


@router.get("/agent-templates")
async def agent_templates(user: User = Depends(current_user)):
    return [{"id": k, **v} for k, v in AGENT_TEMPLATES.items()]


@router.get("/workspaces/{workspace_id}/agents")
async def list_agents(workspace_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id)
    rows = (await db.execute(select(Agent).where(Agent.workspace_id == parse_uuid(workspace_id)).order_by(Agent.name))).scalars().all()
    info = await _registry_info(db, rows)
    return [agent_out(a, info.get(a.id)) for a in rows]


@router.post("/workspaces/{workspace_id}/agents", status_code=201)
async def create_agent(workspace_id: str, body: AgentIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id, "agents:write")
    wid = parse_uuid(workspace_id)
    if body.slug and (await db.execute(select(Agent.id).where(Agent.workspace_id == wid, Agent.slug == body.slug))).first():
        raise AppError(409, "slug_taken", f"An agent with the reference '{body.slug}' already exists")
    a = Agent(workspace_id=wid, name=body.name, description=body.description, template=body.template,
              config=_validate_config({**body.config, "template": body.template}), slug=body.slug or await _unique_slug(db, wid, body.name),
              draft_contract=body.contract)
    db.add(a)
    await db.flush()
    await audit(db, "agent_created", user_id=user.id, workspace_id=a.workspace_id, target_type="agent", target_id=a.id)
    await db.commit()
    return agent_out(a)


async def _load(db, user, agent_id, role="viewer") -> Agent:
    a = await db.get(Agent, parse_uuid(agent_id, "Agent"))
    if a is None:
        raise not_found("Agent")
    await membership(db, user, a.workspace_id, role)
    return a


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    a = await _load(db, user, agent_id)
    return agent_out(a, (await _registry_info(db, [a])).get(a.id))


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, body: AgentIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    a = await _load(db, user, agent_id, "agents:write")
    a.name, a.description, a.template = body.name, body.description, body.template
    a.config = _validate_config({**body.config, "template": body.template})  # the draft; published versions never change
    a.draft_contract = body.contract
    await db.commit()
    return agent_out(a, (await _registry_info(db, [a])).get(a.id))


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    a = await _load(db, user, agent_id, "agents:write")
    await audit(db, "agent_deleted", user_id=user.id, workspace_id=a.workspace_id, target_type="agent", target_id=a.id, data={"name": a.name})
    await db.delete(a)
    await db.commit()
