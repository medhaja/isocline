from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, load_project
from isocline.db.models import User
from isocline.db.session import get_db
from isocline.services.ai_builder import generate_workflow

router = APIRouter(tags=["ai"])


class ModelRef(BaseModel):
    provider: str
    model: str
    credential_id: str | None = None


class GenerateIn(BaseModel):
    description: str = Field(min_length=5, max_length=5000)
    model: ModelRef  # model that designs the workflow
    agent_model: ModelRef | None = None  # model assigned to generated agents (defaults to `model`)


@router.post("/projects/{project_id}/generate-workflow")
async def generate(project_id: str, body: GenerateIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Returns a PROPOSED graph in the standard schema. Nothing is saved until the user accepts it."""
    p = await load_project(db, user, project_id, "editor")
    return await generate_workflow(db, p.workspace_id, p.id, body.description, body.model.model_dump(),
                                   body.agent_model.model_dump() if body.agent_model else None)
