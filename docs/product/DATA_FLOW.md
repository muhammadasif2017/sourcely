# Data flow diagrams: Sourcely

These diagrams show **what data moves where**: which parties and processes send which data, and which stores keep it. They complement the other documents:

- [`FLOW_DIAGRAMS.md`](FLOW_DIAGRAMS.md) shows the **order of calls** (sequence diagrams) and **status changes** (state machines).
- [`ARCHITECTURE.md`](ARCHITECTURE.md) shows the **components** and the **data model**.
- This document shows the **data**: its sources, its path, where it rests, and where it leaves the deployment.

Status labels are the same as everywhere: **Built**, **Specced**, **Proposed** (see [README](README.md#status-labels-used-everywhere)).

## Notation

The diagrams follow classic DFD notation (Gane and Sarson style), drawn in Mermaid.

| Shape | Meaning | Example |
|---|---|---|
| Rectangle | **External entity**: a person or system outside Sourcely that sends or receives data | Asker, LLM provider |
| Circle, numbered | **Process**: transforms data | 2.0 Ingest documents |
| Cylinder, `D1` to `D9` | **Data store**: data at rest | D4 Chunks and vectors |
| Labelled arrow | **Data flow**: the data that moves, named by its content | "question, scope" |
| Dashed box | **Trust boundary**: data crossing it needs authentication, validation or a privacy decision | Browser to server |

Every arrow is labelled with **data**, not actions. "Question text" is a data flow; "calls the API" is not.

## Contents

1. [Current PoC (Built and Specced)](#1-current-poc-built-and-specced)
2. [Level 0: context](#2-level-0-context)
3. [Level 1: main processes and stores](#3-level-1-main-processes-and-stores)
4. [Level 2: ingest documents](#4-level-2-ingest-documents)
5. [Level 2: answer a question](#5-level-2-answer-a-question)
6. [Level 2: authenticate and manage access](#6-level-2-authenticate-and-manage-access)
7. [Trust boundaries](#7-trust-boundaries)
8. [Data inventory](#8-data-inventory)
9. [Deletion flows](#9-deletion-flows)

---

## 1. Current PoC (Built and Specced)

The PoC has no users, no auth and no relational database. Everything a client sends is either stored as chunks in Chroma or used once and discarded. Only the question and retrieved passages ever leave the machine.

```mermaid
flowchart LR
    client["HTTP client"]
    llmP["LLM provider<br/>Gemini, OpenAI, Claude"]

    p1(("1.0<br/>Ingest<br/><b>Built</b>"))
    p2(("2.0<br/>Search<br/><b>Specced</b>"))
    p3(("3.0<br/>Answer<br/><b>Specced</b>"))

    dM[("D0 Model cache<br/>bge-small ONNX")]
    dC[("D4 Chroma<br/>chunk text, vectors,<br/>document id, title, metadata")]

    client -- "document text, id, title, metadata" --> p1
    dM -- "model weights" --> p1
    p1 -- "chunk text, vectors, metadata" --> dC
    p1 -- "document id, chunk count, characters" --> client

    client -- "query, top_k, filters" --> p2
    dM -- "model weights" --> p2
    dC -- "nearest chunks, distances" --> p2
    p2 -- "chunks with scores" --> client

    client -- "question, top_k, filters" --> p3
    dC -- "nearest chunks, distances" --> p3
    p3 -- "system rules, numbered passages, question" --> llmP
    llmP -- "answer text or error" --> p3
    p3 -- "answer, sources, provider, model" --> client
```

**What the PoC does not store:** questions, answers and request bodies. Logs hold the request id, method, path, status and duration, not the content.

## 2. Level 0: context

The whole product as one process. This view answers "what data enters and leaves Sourcely?"

```mermaid
flowchart LR
    asker["Asker"]
    curator["Curator"]
    admin["Workspace admin"]
    integ["Integrator tool"]
    llmP["LLM provider"]
    mail["Email service"]

    s(("0<br/><b>Sourcely</b>"))

    asker -- "credentials, questions, scope, feedback" --> s
    s -- "answers, sources, passages, search results" --> asker
    curator -- "files, text, titles, tags, delete requests" --> s
    s -- "document list, status, chunks" --> curator
    admin -- "invites, roles, key requests, workspace settings" --> s
    s -- "members, API key once, usage figures" --> admin
    integ -- "API key, documents, queries, questions" --> s
    s -- "results, answers, sources" --> integ
    s -- "prompt: rules, passages, question, recent turns" --> llmP
    llmP -- "answer tokens, rewritten query" --> s
    s -- "recipient address, verify, reset and invite links" --> mail
```

**Two flows leave the deployment:** prompts to the LLM provider, and emails. Documents, files, vectors, conversations and usage data never leave it.

## 3. Level 1: main processes and stores

The product broken into its six processes and nine data stores. Every Level 2 diagram below expands one process from here.

```mermaid
flowchart LR
    user["Asker, Curator, Admin"]
    integ["Integrator tool"]
    llmP["LLM provider"]
    mail["Email service"]

    p1(("1.0<br/>Authenticate<br/>and authorise"))
    p2(("2.0<br/>Ingest<br/>documents"))
    p3(("3.0<br/>Retrieve<br/>passages"))
    p4(("4.0<br/>Generate<br/>answer"))
    p5(("5.0<br/>Manage<br/>workspace"))
    p6(("6.0<br/>Record<br/>usage"))

    d1[("D1 Users and sessions")]
    d2[("D2 Workspaces, members,<br/>invites, API keys")]
    d3[("D3 Documents and versions")]
    d4[("D4 Chunks and vectors")]
    d5[("D5 Files")]
    d6[("D6 Jobs")]
    d7[("D7 Conversations,<br/>messages, sources")]
    d8[("D8 Feedback")]
    d9[("D9 Events and counters")]

    user -- "email, password, session cookie" --> p1
    integ -- "API key" --> p1
    d1 -- "password hash, session" --> p1
    d2 -- "membership, role, key hash" --> p1
    p1 -- "Principal: user or key, workspace, role" --> p2
    p1 -- "Principal" --> p3
    p1 -- "Principal" --> p5

    user -- "files, text, tags" --> p2
    integ -- "text, files" --> p2
    p2 -- "original file" --> d5
    p2 -- "document, version, status" --> d3
    p2 -- "job" --> d6
    p2 -- "chunks, vectors, page numbers" --> d4

    user -- "question, scope" --> p3
    integ -- "query, question, filters" --> p3
    d7 -- "recent turns" --> p3
    d4 -- "nearest chunks, scores" --> p3
    p3 -- "passages with scores" --> p4
    p3 -- "search results" --> user

    p4 -- "prompt" --> llmP
    llmP -- "answer tokens" --> p4
    p4 -- "answer, sources" --> user
    p4 -- "messages, cited sources" --> d7

    user -- "rating, reason, comment" --> p6
    p6 -- "feedback" --> d8
    p4 -- "outcome, timings, tokens" --> p6
    p6 -- "events, quota counters" --> d9
    d9 -- "usage figures" --> p5

    user -- "invites, roles, key names" --> p5
    p5 -- "memberships, invites, key hashes" --> d2
    p5 -- "invite and reset links" --> mail
    p5 -- "usage figures, new key once" --> user
```

| Process | Status | Expanded in |
|---|---|---|
| 1.0 Authenticate and authorise | Proposed | [Section 6](#6-level-2-authenticate-and-manage-access) |
| 2.0 Ingest documents | Built (JSON text), Specced (`.txt`, `.md` upload), Proposed (PDF, DOCX, worker) | [Section 4](#4-level-2-ingest-documents) |
| 3.0 Retrieve passages | Specced | [Section 5](#5-level-2-answer-a-question) |
| 4.0 Generate answer | Specced (single question), Proposed (conversations) | [Section 5](#5-level-2-answer-a-question) |
| 5.0 Manage workspace | Proposed | [Section 6](#6-level-2-authenticate-and-manage-access) |
| 6.0 Record usage | Proposed | [Section 8](#8-data-inventory) |

## 4. Level 2: ingest documents

Expands process 2.0. Sub-processes 2.1 and 2.2 run in the API. Sub-processes 2.3 to 2.6 run in the worker (Proposed, Phase 3). For JSON text, `POST /documents` runs 2.4 to 2.6 inside the request, which is the **Built** path.

```mermaid
flowchart LR
    cur["Curator or Integrator"]

    p21(("2.1<br/>Validate<br/>upload"))
    p22(("2.2<br/>Store file,<br/>queue job"))
    p23(("2.3<br/>Extract<br/>text"))
    p24(("2.4<br/>Chunk"))
    p25(("2.5<br/>Embed"))
    p26(("2.6<br/>Publish<br/>version"))

    d3[("D3 Documents<br/>and versions")]
    d4[("D4 Chunks<br/>and vectors")]
    d5[("D5 Files")]
    d6[("D6 Jobs")]
    d0[("D0 Model cache")]
    d9[("D9 Counters")]

    cur -- "file bytes, filename, document id, tags" --> p21
    d9 -- "storage used" --> p21
    p21 -- "rejection reason: 413, 415, 422" --> cur
    p21 -- "accepted file, metadata" --> p22
    p22 -- "file bytes" --> d5
    p22 -- "document, version n+1 queued" --> d3
    p22 -- "job for version" --> d6
    p22 -- "document id, status queued" --> cur

    d6 -- "next job" --> p23
    d5 -- "file bytes" --> p23
    p23 -- "failure reason" --> d3
    p23 -- "text per page" --> p24
    p24 -- "chunks with page numbers" --> p25
    d0 -- "model weights" --> p25
    p25 -- "chunks, 384-dim vectors" --> p26
    p26 -- "chunk rows with vectors" --> d4
    p26 -- "status ready, live version" --> d3
    p26 -- "old version's chunks removed" --> d4
    p26 -- "job removed" --> d6
```

**Data rules in this flow**

- The file is kept in D5 so a document can be re-processed when chunking or the embedding model changes, without asking the user to upload it again.
- 2.6 writes new chunks, moves the live version and deletes old chunks in **one transaction**. Readers see either the old version or the new one, never a mix.
- Extracted text is not stored separately from chunks. Chunks are the only copy of the document's text inside the database.

## 5. Level 2: answer a question

Expands processes 3.0 and 4.0. Steps 3.1 and 4.4 are Proposed (conversations, Phase 3). The rest follows `SPEC.md` for `/ask` and `/ask/stream`.

```mermaid
flowchart LR
    ask["Asker or Integrator"]
    llmP["LLM provider"]

    p31(("3.1<br/>Rewrite<br/>follow-up"))
    p32(("3.2<br/>Embed<br/>query"))
    p33(("3.3<br/>Find nearest<br/>chunks"))
    p34(("3.4<br/>Relevance<br/>gate"))
    p41(("4.1<br/>Build<br/>prompt"))
    p42(("4.2<br/>Call<br/>LLM"))
    p43(("4.3<br/>Stream<br/>answer"))
    p44(("4.4<br/>Save<br/>turn"))

    d0[("D0 Model cache")]
    d3[("D3 Documents")]
    d4[("D4 Chunks and vectors")]
    d7[("D7 Conversations")]
    d9[("D9 Events and counters")]

    ask -- "question, scope, conversation id" --> p31
    d7 -- "last 6 turns" --> p31
    p31 -- "recent turns, follow-up" --> llmP
    llmP -- "standalone query" --> p31
    p31 -- "search query" --> p32
    d0 -- "model weights" --> p32
    p32 -- "query vector" --> p33
    d3 -- "live versions, tags" --> p33
    d4 -- "chunks, distances, workspace-filtered" --> p33
    p33 -- "top_k chunks with scores" --> p34
    p34 -- "no relevant chunks: fixed answer" --> ask
    p34 -- "relevant passages" --> p41
    p41 -- "system rules, numbered passages, question" --> p42
    d9 -- "questions used today" --> p42
    p42 -- "prompt" --> llmP
    llmP -- "tokens or error" --> p42
    p42 -- "tokens" --> p43
    p43 -- "sources event, token events, done or error" --> ask
    p43 -- "question, answer, sources, search query" --> p44
    p44 -- "messages, cited chunk ids and titles" --> d7
    p44 -- "outcome, top score, timings, token counts" --> d9
```

**Data rules in this flow**

- **Minimum data to the provider.** The LLM receives only the system rules, the passages that passed the relevance gate, the question and, for follow-ups, the last 6 turns. It never receives whole documents, other workspaces' data, user names, emails or tags.
- **The relevance gate stops data leaving.** When 3.4 finds nothing relevant, nothing is sent to the provider at all.
- **Sources are stored by reference.** D7 keeps the chunk id, document title, page and score, not a copy of the passage text. Deleting the document therefore removes the passage everywhere (see [section 9](#9-deletion-flows)).

## 6. Level 2: authenticate and manage access

Expands processes 1.0 and 5.0. All **Proposed** (Phase 1).

```mermaid
flowchart LR
    user["User"]
    admin["Admin"]
    integ["Integrator tool"]
    mail["Email service"]

    p11(("1.1<br/>Sign up and<br/>verify"))
    p12(("1.2<br/>Sign in"))
    p13(("1.3<br/>Resolve<br/>credential"))
    p51(("5.1<br/>Invite and<br/>set roles"))
    p52(("5.2<br/>Issue and<br/>revoke keys"))

    d1[("D1 Users and sessions")]
    d2[("D2 Members, invites,<br/>API keys")]

    user -- "name, email, password" --> p11
    p11 -- "user, Argon2id hash, verify token hash" --> d1
    p11 -- "email, verify link" --> mail
    user -- "email, password" --> p12
    d1 -- "password hash, failure count" --> p12
    p12 -- "session token hash" --> d1
    p12 -- "session cookie, CSRF cookie" --> user

    user -- "session cookie, workspace id" --> p13
    integ -- "API key" --> p13
    d1 -- "session" --> p13
    d2 -- "role, key hash, revoked flag" --> p13
    p13 -- "Principal to every other process" --> out["processes 2.0 to 6.0"]

    admin -- "emails, role" --> p51
    p51 -- "invite, token hash, membership, role" --> d2
    p51 -- "email, invite link" --> mail
    admin -- "key name, revoke request" --> p52
    p52 -- "key prefix, key hash, revoked at" --> d2
    p52 -- "full key, shown once" --> admin
```

**Data rules in this flow**

- Secrets are stored only as hashes: passwords with Argon2id, and session tokens, verification tokens, invite tokens and API keys with SHA-256. A database leak exposes none of them in usable form.
- The full API key exists only in the response to 5.2 and in the integrator's own system.

## 7. Trust boundaries

The same system, grouped by where data is trusted. Every arrow that crosses a dashed boundary needs a control.

```mermaid
flowchart LR
    subgraph client["Boundary A: user devices and integrator systems (untrusted)"]
        browser["Browser"]
        tool["Integrator tool"]
    end

    subgraph deploy["Boundary B: Sourcely deployment (trusted)"]
        subgraph edge["Edge"]
            caddy["Caddy: TLS, size limits"]
        end
        subgraph app["Application"]
            apiP(("API"))
            workerP(("Worker"))
        end
        subgraph data["Data at rest"]
            pg[("PostgreSQL<br/>D1 to D4, D6 to D9<br/>row-level security")]
            fs[("Files D5")]
        end
    end

    subgraph third["Boundary C: third parties (trusted by contract only)"]
        llmP["LLM provider"]
        mail["Email service"]
    end

    browser -- "TLS: cookie, CSRF token, questions, files" --> caddy
    tool -- "TLS: Bearer key, requests" --> caddy
    caddy --> apiP
    apiP --> pg
    apiP --> fs
    workerP --> pg
    workerP --> fs
    apiP -- "TLS: prompt with passages" --> llmP
    apiP -- "TLS: address and link" --> mail
```

| Crossing | Data | Controls |
|---|---|---|
| A to B | Credentials, questions, files, document text | TLS. Authentication (FD-2). CSRF token for browser writes. Pydantic validation. Magic-byte file check, size limits. Rate limits. |
| B to A | Answers, passages, document lists, API key once | Workspace scoping on every read. `404` for other workspaces' resources. No stack traces. `HttpOnly` cookies. |
| Application to data | Every read and write | Required `workspace_id` in every repository call. PostgreSQL row-level security as the second check. App database role can't bypass RLS. |
| B to C, LLM | Rules, relevant passages, question, recent turns | Relevance gate sends nothing when no passage qualifies. Paid provider with no-training terms in production. Free-tier warning in development. Only these fields are sent. |
| B to C, email | Recipient address, one-time link | Links carry single-use tokens that expire. No document content in emails. |
| Worker to files | Uploaded files, which may be hostile | Extraction runs in the worker, not the API. Uncompressed-size limit. No macros run. External XML entities off. |

## 8. Data inventory

Every kind of data Sourcely holds, how sensitive it is, and how long it's kept.

| Data | Store | Sensitivity | Sent outside? | Kept until |
|---|---|---|---|---|
| Name, email | D1 | Personal data | Email service (address only) | Account deleted |
| Password | D1 | Secret | Never | Stored only as Argon2id hash. Replaced on reset. |
| Session and CSRF tokens | D1 | Secret | Never | 14 days idle, sign-out or password reset |
| Workspace name, memberships, roles | D2 | Internal | Never | Workspace deleted |
| Invite tokens | D2 | Secret | Email service (link) | Accepted or 7 days |
| API keys | D2 | Secret | Never after creation | Revoked. The row stays for audit, the hash is useless. |
| Document titles, tags, metadata | D3 | Customer confidential | Never. Titles are not sent to the LLM. | Document deleted |
| Original files | D5 | Customer confidential | Never | Document deleted |
| Chunk text and vectors | D4 | Customer confidential | Relevant passages only, to the LLM | Document deleted or version replaced |
| Jobs | D6 | Internal | Never | Job finished |
| Questions and answers | D7 | Customer confidential, may contain personal data | Question and recent turns, to the LLM | Conversation deleted by the user, or workspace deleted |
| Cited sources | D7 | Internal (references only) | Never | Conversation deleted. Chunk reference cleared when the document is deleted. |
| Feedback | D8 | Internal | Never | Conversation deleted |
| Events and counters | D9 | Internal, no content | Never | 13 months, then deleted |
| Access logs | Log files | Internal, no content | Log platform if one is added | 30 days |

**Rule for logs and events:** they hold ids, statuses, timings and counts. They never hold question text, answer text, document text or passwords. Unanswered questions shown in usage insights (F11) are read from D7, not from logs, so deleting a conversation removes them.

## 9. Deletion flows

What is removed, and from where, for each delete. Deletion is the flow most often forgotten in DFDs, and the one that proves the data inventory above is true.

```mermaid
flowchart TD
    delDoc["Delete document"] --> x1["D4: its chunks and vectors"]
    delDoc --> x2["D3: document and all versions"]
    delDoc --> x3["D6: its queued jobs"]
    delDoc --> x4["D5: its files, after the transaction commits"]
    delDoc --> x5["D7: cited chunk ids set to null,<br/>title kept, UI shows Source deleted"]

    delConv["Delete conversation"] --> y1["D7: messages and sources"]
    delConv --> y2["D8: feedback on those messages"]

    delMember["Remove member"] --> z1["D2: membership"]
    delMember --> z2["D1: sessions stop resolving to this workspace"]
    delMember --> z3["D7: their conversations in this workspace deleted"]

    delWs["Delete workspace"] --> w1["D2, D3, D4, D6, D7, D8, D9:<br/>every row with this workspace id"]
    delWs --> w2["D5: every file under the workspace prefix"]
    delWs --> w3["D2: API keys revoked and removed"]

    delAcct["Delete account"] --> a1{"Sole owner of a workspace?"}
    a1 -- "Yes" --> a2["Blocked: transfer ownership<br/>or delete the workspace first"]
    a1 -- "No" --> a3["D1: user and sessions<br/>D2: memberships<br/>D7, D8: their conversations and feedback"]
```

**What a delete can't reach:** prompts already sent to the LLM provider. Their retention depends on the provider's terms, which is why production uses a provider with no-training and short-retention terms. This is stated in the admin settings screen and the README.
