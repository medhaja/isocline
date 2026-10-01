"""First-class artifacts: stored outside workflow state; nodes pass ArtifactRefs.

ArtifactRef = {"artifact_id", "type", "name", "size", "checksum", "mime", "storage_uri": "internal"}.
storage_uri is always the literal "internal" — storage keys and credentials never leave the server."""
from __future__ import annotations

import csv
import hashlib
import io
import mimetypes
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.errors import AppError
from isocline.db.models_v2 import Artifact, ArtifactLineage, ArtifactUsage, WorkspaceQuota
from isocline.services.storage import storage

EXT_KIND = {".csv": "csv", ".json": "json", ".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
            ".webp": "image", ".svg": "image", ".txt": "text", ".md": "report", ".py": "code", ".js": "code", ".ts": "code",
            ".html": "report", ".zip": "zip", ".ipynb": "notebook", ".docx": "document", ".xlsx": "table", ".mp3": "audio",
            ".wav": "audio", ".mp4": "video"}
TEXT_KINDS = {"csv", "json", "text", "report", "code", "notebook"}
DEFAULT_ARTIFACT_QUOTA = 5 * 1024 ** 3


def infer_kind(name: str, mime: str | None = None) -> str:
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext in EXT_KIND:
        return EXT_KIND[ext]
    if mime:
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("text/"):
            return "text"
        if "json" in mime:
            return "json"
    return "other"


def ref(a: Artifact) -> dict:
    return {"artifact_id": str(a.id), "type": a.kind, "name": a.name, "size": a.size_bytes, "checksum": a.checksum,
            "mime": a.mime, "storage_uri": "internal"}


async def check_quota(db: AsyncSession, workspace_id, adding: int) -> None:
    q = await db.get(WorkspaceQuota, workspace_id)
    limit = q.artifact_storage_bytes if q else DEFAULT_ARTIFACT_QUOTA
    used = (await db.execute(select(func.coalesce(func.sum(Artifact.size_bytes), 0)).where(Artifact.workspace_id == workspace_id))).scalar() or 0
    if used + adding > limit:
        raise AppError(429, "artifact_quota_exceeded", f"Artifact storage quota reached ({limit / 1024 ** 3:.1f} GB). Delete artifacts or raise the quota.")


async def create_artifact(db: AsyncSession, *, workspace_id, project_id, name: str, data: bytes, mime: str | None = None,
                          kind: str | None = None, workflow_id=None, run_id=None, node_id: str | None = None,
                          node_key: str | None = None, parents: list[str] | None = None, transformation: str | None = None,
                          meta: dict | None = None, storage_key: str | None = None) -> Artifact:
    await check_quota(db, workspace_id, 0 if storage_key else len(data))
    safe = "".join(ch for ch in (name or "artifact")[-200:] if ch.isprintable() and ch not in "/\\\x00") or "artifact"
    mime = mime or mimetypes.guess_type(safe)[0] or "application/octet-stream"
    ext = "." + safe.rsplit(".", 1)[-1] if "." in safe else ".bin"
    key = storage_key or await storage().put(data, ext)
    a = Artifact(workspace_id=workspace_id, project_id=project_id, workflow_id=workflow_id, run_id=run_id, node_id=node_id,
                 node_key=node_key, name=safe, kind=kind or infer_kind(safe, mime), mime=mime, size_bytes=len(data),
                 checksum=hashlib.sha256(data).hexdigest(), storage_key=key, transformation=transformation, meta=meta or {})
    db.add(a)
    await db.flush()
    for p in dict.fromkeys(parents or []):
        try:
            db.add(ArtifactLineage(artifact_id=a.id, parent_artifact_id=uuid.UUID(str(p)), transformation=transformation))
        except ValueError:
            continue
    await db.flush()
    return a


async def record_usage(db: AsyncSession, artifact_ids: list[str], run_id, node_id: str, node_key: str) -> None:
    for aid in dict.fromkeys(artifact_ids):
        try:
            db.add(ArtifactUsage(artifact_id=uuid.UUID(aid), run_id=run_id, node_id=node_id, node_key=node_key))
        except ValueError:
            continue


async def load_bytes(db: AsyncSession, artifact_id, workspace_id) -> tuple[Artifact, bytes]:
    try:
        a = await db.get(Artifact, uuid.UUID(str(artifact_id)))
    except ValueError:
        a = None
    if a is None or a.workspace_id != workspace_id:
        raise AppError(404, "not_found", "Artifact not found")
    return a, await storage().get(a.storage_key)


def text_of(a: Artifact, data: bytes, max_chars: int = 200_000) -> str:
    if a.kind in TEXT_KINDS or a.mime.startswith("text/"):
        return data[:max_chars * 2].decode("utf-8", "replace")[:max_chars]
    if a.kind in ("pdf", "document"):
        from isocline.services.documents import extract_text
        try:
            ext = "." + a.name.rsplit(".", 1)[-1].lower() if "." in a.name else ".pdf"
            return extract_text(ext, data)[:max_chars]
        except Exception:
            return ""
    return ""


def csv_to_rows(text: str, max_rows: int = 10_000) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for i, r in enumerate(reader):
        if i >= max_rows:
            break
        rows.append({k: _num(v) for k, v in r.items() if k is not None})
    return rows


def _num(v: str | None):
    if v is None:
        return None
    s = v.strip()
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


async def lineage(db: AsyncSession, artifact_id: uuid.UUID, depth: int = 10) -> dict:
    """Ancestors and descendants (bounded)."""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    async def load(aid):
        if str(aid) in nodes:
            return None
        a = await db.get(Artifact, aid)
        if a:
            nodes[str(aid)] = {"id": str(a.id), "name": a.name, "type": a.kind, "node_key": a.node_key,
                               "run_id": str(a.run_id) if a.run_id else None, "created_at": a.created_at.isoformat(),
                               "transformation": a.transformation, "checksum": a.checksum}
        return a

    frontier = [artifact_id]
    await load(artifact_id)
    for _ in range(depth):
        nxt = []
        for aid in frontier:
            for l in (await db.execute(select(ArtifactLineage).where(ArtifactLineage.artifact_id == aid))).scalars():
                edges.append({"from": str(l.parent_artifact_id), "to": str(aid), "transformation": l.transformation})
                if await load(l.parent_artifact_id) is not None:
                    nxt.append(l.parent_artifact_id)
        frontier = nxt
    frontier = [artifact_id]
    for _ in range(depth):
        nxt = []
        for aid in frontier:
            for l in (await db.execute(select(ArtifactLineage).where(ArtifactLineage.parent_artifact_id == aid))).scalars():
                edges.append({"from": str(aid), "to": str(l.artifact_id), "transformation": l.transformation})
                if await load(l.artifact_id) is not None:
                    nxt.append(l.artifact_id)
        frontier = nxt
    uniq = {(e["from"], e["to"]): e for e in edges}
    return {"nodes": list(nodes.values()), "edges": list(uniq.values())}
