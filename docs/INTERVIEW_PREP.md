# Interview Prep: Sourcely

These are questions an interviewer is likely to ask about this project, with model answers tied to the actual code. Read [`BUILD_LOG.md`](BUILD_LOG.md) first for the step-by-step build, and [`TECH_STACK.md`](TECH_STACK.md) for the professional reasons behind every technology choice. Questions such as "Why did you choose X over Y?" are answered there in depth.

Answer in your own words. The goal is to understand *why*, not to memorise. Questions marked **(Task N)** cover parts designed in `SPEC.md` but not built yet. The answers describe the planned design and will be updated once the code exists.

---

## 1. The pitch

**Q: Describe this project in 30 seconds.**

> It's a FastAPI backend for retrieval-augmented generation. You upload text documents. The service splits them into overlapping chunks, embeds each chunk locally with a small ONNX model, and stores the vectors in ChromaDB. You can then search semantically, or ask a question: the service retrieves the most relevant chunks and gives them to an LLM, which answers with citations. The LLM is configurable (OpenAI, Claude, or any OpenAI-compatible API such as Gemini or Ollama), and embeddings run locally, so ingest and search cost nothing. It has input validation, clear error mapping, request-id logging, strict typing, tests and CI.

**Q: Walk me through what happens when someone calls `/ask`.**

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

> It depends on the model. Some models (E5, and older bge versions) expect a prefix on queries, such as bge's "Represent this sentence for searching relevant passages:". For bge-small-en-v1.5, BAAI made that instruction optional. We use fastembed's `query_embed()` for queries, and we verified that for this model it produces exactly the same vector as `embed()`: it adds no prefix. Whether adding the instruction manually improves our retrieval was something to *measure*, not assume. At the calibration checkpoint it widened the gap between relevant and unrelated scores from 0.020 to 0.052, so we now add it to queries only, never to documents.
>
> A good follow-up point for interviews: "I initially assumed `query_embed` added the prefix, tested it, and found it didn't. So I check library behaviour empirically rather than trusting documentation or memory."

**Q: How does a vector database find nearest neighbours quickly?**

> Comparing against every vector is O(n). Chroma uses an HNSW index (Hierarchical Navigable Small World), a layered graph that finds *approximate* nearest neighbours in roughly logarithmic time. It trades a tiny amount of accuracy for large speed gains.

**Q: Why Chroma? Would you use it in production?**

> For a PoC, embedded Chroma is ideal: it runs in-process, persists to disk, needs no server and no key. For production at scale, with many writers and replicas, I'd consider Chroma in server mode, Qdrant, pgvector (if Postgres is already used) or a managed service. The `VectorStore` class wraps Chroma behind a small interface, so swapping it touches one module.

**Q: How does ingestion work, end to end?** (Task 3)

> `POST /documents` validates the body with Pydantic, checks the size limit, splits the text with `chunk_text`, embeds all chunks in one batch, and stores them in Chroma with ids `{document_id}:{i}` and metadata holding `document_id`, `chunk_index`, `title` and the client's own keys. It returns 201 with the id, title, chunk count and character count.

**Q: How do metadata filters work, and why filter inside the search?** (Task 8)

> Filters are validated by Pydantic, then a pure function, `build_where`, turns them into a Chroma `where` clause: document ids become `$in`, each metadata pair an exact `$eq`, joined with `$and`. Chroma applies it during the nearest-neighbour search, so `top_k=4` still returns up to 4 matching chunks. If I filtered the top 4 afterwards, a strict filter could leave nothing even though matching chunks exist further down.

**Q: Why reject unknown fields in the filters object?**

> Pydantic ignores unknown fields by default. For filters that fails open: a typo like `document_id` instead of `document_ids` would give no error and quietly search every document, which for a knowledge base could mean citing the wrong source. `extra="forbid"` turns that into a 422.

**Q: How do you list documents when the vector store only holds chunks?** (Task 7)

> Every chunk carries `document_id`, `chunk_index`, `title` and the client's metadata. Listing reads only the metadata of all chunks, groups them by `document_id` and counts them. It's O(chunks), which I'd call out as a scaling limit: the real fix is a separate documents table, which the product plan puts in Postgres.

**Q: Why check existence before deleting?**

> The spec wants 204 for a real delete and 404 for an unknown id, but Chroma's `delete` doesn't say how many rows it removed. So I fetch at most one chunk id first, with `include=[]` so nothing else comes back. It's not atomic, but a race only means two clients both get 204 for a document that is gone either way.

**Q: How does the file upload endpoint protect the server?** (Task 6)

> It checks cheap things first. The extension must be `.txt` or `.md` (415 otherwise). Then it reads at most 4 bytes per allowed character plus one: UTF-8 uses at most 4 bytes per character, so a bigger file can't be within the limit, and it's rejected with 413 without being loaded whole. Then it decodes UTF-8 (422 if invalid) and applies the same character limit as the JSON route. One honest gap: Starlette spools the whole upload to a temporary file before the route runs, so the request size itself must be capped in front of the app, at the reverse proxy.

**Q: Why `utf-8-sig` and not `utf-8`?**

> `utf-8-sig` also removes a byte order mark, an invisible character some Windows editors put at the start of UTF-8 files. Otherwise the first chunk would start with it. For files without a BOM, both decode the same.

**Q: What happens if a client uploads the same document twice?**

> Re-ingesting an id replaces it, so the operation is idempotent. The store first deletes every chunk whose metadata has that `document_id`, then adds the new ones. Deleting by metadata matters: if I only overwrote ids computed from the new chunk count, a shorter new version would leave the old tail chunks behind as orphans that still appear in search. The route also embeds *before* deleting, so a failed embedding keeps the old version intact. It's not fully atomic, though: Chroma has no transactions, so a crash between delete and add would lose the document. For a PoC that's acceptable; production would version chunks or use a store with transactions.

**Q: Why does a too-large document return 413 and not 422?**

> 413 Content Too Large is the precise HTTP status for "the payload is too big", and the spec asks for it. A Pydantic `max_length` would give 422, and the limit comes from runtime settings the schema can't see, so the route checks it and raises `AppError(413)`.

**Q: Why restrict metadata to flat scalar values?**

> Chroma stores only `str`, `int`, `float` and `bool` metadata values, and those are also what exact-match filters need. Validating at the API edge turns a would-be storage error (a 500) into a clear 422. Keys are restricted to a safe pattern, and `document_id`, `chunk_index` and `title` are reserved because the server writes them itself; letting a client override them would break re-ingest and citations.

**Q: Walk me through `POST /search`.** (Task 4)

> Pydantic validates the body: the query is 1 to 2,000 non-blank characters and `top_k` is 1 to 20, defaulting to a setting. The route embeds the query with the same model used for the documents, asks the vector store for the `top_k` nearest chunks, and converts Chroma's cosine distance to similarity with `1 - distance`. It returns each hit with its document id, chunk index, title, text, score and the client's metadata, sorted by score. It never needs the LLM, so it works without an API key.

**Q: Why must the query use the same embedding model as the documents?**

> Each model defines its own vector space. Comparing a vector from one model with vectors from another is meaningless, even when the dimensions happen to match. That's why the embedder is one shared component, injected into both the ingest and the search routes.

**Q: What did real scores look like, and what does that mean?** (Task 4)

> On a small live test, relevant documents scored about 0.67 to 0.71, and unrelated ones 0.40 to 0.63. An off-topic question still got a "best" hit at 0.475. Nearest-neighbour search always returns something, and small models give unrelated text fairly high similarity. So a relevance threshold is needed before answering, and it has to be chosen from measured data, not guessed.

**Q: An empty store: error or empty list?**

> An empty list with 200. Searching an empty index isn't a client mistake, and the spec says so. I checked Chroma's behaviour rather than assuming: `n_results=0` raises a `TypeError`, but an empty collection queried with `n_results` of 1 or more returns an empty result. Validation guarantees `top_k >= 1`, so the empty case needs no special branch.

**Q: Why is there a `MIN_RELEVANCE` threshold?**

> Nearest neighbours are always returned, even when nothing is actually relevant. Without a threshold, an off-topic question still gets "context", and the LLM may produce a confident wrong answer. The threshold lets us say "not enough information" and skip the LLM call. The value is calibrated from measured scores, because small embedding models give unrelated text fairly high similarity.

**Q: How did you choose 0.58?**

> With a small labelled set: 6 documents, 14 questions they answer and 8 they don't. With bge's query prefix, the right document scored at least 0.607, and the best hit for an unanswerable question at most 0.555. 0.58 sits in the middle of that gap, so all 14 were kept and all 8 blocked. The old guess of 0.5 would have let 5 of the 8 through. I'd say plainly that 22 questions is a small sample, that it needs rechecking on real documents, and that changing the model or the prefix means recalibrating, because both shift every score.

**Q: Your `.env` had the right key, but the app used the wrong one. Why?**

> A user-level environment variable with the same name. pydantic-settings, like most twelve-factor tools, lets real environment variables override the `.env` file, so the old key silently won. The code was right; the machine was misconfigured. Checking the key's prefix without printing it found the cause quickly.

---

## 5. LLM integration and prompting

**Q: How do you support several LLM providers without a mess?**

> Two small classes with the same method: `OpenAICompatibleLLM` and `AnthropicLLM`. A `create_llm(settings)` function picks one with an `if`. Gemini and Ollama expose OpenAI-compatible endpoints, so they reuse the OpenAI class with a different `base_url`. No plugin registry, because two implementations don't justify one.

**Q: How do you reduce hallucination in the prompt?**

> The system prompt says: answer only from the provided sources, cite them as `[n]`, and say you don't know when the sources don't contain the answer. Sources are numbered and wrapped in tags. We also skip the LLM entirely when retrieval finds nothing relevant.

**Q: What is prompt injection, and how does this project handle it?**

> A document can contain text like "ignore previous instructions and…". Since retrieved text goes into the prompt, it could hijack the model. Mitigations here: context is wrapped in clearly delimited `<source>` blocks, and the system prompt tells the model to treat them as data, never as instructions. That reduces the risk but can't fully prevent it. For higher stakes you'd add output checks, restrict what the model can do (no tools here), and filter what gets ingested.

**Q: How do you handle LLM API errors?**

> Each provider's SDK exceptions are translated into one `LLMError` with an HTTP status: auth or bad request becomes 502 (the upstream rejected us), rate limit or overload becomes 503 (try later), timeout or connection failure becomes 504, and a missing key becomes 503 "not configured". The client gets a clear status, and routes don't need provider-specific code. The SDKs already retry transient errors (429, 5xx) with backoff, so we don't add another retry layer.

**Q: What's the `fallbacks` parameter on the Claude call?**

> Claude Opus 5 can decline a request through its safety classifiers (`stop_reason: "refusal"`). With `fallbacks="default"` and the `server-side-fallback-2026-07-01` beta, Anthropic re-runs a declined request on a recommended fallback model server-side. We still check `stop_reason` and return 502 if it's a refusal anyway. Because another model may have served the answer, the response reports `response.model` rather than the configured name.

**Q: How does `/ask/stream` return proper HTTP errors if streaming has already started?** (Task 9)

> It doesn't start until it's safe. Once a streamed response begins, the status is fixed at 200. So the service retrieves the sources, opens the provider stream and pulls the **first token** before the route builds the response. Missing keys, auth errors, rate limits, timeouts and refusals all happen at that point and still return 502, 503 or 504 with a JSON body. The first token is put back in front with `itertools.chain`. Only failures after it become an `event: error` inside the stream.

**Q: Why Server-Sent Events rather than WebSockets?**

> The data only flows one way, from server to client, and SSE is just an HTTP response with a text format: it works through proxies and with `curl -N`, and needs no extra library. One caveat I'd mention: the browser's `EventSource` only does `GET`, and this endpoint is a `POST` with a JSON body, so a browser reads it with `fetch` and a `ReadableStream`.

**Q: What can go wrong between your server and the client when streaming?**

> Buffering. A reverse proxy such as nginx collects the response by default, so the client would get every token at the end. The response sets `X-Accel-Buffering: no` and `Cache-Control: no-cache`. Inside the app, the request-id middleware is raw ASGI rather than `BaseHTTPMiddleware`, so it doesn't buffer the body either.

**Q: How do you escape retrieved text in the prompt, and why?**

> Each chunk goes into a `<source id="n" title="…">` block, and both the title and the text are HTML-escaped. Otherwise a document containing `</source>` plus fake instructions could close its own block and pose as a new source or as instructions. Escaping makes the delimiters trustworthy. It's one layer of the prompt-injection defence, together with the system prompt rule to treat sources as data.

**Q: Why does a missing key return 503 even for questions with no relevant context?**

> Consistency. If the key were checked only when the LLM is needed, one misconfigured server would answer 200 to off-topic questions and 503 to on-topic ones, which is confusing to diagnose. So the route checks the key first. `/documents` and `/search` never need the key and keep working.

**Q: Tell me about a bug the tests couldn't catch.**

> The first live `/ask` returned 502. The code was right: `.env` had an OpenAI key next to Gemini's base URL, and Gemini reports a bad key as 400, not 401. Unit tests with fakes can't see configuration. That's why the plan includes a live end-to-end check, and why the error mapping logs the provider's status code: it made the cause easy to find.

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

> With fakes. A deterministic `FakeEmbedder` hashes words into a vector: it's fast, needs no download, yet shared words still produce similar vectors, so ranking tests are meaningful. The LLM is replaced by a `FakeLLM` that records its prompt, and the SDK adapters are tested with fake clients that record the exact request. Chroma runs in memory with a unique collection per test. Paid APIs are never called in tests. One manual live check against the real model and Gemini confirms the real wiring.

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

**Q: How did you know the project was finished?**

> The spec listed eight success criteria before any code, such as "a new developer can follow the README from clone to a working `/ask`" and "after DELETE the document is gone from list and search". At the end I recorded evidence for each one in the spec: a test name, a live run, or both. For the README I didn't just read it: I ran every command in it against a fresh index, and fixed the two example values that didn't match the real output. The one gap is stated openly: the Claude path has unit tests but no live run, because I had no key.

**Q: Why uv?**

> It's fast, and it manages the Python version, the virtualenv, dependencies and a lockfile in one tool. `uv.lock` makes installs reproducible, so CI and Docker get exactly the versions tested locally.

**Q: How would you deploy this?**

> With the Docker image: a two-stage build on `python:3.12-slim`, dependencies installed from `uv.lock` with `--frozen --no-dev`, running as a non-root user, with a health check on `/health`. Named volumes keep the Chroma index and the model cache. Configuration comes from environment variables at run time; `.env` is excluded from the image by `.dockerignore`. For production I'd add a TLS reverse proxy, and several replicas would need a shared vector store (Chroma server mode, pgvector or Qdrant) instead of the embedded one.

**Q: Why a multi-stage Docker build?**

> The build stage has uv and its cache; the runtime stage copies only the finished virtual environment and the code. The final image is smaller and has fewer tools an attacker could use. Copying `pyproject.toml` and `uv.lock` before the code also means a code change reuses the cached dependency layer.

**Q: Tell me about a bug that only appeared in Docker.**

> The container failed on first start with `Permission denied` while downloading the embedding model. The Hugging Face downloader writes a cache in the user's home directory, and my non-root user had none. Setting `HF_HOME` to a path in the writable model volume fixed it. Tests couldn't catch it, because they never download models or run as a restricted user, which is why the plan has a manual Docker check.

**Q: How do you stop a huge upload from filling the disk?**

> A raw ASGI middleware checks `Content-Length` before reading anything and answers 413 above `MAX_REQUEST_BYTES` (2 MiB). Chunked bodies have no declared length, so it counts bytes as they arrive and stops past the limit. FastAPI turns a failed body read into a 400, so the middleware also replaces that response with the 413. It runs inside the request-id middleware, so even rejected requests are traceable.

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

---

## 12. Product thinking (planned in `docs/product/`)

These answers describe the product plan in [`docs/product/`](product/README.md). None of it is built yet, so say "planned" when you talk about it.

**Q: Who is the user, and how did that change from the PoC?**

> The PoC served developers calling an HTTP API. The product makes the *asker* the primary user: a non-technical team member who needs an answer they can trust and show to others. That shifted priorities toward citations you can click, an honest "I couldn't find this", and a web app, with the API kept for integrators.

**Q: How would you make Sourcely multi-tenant?**

> Each customer gets a *workspace*, and every row, every vector and every API key belongs to one. Isolation is enforced in three layers: the auth step resolves exactly one workspace per request, every repository function requires a `workspace_id` argument, and PostgreSQL row-level security rejects any row from another workspace even if the code forgets. A test calls every route with another workspace's credential and expects 404. I return 404 rather than 403, so the other workspace's data isn't even confirmed to exist.

**Q: Why move from Chroma to pgvector?**

> Once ingestion runs in a separate worker process, two processes would share an embedded Chroma database, which it doesn't support safely. The options were Chroma server mode or pgvector. pgvector wins because we were adding Postgres anyway for users and workspaces: one database to back up, and deleting a document removes its rows and its vectors in one transaction, so there's no window where vectors outlive their document. The `VectorStore` interface stays the same, so routes don't change. Before switching, I'd measure recall against Chroma on a test set.

**Q: Why is PDF upload asynchronous?**

> Extracting and embedding a large PDF takes seconds to minutes. Doing that inside the request would hold an API thread and risk timeouts. So the upload saves the file, creates a version with status `queued` and a job row in one transaction, and returns `202 Accepted`. A worker picks jobs with `SELECT ... FOR UPDATE SKIP LOCKED`, which lets several workers run without taking the same job, and no Redis is needed. A replace only goes live when the new version is ready, so a failed replace never leaves the document empty.

**Q: How do you decide whether a feature is worth building?**

> Each feature has a success metric and a signal that would make us change it. The risky assumptions get a cheap test first. For example, whether users actually click citations is tested with a clickable prototype and 5 people before the real UI is built.

---

## 13. Phase 1: the database (Task 12)

**Q: Why does the app connect with a different database role than the migrations?**

> Row-level security, which isolates workspaces, is bypassed by a table's owner. If the app connected as the owner, isolation could silently not apply. So `sourcely_owner` owns the schema and runs migrations, and the app connects as `sourcely_app`, which can read and write rows but owns nothing and can't change the schema. A test checks that the app role can't create a table.

**Q: What is a database migration, and why Alembic instead of creating tables at startup?**

> A migration is a versioned script that changes the schema, and the database records which version it's at, so upgrading applies only what's missing. Creating tables at startup works once, but can't change a schema that already holds data, like adding a column. Alembic is SQLAlchemy's migration tool; in Compose, a one-shot `migrate` container runs it before the API starts.

**Q: How do your tests use a real database without interfering with each other?**

> One fresh database per test run, created as a superuser, migrated with the real migrations, and dropped at the end. Before each test every table is truncated. Tests run as the same restricted role as production, so they'd catch a missing permission. If Postgres isn't running, the run stops at once with a message saying how to start it.

**Q: Tell me about a performance problem you found in your tests.**

> The suite went from 20 seconds to 149. `pytest --durations` showed one test took 130 seconds: it checks `/health` when the database is down by connecting to a closed port, and on Windows the connection attempt was dropped rather than refused, so the driver waited for the OS timeout. A real outage would have hung health checks the same way. I added `connect_timeout=5` to the engine and gave the test a 1-second one.

---

## 14. Phase 1: accounts and sessions (Task 13)

**Q: How do you store passwords?**

> As Argon2id hashes with a random salt, using argon2-cffi's defaults (RFC 9106). Argon2id is slow and memory-hungry on purpose, so someone with a stolen database can test far fewer guesses per second than with SHA-256. Rules apply only when a password is set: 12 to 128 characters and not on a list of common passwords. At sign-in any string is accepted, so changing the rules never locks people out.

**Q: How do you stop attackers learning which emails have accounts?**

> Every path answers the same way. Sign-up always returns the same 202, and an existing owner gets an "already have an account" email instead. Sign-in returns the same 401 for a wrong password and an unknown email. Timing matters too: for an unknown email the code still verifies against a dummy Argon2 hash, and sign-up hashes the password even when it won't store it.

**Q: What is CSRF, and how does this project prevent it?**

> Another site can make your browser send a request to our API, and the browser attaches our session cookie automatically. Two defences: the session cookie is `SameSite=Lax`, and every state-changing request made with a session must also carry an `X-CSRF-Token` header matching a token stored with the session. Our web app can read that token from a non-HttpOnly cookie; another site can't, so it can't forge the header. The comparison uses `secrets.compare_digest` to avoid timing differences.

**Q: Why store only a hash of the session token?**

> If the database leaked, raw tokens would be working logins. With only SHA-256 hashes stored, a leak gives nothing usable. SHA-256 is enough here, unlike for passwords, because the token is 32 random bytes and can't be guessed.

**Q: Tell me about a bug your design avoided with the sign-in throttle.**

> Each request runs in one transaction that rolls back on error, and a failed sign-in is an error. If I'd recorded the failure in that transaction, the rollback would erase it, and the throttle would never fire. So failures are written in their own short transaction. A test makes five wrong attempts and then checks that even the correct password gets 429.

**Q: Why did you change the common-passwords list from what the spec said?**

> The spec said "10,000 common passwords". When I checked, only 10 entries in that list are 12 characters or longer, and our minimum is 12, so it would have blocked almost nothing. I bundled the 1,259 long entries from the NCSC's 100,000 most-used passwords instead, and updated the spec to record why.
