# PRD: Sourcely

| | |
|---|---|
| **Product** | Sourcely: ask your team's documents, get answers with sources |
| **Owner** | Project owner |
| **Status** | Proposal, 2026-09-18 |
| **Baseline** | [`SPEC.md`](../../SPEC.md) (the PoC API, Tasks 1 to 3 built) |
| **Related** | [Wireframes](WIREFRAMES.md) · [Interaction flows](INTERACTION_FLOWS.md) · [Feature validation](FEATURE_VALIDATION.md) · [Architecture](ARCHITECTURE.md) · [Flow diagrams](FLOW_DIAGRAMS.md) |

---

## 1. Summary

Sourcely lets a small team upload its documents (policies, SOPs, manuals, notes, wiki exports) and ask questions in plain language. Every answer cites the exact passages it came from, and Sourcely says "I don't know" when the documents don't contain the answer instead of guessing.

Today Sourcely is a backend proof of concept for developers. This PRD turns it into a product with three surfaces:

1. **A web app** for people who ask questions and manage documents.
2. **A workspace model** so several teams can use one deployment without seeing each other's data.
3. **A developer API** (the existing endpoints, now authenticated) so the same knowledge base can power other tools.

## 2. Problem

Small teams keep their knowledge in scattered documents. When someone needs an answer, they either search by keyword (and miss documents that use different words), ask a colleague (and interrupt them), or give up. General chatbots can't help, because they don't know the team's private documents, and when they don't know, they invent an answer that sounds right.

The problem has three parts:

| Part | Today | With Sourcely |
|---|---|---|
| **Finding** | Keyword search misses synonyms and paraphrases. | Semantic search finds passages by meaning. |
| **Trusting** | A chatbot answer can't be checked. | Every claim links to the passage behind it. |
| **Knowing the limits** | A chatbot never says "not in our docs". | Sourcely refuses when no passage is relevant enough, without calling the LLM. |

## 3. Goals and non-goals

### Goals

- **G1. Trustworthy answers.** Every answer is grounded in the workspace's documents and cites them. Unsupported questions get an explicit "not enough information" answer.
- **G2. Time to first answer under 5 minutes.** A new user signs up, uploads a document and gets a cited answer in one short session.
- **G3. Team-safe.** Workspaces are fully isolated. A user or API key can never read another workspace's documents, answers or metadata.
- **G4. Provider-independent.** The LLM stays a configuration choice (Gemini, OpenAI, Claude, Ollama), as in the PoC.
- **G5. Cheap to run.** Embeddings stay local. One `docker compose up` still runs the whole product for a small team.

### Non-goals (for this PRD)

- Billing, plans and payments.
- Enterprise SSO (SAML, SCIM) and on-premise installation support.
- Connectors that sync from Google Drive, Notion, Confluence or Slack. Users upload files.
- OCR for scanned PDFs, and understanding images, charts or complex tables.
- Editing documents inside Sourcely. It indexes documents; it doesn't author them.
- Fine-tuning models, or agents that take actions.
- Native mobile apps. The web app is responsive instead.

## 4. Users

### Personas

| Persona | Who | Main job | Frequency |
|---|---|---|---|
| **Asker** (primary) | Any team member: support agent, new hire, operations staff. Not technical. | "Get a correct answer I can trust and show to others." | Several times a day |
| **Curator** | Team lead or ops person who owns the documents. | "Keep the knowledge base complete and current, and remove outdated documents." | Weekly |
| **Workspace admin** | Founder, manager or IT person. | "Set up the workspace, invite people, control access and see whether it's used." | Monthly |
| **Integrator** | Developer at the same company. | "Use the knowledge base from our own tools (helpdesk, Slack bot, internal site)." | During integration, then rarely |

The PoC served only the Integrator. This PRD makes the **Asker** the primary persona, because the Asker's trust decides whether the product gets used at all.

### Jobs to be done

1. When I have a question about how we do something, I want a direct answer with its source, so I can act on it and defend it.
2. When the documents don't cover my question, I want to be told clearly, so I ask a person instead of trusting a guess.
3. When a document changes or becomes outdated, I want to replace or remove it, so answers stop using old information.
4. When I only care about one area (for example "HR policies"), I want to ask within those documents only.
5. When our internal tool needs answers, I want an API key and stable endpoints.

## 5. Scope and phases

Phase 0 finishes the PoC exactly as specced. The product work starts only after it, because Phases 1 to 4 reuse every PoC endpoint.

| Phase | Theme | Features | Exit criterion |
|---|---|---|---|
| **0** | Finish the PoC | Tasks 4 to 11 in `tasks/todo.md`: search, ask, upload (`.txt`, `.md`), list, delete, filters, streaming, Docker, README | Every success criterion in `SPEC.md` has evidence. |
| **1** | Multi-tenant foundation (**done 2026-09-19**) | F1 Accounts, F2 Workspaces and roles, F10 API keys, Postgres, tenant isolation | Two workspaces on one deployment can't see each other's data, proven by automated tests. |
| **2** | Web app MVP | F3 Library, F5 Ask, F7 Scoped questions, F8 Search, members and invites UI | A new user reaches a cited answer in under 5 minutes in a usability test. |
| **3** | Rich ingestion and conversations | F4 PDF and DOCX with background processing, F6 Conversations and follow-ups, F9 Answer feedback | 90% of real PDFs from pilot users are processed without error. |
| **4** | Team and admin | F11 Usage insights, F12 Quotas and rate limits, audit log | An admin can answer "is this used, and is it good?" from one screen. |

## 6. Features

Each feature has an ID used across all product documents. Detailed acceptance criteria and input rules are in [`FEATURE_VALIDATION.md`](FEATURE_VALIDATION.md).

### Feature summary

| ID | Feature | Phase | Status | Priority |
|---|---|---|---|---|
| F1 | Accounts and sessions | 1 | Proposed | Must |
| F2 | Workspaces, roles and invites | 1 (API), 2 (UI) | Proposed | Must |
| F3 | Document library | 0 (API), 2 (UI) | Built: ingest JSON. Specced: list, delete, upload. Proposed: UI, tags, detail page | Must |
| F4 | File ingestion: PDF and DOCX, background processing | 3 | Proposed (`.txt` and `.md` upload is Specced) | Must |
| F5 | Ask with cited, streamed answers | 0 (API), 2 (UI) | Specced (API). Proposed (UI) | Must |
| F6 | Conversations and follow-up questions | 3 | Proposed | Should |
| F7 | Scoped questions (filter by documents or tags) | 0 (API), 2 (UI) | Specced (API). Proposed (UI) | Should |
| F8 | Semantic search | 0 (API), 2 (UI) | Specced (API). Proposed (UI) | Should |
| F9 | Answer feedback | 3 | Proposed | Should |
| F10 | API keys and developer API | 1 | Proposed | Must |
| F11 | Usage insights | 4 | Proposed | Could |
| F12 | Quotas and rate limits | 4 | Proposed | Should |

### F1. Accounts and sessions

Users sign up with an email and password, verify their email, sign in and sign out. Sessions live on the server and reach the browser as an `HttpOnly`, `Secure`, `SameSite=Lax` cookie. Users can reset a forgotten password by email.

- Passwords are hashed with Argon2id. Sessions expire after 14 days of inactivity and can be revoked.
- Sign-in errors never reveal whether an email is registered.
- Google sign-in is a candidate for later and is out of scope here.

### F2. Workspaces, roles and invites

A **workspace** is the unit of isolation. Documents, conversations, API keys and usage all belong to exactly one workspace. A user can belong to several workspaces and switches between them.

| Permission | Owner | Admin | Editor | Viewer |
|---|:-:|:-:|:-:|:-:|
| Ask questions, search, view documents | ✓ | ✓ | ✓ | ✓ |
| Give answer feedback | ✓ | ✓ | ✓ | ✓ |
| Upload, replace and delete documents, edit tags | ✓ | ✓ | ✓ | |
| Invite and remove members, change roles below own role | ✓ | ✓ | | |
| Create and revoke API keys | ✓ | ✓ | | |
| View usage insights | ✓ | ✓ | | |
| Rename the workspace | ✓ | ✓ | | |
| Delete the workspace, transfer ownership | ✓ | | | |

- The user who creates a workspace becomes its Owner. Each workspace has exactly one Owner.
- Admins invite people by email with a role. The invite link expires after 7 days and works once.
- Removing a member ends their sessions for that workspace immediately.

### F3. Document library

The library lists every document in the workspace with its title, type, tags, size in chunks, status, who added it and when. Curators can open a document to see its details and its chunks, replace it with a new version, edit its tags, or delete it.

- Re-uploading a file with the same document id replaces the old version (the PoC's replace-on-reingest rule).
- Deleting a document removes its file, chunks and vectors. Past answers that cited it show "Source deleted" instead of the passage.
- Tags are the product name for the PoC's metadata filters. A tag is a short label such as `hr` or `policy-2026`.

### F4. File ingestion

Users upload `.txt`, `.md`, `.pdf` and `.docx` files by drag and drop, several at once. Files up to 20 MB are accepted. Processing runs in the background, and each document shows its status: **Queued**, **Processing**, **Ready** or **Failed** (with a reason and a retry button).

- Text is extracted per page for PDFs, so answers can cite "page 4".
- A PDF with no extractable text (a scan) fails with the reason "No text found. Scanned PDFs aren't supported yet."
- The JSON `POST /documents` endpoint stays synchronous for API clients sending plain text.

### F5. Ask with cited, streamed answers

The Ask screen is the heart of the product. The user types a question, and the answer streams in word by word. Inline markers such as `[1]` link to source cards showing the document title, page and the passage. Clicking a source opens the passage highlighted in context.

- The "not enough information" rule from the PoC stays: when no passage is relevant enough, Sourcely says so and suggests rephrasing or uploading a document. It never calls the LLM in that case.
- If the stream breaks mid-answer, the partial answer stays visible with a "Retry" action.
- Answers can be copied with their citations as footnotes.

### F6. Conversations and follow-up questions

Questions and answers are saved as conversations the user can reopen. Follow-up questions such as "and for part-time staff?" work, because Sourcely rewrites them into a standalone question using the conversation so far before searching.

- Conversations are private to the user who created them.
- Users can rename and delete their conversations.
- The rewritten question is shown in small text ("Searched for: parental leave for part-time staff") so the user sees what was searched.

### F7. Scoped questions

Before asking, the user can limit the scope to chosen documents or tags. The scope shows as chips above the input and stays for the conversation until cleared. This is the PoC's `filters` field with a UI.

### F8. Semantic search

A search screen returns the most relevant passages for a query, each with its document, page and a relevance bar. It is for users who want to read the sources themselves rather than get a written answer. It never calls the LLM, so it works even when the LLM is down.

### F9. Answer feedback

Each answer has thumbs up and thumbs down. Thumbs down asks for an optional reason: "Wrong", "Incomplete", "Wrong source", "Should have said I don't know", or free text. Admins see feedback in usage insights, and it becomes the test set for retrieval tuning.

### F10. API keys and developer API

Admins create API keys for a workspace. A key is shown once at creation, then only its prefix is visible. Keys can be named and revoked. API calls with a key act on that key's workspace, with the Editor role.

The PoC paths `/documents`, `/search` and `/ask` stay unchanged, because the client's brief fixes them. The workspace comes from the credential, not from the path.

### F11. Usage insights

Admins see, for a chosen period: questions asked, active askers, the "not enough information" rate, the helpful-answer rate from feedback, the most cited documents, and questions that got no answer (a to-do list for curators).

### F12. Quotas and rate limits

Per-workspace limits protect the LLM budget and the server: maximum documents, total storage, questions per day, and requests per minute per user and per API key. Hitting a limit returns `429` with a `Retry-After` header, and the UI explains which limit was hit.

## 7. Success metrics

| Metric | Definition | Target | Measured from |
|---|---|---|---|
| **Activation** | New workspaces with at least 1 ready document and 1 answered question within 24 hours of sign-up | ≥ 60% | Events table |
| **Time to first answer** | Median time from sign-up to the first answer with sources | < 5 minutes | Events table |
| **Helpful rate** | Thumbs up ÷ all rated answers | ≥ 75% | F9 feedback |
| **Correct refusal rate** | Share of "should have said I don't know" among thumbs-down reasons | < 10% of thumbs down | F9 feedback |
| **No-answer rate** | Questions answered with "not enough information" | Tracked, no target. A rising rate means missing documents. | Answer events |
| **Time to first token** | p50 and p95 from question sent to first streamed token | p50 < 2 s, p95 < 5 s | Server timing |
| **Ingestion time** | p95 from upload to Ready for a 20-page PDF | < 60 s | Job timings |
| **Weekly active askers** | Users who asked at least one question in the week, per workspace | Rising over the first 8 weeks | Events table |
| **Isolation incidents** | Any read across workspaces | 0, always | Tests and audit |

## 8. Assumptions and risks

| # | Assumption or risk | Why it matters | How it's tested or reduced |
|---|---|---|---|
| A1 | Teams trust cited answers more than uncited ones and will click sources. | It is the core bet. | Usability test in Phase 2: citation click rate and trust rating. See [`FEATURE_VALIDATION.md`](FEATURE_VALIDATION.md#assumptions-to-validate-before-building). |
| A2 | Most useful team documents are text PDFs and DOCX, not scans. | Decides whether OCR is needed. | Ask 5 pilot teams for 10 real files each before Phase 3. |
| A3 | `bge-small-en-v1.5` retrieval is good enough on real team documents. | Weak retrieval makes every answer bad. | Build a 50-question test set from pilot documents and measure hit rate at top 4. |
| A4 | Gemini's free tier is fine for development but not for customer data. | Google may use free-tier data. | Production uses a paid provider with no-training terms. This is stated in the admin settings and README. |
| R1 | A tenant isolation bug leaks documents between workspaces. | Fatal for trust. | Workspace id on every row and every vector query, one enforcement point, and cross-tenant tests on every endpoint. |
| R2 | Prompt injection inside an uploaded document changes the answer's behaviour. | Answers could be manipulated. | The system prompt treats context as data (already in SPEC), sources are always shown, and an injection test set runs in CI. |
| R3 | LLM cost grows with usage. | Budget risk. | The no-context short circuit, quotas (F12) and usage insights (F11). |
| R4 | Embedded Chroma can't be shared by the API and a background worker. | Blocks F4. | Decision D3 in [`ARCHITECTURE.md`](ARCHITECTURE.md#8-key-decisions): move to Chroma server mode or pgvector. |

## 9. Open decisions

These need an answer from the owner before the phase that depends on them. Each has a recommendation in [`ARCHITECTURE.md`](ARCHITECTURE.md#8-key-decisions).

| # | Decision | Needed before | Recommendation |
|---|---|---|---|
| D1 | Build our own auth, or use a managed service (Clerk, Auth0, Supabase Auth)? | Phase 1 | Own auth: fewer moving parts for self-hosting, and good learning value. |
| D2 | Relational database | Phase 1 | PostgreSQL with SQLAlchemy 2 and Alembic. |
| D3 | Vector store once a worker exists: Chroma server, or pgvector inside Postgres? | Phase 1 | pgvector: one database, transactional deletes, workspace filtering in SQL. |
| D4 | Frontend stack | Phase 2 | Next.js (App Router) with TypeScript, Tailwind CSS and shadcn/ui, matching the `job-tracker` project. |
| D5 | Background job runner | Phase 3 | A Postgres-backed job table (`SELECT … FOR UPDATE SKIP LOCKED`). No Redis needed. |
| D6 | What happens to past answers when a cited document is deleted? | Phase 3 | Keep the answer text, replace the cited passage with "Source deleted". |
| D7 | Are conversations private to their creator, or shared in the workspace? | Phase 3 | Private, with a "share link" later. |
| D8 | Should `POST /documents/upload` return `202` and process in the background, instead of SPEC's synchronous `201`? | Phase 3 | Yes, for every file type, while the API has no external consumers. |

## 10. Release plan

1. **Phase 0 to 1:** internal only. Run on one machine with Docker Compose.
2. **Phase 2:** closed pilot with 3 to 5 small teams, one workspace each, invited by hand. Weekly check-ins, feedback in a shared doc.
3. **Phase 3:** open to pilot teams' colleagues. Measure activation and helpful rate.
4. **Phase 4:** decide on a public beta based on the metrics in section 7.

Each phase ends at a checkpoint with owner review, the same way the PoC tasks do.
