# Research Prompt: Best RAG Architecture for Multi-Agent Code Generation

## Context

I am building a multi-agent AI software company simulation. Here is the exact setup:

- ~9 AI agents (software engineers, QA, architects) run in parallel each "sprint"
- Each sprint agents write code files to a shared output directory (`company_output/code/`)
- After each sprint: ~50-200 Python, TypeScript, YAML, and Markdown files exist
- Before writing any file, agents must search existing code to avoid reimplementing things
- Agents ask natural language queries like:
  - "authentication token validation"
  - "WebSocket connection handler"
  - "Kanban task database model"
  - "does an auth middleware already exist?"
- The codebase grows by ~10-30 files per sprint over 10-15 sprints
- Embedding model available: Gemini `text-embedding-004`
- LLM: Gemini Flash (small, fast)
- Runtime: Python, on a single machine, no external vector DB infrastructure

## Current implementation (basic)

- Chunk Python files by function/class boundary, other files by fixed 60-line windows
- Embed each chunk with `text-embedding-004`
- Store as a numpy matrix + pickle file
- Query: embed query → cosine similarity → return top 5 chunks
- Rebuild index after each sprint (incremental: only embed new/changed chunks)

## Research questions

Please research and answer the following:

### 1. Chunking strategy
What is the best chunking strategy for a mixed codebase (Python + TypeScript + YAML + Markdown)?
- Is function/class boundary chunking better than fixed-size for retrieval accuracy?
- Should chunks include surrounding context (e.g. imports at top of file, class name for a method)?
- What is the optimal chunk size (tokens) for code retrieval with `text-embedding-004`?
- Should we use overlapping chunks? If so, what overlap ratio?

### 2. Embedding and indexing
- Is `text-embedding-004` a good choice for code retrieval, or is a code-specific model (e.g. `code-gecko`, `codebert`) significantly better?
- For ~5,000-20,000 chunks (10-15 sprints × 200 files × avg 5 chunks/file), is a flat numpy cosine search fast enough, or should we use an approximate nearest neighbor index (FAISS, HNSW)?
- Should we embed the raw code, or preprocess it (strip comments, normalize whitespace, add a natural language summary prefix)?

### 3. Retrieval strategy
- Is pure dense retrieval (embedding similarity) the best approach, or should we use:
  - **Hybrid retrieval**: dense + BM25 keyword search combined?
  - **Reranking**: retrieve top-20 by embedding, rerank with a cross-encoder?
  - **HyDE (Hypothetical Document Embeddings)**: generate a hypothetical code snippet for the query, then search?
- For queries like "does an auth middleware already exist?" — what retrieval approach handles existence questions best?
- How many chunks should be returned (top-K)? What is the right K for a ~1000-token context budget per search result?

### 4. Index freshness
- We currently rebuild the index after each sprint (not during). Is within-sprint real-time indexing feasible and worth it given parallel agent execution?
- What is the fastest way to do incremental updates (new chunks only) without full reindex?

### 5. Metadata filtering
- Should chunks be tagged with metadata (filename, sprint number, agent that wrote it, function name)?
- Would filtering by metadata (e.g. "only search files from the last 2 sprints") improve precision?
- How should metadata be incorporated — pre-filter, post-filter, or embedded into the chunk text?

### 6. Alternative approaches
- Is RAG even the right tool here, or would a **code graph** (AST-based, tracking imports/exports/function calls) be more precise for "does X already exist?" queries?
- Would a simple **inverted index** (keyword search over function names, class names, file names) outperform embedding search for this specific use case?
- Is there a hybrid approach combining a lightweight symbol index (function/class names) with embedding search for semantic queries?

## Constraints

- Must work fully offline/locally after initial embedding API calls
- No managed vector DB (no Pinecone, Weaviate, etc.) — file-based only
- Python implementation
- Embedding API calls have cost — minimize redundant re-embeddings
- Query latency budget: <2 seconds per search (agents call this during their task)
- Index build budget: <30 seconds after each sprint

## Expected output

For each research question above, provide:
1. The recommended approach with justification
2. Any relevant benchmarks or papers comparing approaches
3. A concrete Python implementation recommendation (library, data structure, algorithm)
4. Any tradeoffs to be aware of for this specific use case

Finally, provide a **recommended complete RAG architecture** for this exact use case, combining the best answers from all questions above into a coherent system design.
