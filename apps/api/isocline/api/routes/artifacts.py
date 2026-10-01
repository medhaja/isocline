from __future__ import annotations

import base64

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, load_project, membership, parse_uuid
from isocline.core.errors import not_found
from isocline.db.models import User
from isocline.db.models_v2 import Artifact, ArtifactUsage
from isocline.db.session import get_db

router = APIRouter(tags=["artifacts"])


def art_out(a: Artifact) -> dict:
    # storage_key is internal and never returned
    return dump(a, "id", "project_id", "name", "kind", "mime", "size_bytes", "checksum", "node_key", "node_id", "transformation", "meta",
                "created_at", workflow_id=str(a.workflow_id) if a.workflow_id else None, run_id=str(a.run_id) if a.run_id else None)


@router.get("/projects/{project_id}/artifacts")
async def list_artifacts(project_id: str, q: str | None = None, kind: str | None = None, workflow_id: str | None = None,
                         run_id: str | None = None, limit: int = 100, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id)
    stmt = select(Artifact).where(Artifact.project_id == p.id)
    if q:
        stmt = stmt.where(or_(Artifact.name.ilike(f"%{q}%"), Artifact.node_key.ilike(f"%{q}%")))
    if kind:
        stmt = stmt.where(Artifact.kind == kind)
    if workflow_id:
        stmt = stmt.where(Artifact.workflow_id == parse_uuid(workflow_id))
    if run_id:
        stmt = stmt.where(Artifact.run_id == parse_uuid(run_id))
    rows = (await db.execute(stmt.order_by(Artifact.created_at.desc()).limit(min(limit, 500)))).scalars().all()
    return [art_out(a) for a in rows]


async def _load(db, user, artifact_id) -> Artifact:
    a = await db.get(Artifact, parse_uuid(artifact_id, "Artifact"))
    if a is None:
        raise not_found("Artifact")
    await membership(db, user, a.workspace_id)  # artifact access follows workspace membership
    return a


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.services.artifacts import lineage
    a = await _load(db, user, artifact_id)
    consumers = (await db.execute(select(ArtifactUsage).where(ArtifactUsage.artifact_id == a.id))).scalars().all()
    return {**art_out(a), "consumers": [{"run_id": str(u.run_id), "node_key": u.node_key, "at": u.created_at.isoformat()} for u in consumers],
            "lineage": await lineage(db, a.id)}


@router.get("/artifacts/{artifact_id}/preview")
async def preview(artifact_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.services.artifacts import csv_to_rows, text_of
    from isocline.services.storage import storage
    a = await _load(db, user, artifact_id)
    data = await storage().get(a.storage_key)
    if a.kind == "image" and a.size_bytes <= 4 * 1024 * 1024 and not a.mime.endswith("svg+xml"):
        return {"type": "image", "data_url": f"data:{a.mime};base64,{base64.b64encode(data).decode()}"}
    if a.kind == "csv":
        rows = csv_to_rows(data.decode("utf-8", "replace"), 50)
        return {"type": "table", "rows": rows, "truncated": len(rows) == 50}
    text = text_of(a, data, 64_000)
    return {"type": "text", "text": text, "truncated": len(text) >= 64_000} if text else {"type": "binary", "note": "No preview for this file type"}


@router.get("/artifacts/{artifact_id}/download")
async def download(artifact_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.services.storage import storage
    a = await _load(db, user, artifact_id)
    data = await storage().get(a.storage_key)
    safe = a.name.replace('"', "")
    return Response(data, media_type="application/octet-stream" if a.mime.startswith(("text/html", "image/svg")) else a.mime,
                    headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"})


@router.delete("/artifacts/{artifact_id}", status_code=204)
async def delete_artifact(artifact_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from isocline.db.models_v2 import ArtifactLineage
    from sqlalchemy import delete as sdel
    a = await _load(db, user, artifact_id)
    await membership(db, user, a.workspace_id, "editor")
    await db.execute(sdel(ArtifactLineage).where(or_(ArtifactLineage.artifact_id == a.id, ArtifactLineage.parent_artifact_id == a.id)))
    await db.execute(sdel(ArtifactUsage).where(ArtifactUsage.artifact_id == a.id))
    shared = (await db.execute(select(Artifact.id).where(Artifact.storage_key == a.storage_key, Artifact.id != a.id))).first()
    if not shared and not a.meta.get("document_id"):
        from isocline.services.storage import storage
        await storage().delete(a.storage_key)
    await db.delete(a)
    await db.commit()
