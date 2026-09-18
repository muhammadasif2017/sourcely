# Sourcely product documents

These documents describe Sourcely as a **product**, not only as the proof-of-concept API in [`SPEC.md`](../../SPEC.md). They were written on 2026-09-18, after Task 3 of the PoC, to plan what Sourcely becomes once the PoC is finished.

> **Status: proposal.** Nothing here changes the current build. `SPEC.md` is still the source of truth for the PoC, and `tasks/todo.md` (Tasks 4 to 11) is still the next work. Several ideas here are on the "ask first" list in `CLAUDE.md` (auth, new public endpoints, switching the vector store). Adopting any of them means amending `SPEC.md` first.

## Reading order

| # | Document | What it answers |
|---|---|---|
| 1 | [`PRD.md`](PRD.md) | Why Sourcely exists, who it is for, which features it has, in which phase, and how success is measured. |
| 2 | [`WIREFRAMES.md`](WIREFRAMES.md) | What each screen looks like, including empty, loading and error states. |
| 3 | [`INTERACTION_FLOWS.md`](INTERACTION_FLOWS.md) | How a person moves through the screens to get a job done. |
| 4 | [`FEATURE_VALIDATION.md`](FEATURE_VALIDATION.md) | How each feature is accepted: acceptance criteria, input rules, metrics, and the assumptions to test before building. |
| 5 | [`ARCHITECTURE.md`](ARCHITECTURE.md) | The current system and the target system: containers, components, data model, API surface, key decisions. |
| 6 | [`FLOW_DIAGRAMS.md`](FLOW_DIAGRAMS.md) | What happens inside the system for each operation: sequence diagrams and state machines. |
| 7 | [`DATA_FLOW.md`](DATA_FLOW.md) | What data moves where: data flow diagrams (Levels 0 to 2), trust boundaries, the data inventory and deletion flows. |

## Status labels used everywhere

Every feature, endpoint and component carries one of three labels, so it is always clear what is real.

| Label | Meaning |
|---|---|
| **Built** | Exists in the code on `main` and is covered by tests. |
| **Specced** | Designed in `SPEC.md` and scheduled in `tasks/todo.md`, not built yet. |
| **Proposed** | New in these documents. Needs a decision and a `SPEC.md` amendment before any code. |

Verified against the code on 2026-09-18: **Built** is `GET /health`, `POST /documents`, chunking, local embeddings, the Chroma vector store (count and replace), request-id middleware, error handlers, settings, CI and pre-commit hooks.

## Diagrams

Diagrams use [Mermaid](https://mermaid.js.org/), which GitHub renders inside Markdown. Wireframes are monospace text blocks: they render everywhere and show clean diffs in review. They can be turned into high-fidelity designs later.
