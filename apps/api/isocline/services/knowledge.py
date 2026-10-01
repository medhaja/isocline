"""Knowledge-base ingestion and retrieval (pgvector)."""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.db.models import Document, DocumentChunk, KnowledgeBase

from .documents import chunk_text, extract_text
from .embeddings import cosine, embed
from .storage import storage


async def ingest_document(db: AsyncSession, doc: Document) -> None:
    kb = await db.get(KnowledgeBase, doc.knowledge_base_id) if doc.knowledge_base_id else None
    doc.status = "processing"
    await db.commit()
    try:
        data = await storage().get(doc.storage_key)
        ext = "." + doc.filename.rsplit(".", 1)[-1].lower()
        text = extract_text(ext, data)
        if not text.strip():
            raise ValueError("No extractable text found (scanned PDFs need OCR before upload)")
        if kb:
            chunks = chunk_text(text, kb.chunk_size, kb.chunk_overlap)
            vectors = await embed(chunks)
            await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
            for i, (c, v) in enumerate(zip(chunks, vectors)):
                db.add(DocumentChunk(document_id=doc.id, knowledge_base_id=kb.id, idx=i, content=c, embedding=v,
                                     meta={"filename": doc.filename, "chunk": i}))
            doc.chunk_count = len(chunks)
        doc.status = "ready"
        doc.error = None
    except Exception as e:  # recorded on the document, surfaced in the UI
        doc.status = "failed"
        doc.error = str(e)[:1000]
    await db.commit()


async def retrieve(db: AsyncSession, kb_ids: list[str], query: str, top_k: int = 5) -> list[dict]:
    if not kb_ids or not query.strip():
        return []
    ids = [uuid.UUID(str(k)) for k in kb_ids]
    [qv] = await embed([query])
    if db.bind.dialect.name == "postgresql":
        dist = DocumentChunk.embedding.cosine_distance(qv)
        rows = (await db.execute(
            select(DocumentChunk, dist.label("d")).where(DocumentChunk.knowledge_base_id.in_(ids)).order_by(dist).limit(top_k)
        )).all()
        return [{"content": c.content, "score": round(1 - float(d), 4), "source": c.meta.get("filename"),
                 "chunk": c.idx, "document_id": str(c.document_id)} for c, d in rows]
    rows = (await db.execute(select(DocumentChunk).where(DocumentChunk.knowledge_base_id.in_(ids)))).scalars().all()
    scored = sorted(((cosine(qv, c.embedding), c) for c in rows), key=lambda x: -x[0])[:top_k]
    return [{"content": c.content, "score": round(s, 4), "source": c.meta.get("filename"), "chunk": c.idx,
             "document_id": str(c.document_id)} for s, c in scored]
