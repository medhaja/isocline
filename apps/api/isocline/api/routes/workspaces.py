from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, load_project, membership, parse_uuid
from isocline.db.models import Project, Run, User, Workflow, Workspace, WorkspaceMember
from isocline.db.session import get_db
from isocline.services.audit import audit

router = APIRouter(tags=["workspaces"])


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


@router.get("/workspaces")
async def list_workspaces(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Workspace, WorkspaceMember.role).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                             .where(WorkspaceMember.user_id == user.id).order_by(Workspace.created_at))).all()
    return [dump(w, "id", "name", "created_at", role=r) for w, r in rows]


@router.post("/workspaces", status_code=201)
async def create_workspace(body: WorkspaceIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    ws = Workspace(name=body.name, owner_id=user.id)
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    await audit(db, "workspace_created", user_id=user.id, workspace_id=ws.id, target_type="workspace", target_id=ws.id)
    await db.commit()
    return dump(ws, "id", "name", "created_at", role="owner")


@router.patch("/workspaces/{workspace_id}")
async def rename_workspace(workspace_id: str, body: WorkspaceIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id, "admin")
    ws = await db.get(Workspace, parse_uuid(workspace_id))
    ws.name = body.name
    await db.commit()
    return dump(ws, "id", "name", "created_at")


@router.get("/workspaces/{workspace_id}/members")
async def members(workspace_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id)
    rows = (await db.execute(select(WorkspaceMember, User).join(User, User.id == WorkspaceMember.user_id)
                             .where(WorkspaceMember.workspace_id == parse_uuid(workspace_id)))).all()
    return [{"user_id": str(u.id), "email": u.email, "name": u.name, "role": m.role} for m, u in rows]


@router.get("/workspaces/{workspace_id}/projects")
async def list_projects(workspace_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id)
    wid = parse_uuid(workspace_id)
    projects = (await db.execute(select(Project).where(Project.workspace_id == wid).order_by(Project.created_at.desc()))).scalars().all()
    wf_counts = dict((await db.execute(select(Workflow.project_id, func.count(Workflow.id)).join(Project, Project.id == Workflow.project_id)
                                       .where(Project.workspace_id == wid).group_by(Workflow.project_id))).all())
    run_counts = dict((await db.execute(select(Run.project_id, func.count(Run.id)).where(Run.workspace_id == wid)
                                        .group_by(Run.project_id))).all())
    return [dump(p, "id", "workspace_id", "name", "description", "created_at",
                 workflow_count=wf_counts.get(p.id, 0), run_count=run_counts.get(p.id, 0)) for p in projects]


@router.post("/workspaces/{workspace_id}/projects", status_code=201)
async def create_project(workspace_id: str, body: ProjectIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await membership(db, user, workspace_id, "editor")
    p = Project(workspace_id=parse_uuid(workspace_id), name=body.name, description=body.description)
    db.add(p)
    await db.flush()
    await audit(db, "project_created", user_id=user.id, workspace_id=p.workspace_id, target_type="project", target_id=p.id)
    await db.commit()
    return dump(p, "id", "workspace_id", "name", "description", "created_at", workflow_count=0, run_count=0)


@router.get("/projects/{project_id}")
async def get_project(project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id)
    return dump(p, "id", "workspace_id", "name", "description", "created_at")


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, body: ProjectPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id, "editor")
    if body.name is not None:
        p.name = body.name
    if body.description is not None:
        p.description = body.description
    await db.commit()
    return dump(p, "id", "workspace_id", "name", "description", "created_at")


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id, "admin")
    await audit(db, "project_deleted", user_id=user.id, workspace_id=p.workspace_id, target_type="project", target_id=p.id)
    await db.delete(p)
    await db.commit()
