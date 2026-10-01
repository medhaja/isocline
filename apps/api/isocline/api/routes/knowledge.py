from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.api.deps import current_user, dump, load_kb, load_project, parse_uuid
from isocline.core.config import get_settings
from isocline.core.errors import AppError, bad_request, not_found
from isocline.db.models import Document, KnowledgeBase, User
from isocline.db.session import get_db
from isocline.services.audit import audit
from isocline.services.dispatch import enqueue_ingest
from isocline.services.documents import DocumentError, validate_upload
from isocline.services.knowledge import retrieve
from isocline.services.storage import storage

router = APIRouter(tags=["knowledge"])


class KBIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    chunk_size: int = Field(default=1000, ge=200, le=8000)
    chunk_overlap: int = Field(default=150, ge=0, le=2000)


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)


def kb_out(k: KnowledgeBase, **extra) -> dict:
    return dump(k, "id", "project_id", "name", "description", "chunk_size", "chunk_overlap", "created_at", **extra)


def doc_out(d: Document) -> dict:
    return dump(d, "id", "project_id", "knowledge_base_id", "filename", "mime", "size_bytes", "status", "error", "chunk_count", "created_at")


@router.get("/projects/{project_id}/knowledge-bases")
async def list_kbs(project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id)
    kbs = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.project_id == p.id).order_by(KnowledgeBase.created_at))).scalars().all()
    docs = (await db.execute(select(Document).where(Document.project_id == p.id))).scalars().all()
    counts: dict = {}
    for d in docs:
        counts[d.knowledge_base_id] = counts.get(d.knowledge_base_id, 0) + 1
    return [kb_out(k, document_count=counts.get(k.id, 0)) for k in kbs]


@router.post("/projects/{project_id}/knowledge-bases", status_code=201)
async def create_kb(project_id: str, body: KBIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id, "editor")
    if body.chunk_overlap >= body.chunk_size:
        raise bad_request("Chunk overlap must be smaller than chunk size")
    k = KnowledgeBase(project_id=p.id, **body.model_dump())
    db.add(k)
    await db.commit()
    return kb_out(k, document_count=0)


@router.delete("/knowledge-bases/{kb_id}", status_code=204)
async def delete_kb(kb_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    k, p = await load_kb(db, user, kb_id, "editor")
    docs = (await db.execute(select(Document).where(Document.knowledge_base_id == k.id))).scalars().all()
    for d in docs:
        await storage().delete(d.storage_key)
    await db.delete(k)
    await db.commit()


@router.get("/knowledge-bases/{kb_id}/documents")
async def list_docs(kb_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    k, _ = await load_kb(db, user, kb_id)
    docs = (await db.execute(select(Document).where(Document.knowledge_base_id == k.id).order_by(Document.created_at.desc()))).scalars().all()
    return [doc_out(d) for d in docs]


async def _store_upload(db: AsyncSession, project_id, kb_id, file: UploadFile) -> Document:
    max_mb = get_settings().max_upload_mb
    data = await file.read(max_mb * 1024 * 1024 + 1)
    try:
        ext = validate_upload(file.filename or "upload", file.content_type, data, max_mb)
    except DocumentError as e:
        raise AppError(415 if "Unsupported" in str(e) else 400, "invalid_file", str(e)) from e
    key = await storage().put(data, ext)  # safe, random internal filename
    safe_name = "".join(c for c in (file.filename or "upload")[-200:] if c.isprintable() and c not in '/\\\x00')
    d = Document(project_id=project_id, knowledge_base_id=kb_id, filename=safe_name or f"upload{ext}",
                 mime=file.content_type or "application/octet-stream", size_bytes=len(data), storage_key=key, status="pending")
    db.add(d)
    await db.commit()
    return d


@router.post("/knowledge-bases/{kb_id}/documents", status_code=201)
async def upload_doc(kb_id: str, file: UploadFile = File(...), user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    k, p = await load_kb(db, user, kb_id, "editor")
    d = await _store_upload(db, p.id, k.id, file)
    await audit(db, "document_uploaded", user_id=user.id, workspace_id=p.workspace_id, target_id=d.id, data={"filename": d.filename},
                commit=True)
    enqueue_ingest(str(d.id))
    from isocline.services.triggers import fire_file_triggers
    await fire_file_triggers(db, d)
    return doc_out(d)


@router.post("/projects/{project_id}/documents", status_code=201)
async def upload_project_file(project_id: str, file: UploadFile = File(...), user: User = Depends(current_user),
                              db: AsyncSession = Depends(get_db)):
    """Files for File Input nodes / the File Reader tool (not embedded into a knowledge base)."""
    p = await load_project(db, user, project_id, "editor")
    d = await _store_upload(db, p.id, None, file)
    d.status = "ready"
    await db.commit()
    from isocline.services.triggers import fire_file_triggers
    await fire_file_triggers(db, d)
    return doc_out(d)


@router.get("/projects/{project_id}/documents")
async def list_project_files(project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await load_project(db, user, project_id)
    docs = (await db.execute(select(Document).where(Document.project_id == p.id).order_by(Document.created_at.desc()))).scalars().all()
    return [doc_out(d) for d in docs]


@router.delete("/documents/{document_id}", status_code=204)
async def delete_doc(document_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    d = await db.get(Document, parse_uuid(document_id, "Document"))
    if d is None:
        raise not_found("Document")
    await load_project(db, user, d.project_id, "editor")
    await storage().delete(d.storage_key)
    await db.delete(d)
    await db.commit()


@router.post("/documents/{document_id}/reprocess")
async def reprocess(document_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    d = await db.get(Document, parse_uuid(document_id, "Document"))
    if d is None or d.knowledge_base_id is None:
        raise not_found("Document")
    await load_project(db, user, d.project_id, "editor")
    d.status, d.error = "pending", None
    await db.commit()
    enqueue_ingest(str(d.id))
    return doc_out(d)


@router.post("/knowledge-bases/{kb_id}/search")
async def search(kb_id: str, body: SearchIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    k, _ = await load_kb(db, user, kb_id)
    return {"results": await retrieve(db, [str(k.id)], body.query, body.top_k)}
