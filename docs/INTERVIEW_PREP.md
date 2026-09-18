# Interview Prep: RAG API

These are questions an interviewer is likely to ask about this project, with model answers tied to the actual code. Read [`BUILD_LOG.md`](BUILD_LOG.md) first for the step-by-step build, and [`TECH_STACK.md`](TECH_STACK.md) for the professional reasons behind every technology choice. Questions such as "Why did you choose X over Y?" are answered there in depth.

Answer in your own words. The goal is to understand *why*, not to memorise. Questions marked **(Task N)** cover parts designed in `SPEC.md` but not built yet. The answers describe the planned design and will be updated once the code exists.

---

## 1. The pitch

**Q: Describe this project in 30 seconds.**

> It's a FastAPI backend for retrieval-augmented generation. You upload text documents. The service splits them into overlapping chunks, embeds each chunk locally with a small ONNX model, and stores the vectors in ChromaDB. You can then search semantically, or ask a question: the service retrieves the most relevant chunks and gives them to an LLM, which answers with citations. The LLM is configurable (OpenAI, Claude, or any OpenAI-compatible API such as Gemini or Ollama), and embeddings run locally, so ingest and search cost nothing. It has input validation, clear error mapping, request-id logging, strict typing, tests and CI.

**Q: Walk me through what happens when someone calls `/ask`.** (Task 5)

> The question is embedded with the same model used for the documents. Chroma returns the `top_k` nearest chunks by cosine similarity. Chunks scoring below a relevance threshold are dropped. If nothing is left, we return "not enough information" without calling the LLM, which saves cost and avoids hallucination. Otherwise we build a prompt with the chunks as numbered sources plus the question, call the LLM with a system prompt that says to answer only from the sources and cite them as `[n]`, and return the answer together with the sources used.

---

## 2. RAG fundamentals

**Q: What is RAG, and why use it instead of just asking the LLM?**

> An LLM only knows its training data, which is frozen at a cutoff and doesn't include your private documents. RAG retrieves relevant text at question time and puts it in the prompt, so answers can be grounded in current, private data. It also makes answers checkable, because you can show the sources. Compared with fine-tuning, it's cheaper, updates instantly when documents change, and doesn't need retraining.

**Q: What are the main ways a RAG system fails?**

> 1. **Retrieval misses:** the right chunk isn't in the top-k. Causes include bad chunking, a weak embedding model, or the query using different words than the document.
> 2. **Noise:** irrelevant chunks get retrieved, and the LLM uses them anyway.
> 3. **Hallucination:** the LLM ignores the context, or fills gaps from its own memory.
> 4. **Context limits:** too many or too large chunks for the prompt budget.
>
> Mitigations in this project: chunking on natural boundaries with overlap, a relevance threshold, a strict system prompt with citations, and returning sources so users can verify. Next steps would be hybrid search (keyword plus vector), reranking, and an evaluation set.

**Q: How would you evaluate whether this RAG system is good?**

> Build a small labelled set of questions with known answers and the chunks that contain them. Measure retrieval with recall@k (is the right chunk in the top k?) and MRR. Measure generation for faithfulness (is every claim supported by the sources?) and answer relevance, using human review or an LLM-as-judge. Re-run the set whenever you change chunk size, the model or the prompt. An evaluation harness is listed as a next step in `SPEC.md`.

---

## 3. Chunking

**Q: Why chunk documents? Why not embed the whole document?**

> One vector for a long document averages many topics into one point, so it matches nothing precisely. Search also needs to return the specific passage that answers the question, and prompts have a token budget. Chunks of a few hundred characters keep each vector focused.

**Q: How does your chunker work?**

> It's a recursive character splitter. It tries paragraph breaks first, then line breaks, then sentence ends, then spaces, and hard-cuts only text with no spaces at all. Pieces are packed into chunks up to `CHUNK_SIZE` characters. Each new chunk starts with the tail of the previous one, up to `CHUNK_OVERLAP` characters, measured in whole pieces so a sentence is never cut mid-way for overlap.

**Q: Why overlap?**

> If an important sentence falls on a chunk boundary, its context would be split across two chunks and neither might match well. Overlap repeats a little context so each chunk stands on its own. The cost is some duplicate storage and embedding work. Our default is 15% (120 of 800 characters).

**Q: How would you choose chunk size?**

> It's a tradeoff. Small chunks give precise matches but lose context. Large chunks keep context but dilute the vector and use more prompt budget. Start around 500–1,000 characters (or 200–400 tokens), then tune with an evaluation set. It's configurable here through `.env`.

**Q: Characters or tokens?**

> Characters are simple and model-independent, which suits a PoC. Tokens match what models actually count, so token-based sizing is more precise for prompt budgets. An upgrade would be to measure with the embedding model's tokenizer.

---

## 4. Embeddings and vector search

**Q: What is an embedding?**

> A fixed-length vector of numbers produced by a model, where texts with similar meaning land close together. We use `BAAI/bge-small-en-v1.5`, which gives 384 dimensions.

**Q: Why a local embedding model instead of OpenAI embeddings?**

> Four reasons: zero cost, no API key, works offline, and ingest and search don't depend on an external service. bge-small is a strong small model and runs on CPU through ONNX. The tradeoff is lower quality than large hosted models on some tasks. Note that Claude has no embeddings API, so a Claude-based stack needs another embedding source anyway.

**Q: Could you switch embedding models later?**

> Not without re-embedding everything. Vectors from different models live in different spaces, and often have different dimensions, so they can't be compared. That's why the embedding model should be pinned, and changing it means rebuilding the collection. It's also why embeddings are independent of the LLM choice here: switching LLMs never forces re-embedding.

**Q: What is cosine similarity? Why cosine?**

> It's the cosine of the angle between two vectors, which measures direction and ignores length. Text embedding models are trained so that direction carries the meaning, and bge produces normalised vectors, so cosine is the standard metric. Chroma returns cosine *distance* (1 minus similarity), and we convert it back to a similarity score where higher means more relevant.

**Q: Do queries and documents get embedded the same way?**

> It depends on the model. Some models (E5, and older bge versions) expect a prefix on queries, such as bge's "Represent this sentence for searching relevant passages:". For bge-small-en-v1.5, BAAI made that instruction optional. We use fastembed's `query_embed()` for queries, and we verified that for this model it produces exactly the same vector as `embed()`: it adds no prefix. Whether adding the instruction manually improves our retrieval is something to *measure* on real data, not assume. That's done at the calibration checkpoint.
>
> A good follow-up point for interviews: "I initially assumed `query_embed` added the prefix, tested it, and found it didn't. So I check library behaviour empirically rather than trusting documentation or memory."

**Q: How does a vector database find nearest neighbours quickly?**

> Comparing against every vector is O(n). Chroma uses an HNSW index (Hierarchical Navigable Small World), a layered graph that finds *approximate* nearest neighbours in roughly logarithmic time. It trades a tiny amount of accuracy for large speed gains.

**Q: Why Chroma? Would you use it in production?**

> For a PoC, embedded Chroma is ideal: it runs in-process, persists to disk, needs no server and no key. For production at scale, with many writers and replicas, I'd consider Chroma in server mode, Qdrant, pgvector (if Postgres is already used) or a managed service. The `VectorStore` class wraps Chroma behind a small interface, so swapping it touches one module.

**Q: How does ingestion work, end to end?** (Task 3)

> `POST /documents` validates the body with Pydantic, checks the size limit, splits the text with `chunk_text`, embeds all chunks in one batch, and stores them in Chroma with ids `{document_id}:{i}` and metadata holding `document_id`, `chunk_index`, `title` and the client's own keys. It returns 201 with the id, title, chunk count and character count.

**Q: What happens if a client uploads the same document twice?**

> Re-ingesting an id replaces it, so the operation is idempotent. The store first deletes every chunk whose metadata has that `document_id`, then adds the new ones. Deleting by metadata matters: if I only overwrote ids computed from the new chunk count, a shorter new version would leave the old tail chunks behind as orphans that still appear in search. The route also embeds *before* deleting, so a failed embedding keeps the old version intact. It's not fully atomic, though: Chroma has no transactions, so a crash between delete and add would lose the document. For a PoC that's acceptable; production would version chunks or use a store with transactions.

**Q: Why does a too-large document return 413 and not 422?**

> 413 Content Too Large is the precise HTTP status for "the payload is too big", and the spec asks for it. A Pydantic `max_length` would give 422, and the limit comes from runtime settings the schema can't see, so the route checks it and raises `AppError(413)`.

**Q: Why restrict metadata to flat scalar values?**

> Chroma stores only `str`, `int`, `float` and `bool` metadata values, and those are also what exact-match filters need. Validating at the API edge turns a would-be storage error (a 500) into a clear 422. Keys are restricted to a safe pattern, and `document_id`, `chunk_index` and `title` are reserved because the server writes them itself; letting a client override them would break re-ingest and citations.

**Q: Why is there a `MIN_RELEVANCE` threshold?** (Task 5)

> Nearest neighbours are always returned, even when nothing is actually relevant. Without a threshold, an off-topic question still gets "context", and the LLM may produce a confident wrong answer. The threshold lets us say "not enough information" and skip the LLM call. The value is calibrated from measured scores, because small embedding models give unrelated text fairly high similarity.

---

## 5. LLM integration and prompting (Task 5)

**Q: How do you support several LLM providers without a mess?**

> Two small classes with the same method: `OpenAICompatibleLLM` and `AnthropicLLM`. A `create_llm(settings)` function picks one with an `if`. Gemini and Ollama expose OpenAI-compatible endpoints, so they reuse the OpenAI class with a different `base_url`. No plugin registry, because two implementations don't justify one.

**Q: How do you reduce hallucination in the prompt?**

> The system prompt says: answer only from the provided sources, cite them as `[n]`, and say you don't know when the sources don't contain the answer. Sources are numbered and wrapped in tags. We also skip the LLM entirely when retrieval finds nothing relevant.

**Q: What is prompt injection, and how does this project handle it?**

> A document can contain text like "ignore previous instructions and…". Since retrieved text goes into the prompt, it could hijack the model. Mitigations here: context is wrapped in clearly delimited `<source>` blocks, and the system prompt tells the model to treat them as data, never as instructions. That reduces the risk but can't fully prevent it. For higher stakes you'd add output checks, restrict what the model can do (no tools here), and filter what gets ingested.

**Q: How do you handle LLM API errors?**

> Each provider's SDK exceptions are translated into one `LLMError` with an HTTP status: auth or bad request becomes 502 (the upstream rejected us), rate limit or overload becomes 503 (try later), timeout or connection failure becomes 504, and a missing key becomes 503 "not configured". The client gets a clear status, and routes don't need provider-specific code. The SDKs already retry transient errors (429, 5xx) with backoff, so we don't add another retry layer.

**Q: What's the `fallbacks` parameter on the Claude call?**

> Claude Opus 5 can decline a request through its safety classifiers (`stop_reason: "refusal"`). With `fallbacks="default"` and the `server-side-fallback-2026-07-01` beta, Anthropic re-runs a declined request on a recommended fallback model server-side. We still check `stop_reason` and return 502 if it's a refusal anyway.

---

## 6. FastAPI

**Q: Why FastAPI?**

> Type hints drive everything: request validation, serialisation and auto-generated OpenAPI docs at `/docs`. It has built-in dependency injection, supports both sync and async, is fast, and is the de facto standard for Python AI backends.

**Q: `def` vs `async def` for route handlers. Which did you use and why?**

> Plain `def`. FastAPI runs `def` handlers in a thread pool, so blocking calls (Chroma, fastembed on the CPU, the synchronous SDK clients) don't freeze the event loop. With `async def`, every call inside must be non-blocking and awaited. One blocking call there stalls *all* requests. Choose based on what the code inside actually does.

**Q: What is dependency injection in FastAPI? Show an example from your code.**

> A route declares what it needs, and FastAPI provides it. In `app/api/deps.py`, `get_store(request)` returns the store from `app.state`, and `StoreDep = Annotated[VectorStore, Depends(get_store)]`. Any route with a `store: StoreDep` parameter receives it. Routes are decoupled from construction, which makes testing easy.

**Q: What is the lifespan function for?**

> It runs startup code before the app serves requests and shutdown code after. We load the embedding model and open the Chroma client there, once, and store them on `app.state`. It replaces the deprecated `@app.on_event("startup")`.

**Q: Why an app factory (`create_app`) with `--factory`?**

> Tests can build a fresh, isolated app with fake components. Importing the module has no side effects: no `.env` read, no model loaded. Different configurations can be created in the same process. `uvicorn app.main:create_app --factory` calls the function to get the app.

**Q: What does `response_model` do?**

> FastAPI validates the handler's return value against the Pydantic model, drops any fields not in the model (preventing accidental data leaks), and documents the schema in OpenAPI.

**Q: How are validation errors returned?**

> FastAPI validates request bodies against the Pydantic models automatically and returns 422 with a list of which fields failed and why. We use Pydantic constraints (lengths, ranges, regex patterns) to enforce the spec's limits at the edge.

**Q: What is middleware? What does yours do?**

> Code that wraps every request. Ours assigns a request id (reusing a safe client-supplied one), puts it in a `ContextVar` so every log line includes it, returns it in `X-Request-ID`, and logs method, path, status and duration. It's written as raw ASGI rather than `BaseHTTPMiddleware` so streamed responses pass through without buffering.

**Q: How do you avoid leaking internal errors?**

> A catch-all exception handler logs the full traceback and returns only `{"detail": "Internal server error"}` with a 500. Expected failures use `AppError` with a safe message and a proper status.

---

## 7. Python and Pydantic

**Q: How is configuration managed?**

> With `pydantic-settings`: a typed `Settings` class reads environment variables and `.env`, converts types, and validates ranges and cross-field rules (overlap smaller than size) at startup. Secrets stay in `.env`, which is gitignored, and `.env.example` documents every option. Bad configuration fails fast with a clear error instead of breaking at request time.

**Q: What is a `Protocol`, and why is `Embedder` one?**

> `typing.Protocol` defines an interface by shape (structural typing). Any class with `model_name`, `embed_documents` and `embed_query` counts as an `Embedder`, with no inheritance needed. The real `FastEmbedEmbedder` and the test `FakeEmbedder` both satisfy it, and mypy checks that.

**Q: What is a `ContextVar`?**

> A variable whose value is local to the current execution context (an async task or thread). Concurrent requests each see their own request id without passing it through every function.

---

## 8. Testing

**Q: How did you test this without paying for API calls?**

> With fakes. A deterministic `FakeEmbedder` hashes words into a vector: it's fast, needs no download, yet shared words still produce similar vectors, so ranking tests are meaningful. The LLM is replaced by a fake that records its prompt (Task 5). Chroma runs in memory with a unique collection per test. Paid APIs are never called in tests. One manual live check against the real model and Gemini confirms the real wiring.

**Q: Unit vs integration tests. What's the split here?**

> Unit tests (`tests/unit/`) cover single pieces: settings validation, the chunker, and filter-clause building. Integration tests (`tests/integration/`) go through HTTP with `TestClient` and exercise routes, validation, error mapping and middleware together.

**Q: What is TDD? Did you use it?**

> Write a failing test first (red), write the minimum code to pass it (green), then clean up (refactor). The chunker was built that way: its tests define the behaviour (size limits, no lost words, overlap, boundary preference, invalid input).

**Q: Why run a live check if the tests pass?**

> Tests with fakes prove our logic, not the integration. The live check caught real-world facts that fakes can't, such as Gemini retiring `gemini-2.5-*` models (404 for new users) and the real model download size.

---

## 9. Tooling and delivery

**Q: What quality gates does the project have?**

> ruff for lint and format, mypy in strict mode for types, and pytest for behaviour. They run locally through pre-commit hooks on every commit and in GitHub Actions CI on every push or PR. pre-commit also blocks committing private keys.

**Q: Why uv?**

> It's fast, and it manages the Python version, the virtualenv, dependencies and a lockfile in one tool. `uv.lock` makes installs reproducible, so CI and Docker get exactly the versions tested locally.

**Q: How would you deploy this?** (Task 10)

> A Docker image based on `python:3.12-slim`, dependencies installed from `uv.lock` without dev tools, running as a non-root user, with a healthcheck on `/health`. Volumes persist `data/` (Chroma and the model cache). Configuration comes from environment variables. For production: multiple replicas need a shared vector store (Chroma server mode or Qdrant) instead of the embedded one.

---

## 10. Design tradeoffs and "what would you improve?"

**Q: What are the limitations of this PoC?**

> No auth or rate limiting. Embedded Chroma is single-process. `GET /documents` scans chunk metadata, so it's O(chunks). Text formats only (no PDF or DOCX). No evaluation harness. The Claude path is unit-tested with a fake client but not verified live, since no key was available.

**Q: How would you scale it?**

> Move the vector store to a server (Qdrant, pgvector or Chroma server) so API replicas share it. Run ingestion as a background job queue for large documents. Batch embeddings. Cache embeddings for repeated queries. Add auth and per-client rate limits. Add observability: metrics on latency, retrieval scores and LLM tokens and cost.

**Q: How would you improve answer quality?**

> Hybrid retrieval (BM25 keyword plus vectors), a cross-encoder reranker on the top ~20 results, token-aware chunking with document titles or headings prepended to chunks, query rewriting, and an evaluation set to measure each change.

**Q: What would you do differently if starting over?**

> Honest answers score well here. For example: "I'd build the evaluation set earlier, because chunk size and threshold choices are guesses until you can measure them."

---

## 11. Security

**Q: What security measures are in place?**

> Secrets live in `.env` (gitignored), with a pre-commit hook that blocks committed private keys. Every input is validated at the edge (types, lengths, id patterns, metadata key rules, size limit returning 413). There's a generic 500 with no internals, a prompt-injection guard in the system prompt, and the Docker container runs as non-root. Missing: auth, rate limiting and CORS policy. Those are next steps.

**Q: Any data-privacy concern with your setup?**

> Yes. On Gemini's free tier, Google may use prompts and responses to improve its products. So no confidential documents should be ingested while using a free-tier key. It's documented in `.env.example` and the README. Local Ollama avoids the issue entirely.
