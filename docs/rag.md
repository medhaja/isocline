# RAG

Retrieval-augmented generation in Isocline is an agent node with knowledge bases attached (automatic retrieval before
the call, recorded in the node trace) or with the `vector_search` tool (the model decides when to search). Setup, file
types and embedding providers: [knowledge.md](knowledge.md). Example: [`examples/05-rag`](../examples/05-rag/).

Retrieval quality depends on the embedding provider: the default `hashing` embeddings match keywords, not meaning.
Configure Ollama or an OpenAI-compatible embedding model for semantic retrieval.
