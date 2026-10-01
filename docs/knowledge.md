# Knowledge bases

Per project: **create** a knowledge base (`chunk_size`, `chunk_overlap`) → **upload** documents (PDF, DOCX, text,
Markdown, CSV, JSON; ≤ `ISOCLINE_MAX_UPLOAD_MB`) → the `ingest` queue extracts text, chunks it and embeds the chunks
into PostgreSQL (`document_chunks.embedding`, pgvector, HNSW cosine index) → documents become `ready`. **Reprocess** a
document after changing settings; delete removes its chunks.

Use it: attach knowledge bases to an agent (`knowledge_base_ids`) — relevant passages are retrieved before the model call —
or give the agent the `vector_search` tool to search itself, or use a `tool_vector_search` node. Test retrieval with
`POST /api/v1/knowledge-bases/{id}/search {"query", "top_k"}`.

**Embeddings** (`ISOCLINE_EMBEDDING_PROVIDER`): `hashing` (default; built-in, no API, **lexical** — keyword-level
retrieval), `ollama` (e.g. `nomic-embed-text` via `ISOCLINE_EMBEDDING_BASE_URL`/`_MODEL`), `openai_compatible` (any
`/v1/embeddings`). `ISOCLINE_EMBEDDING_DIM` must match the model (default 1536); changing it requires a new
embedding column — choose before ingesting. No external vector database is needed.

Verified live: upload → ingest → the refund passage ranked first for a refund question (`examples/05-rag`).
