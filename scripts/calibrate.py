"""Measure relevance scores for answerable vs unanswerable questions (Checkpoint B).

Embedding only, no LLM calls. Compares plain queries with bge's query instruction prefix,
and prints how many questions each `MIN_RELEVANCE` candidate keeps or blocks. Rerun it
whenever the embedding model, the query prefix or the vector store changes.

Run from the repository root:  uv run python -m scripts.calibrate
"""

import statistics
import sys
import uuid

import chromadb

from app.core.config import Settings
from app.services.chunking import chunk_text
from app.services.embeddings import FastEmbedEmbedder
from app.services.vector_store import VectorStore

DOCS = {
    "leave": "Leave policy 2026. Full-time employees get 21 days of paid annual leave per year. "
    "Part-time staff receive annual leave pro-rated to their contracted hours. Unused leave of up "
    "to 5 days can be carried over to the next year. Parental leave: birth parents are entitled "
    "to 16 weeks of paid leave, and partners to 4 weeks. Requests must be made 8 weeks in advance.",
    "refunds": "Refund policy. Annual plans can be refunded in full within 30 days of purchase. "
    "After 30 days, annual plans are refunded pro-rata for the unused months. Monthly plans are "
    "not refundable. Refunds are paid to the original payment method within 10 business days.",
    "vpn": "VPN setup guide. Install the WireGuard client from the company portal. Sign in with "
    "your work account and choose the Frankfurt gateway. If the connection drops, restart the "
    "client and check that multi-factor authentication is approved on your phone.",
    "expenses": "Expense policy. Employees may claim travel, meals and accommodation for business "
    "trips. The daily meal allowance is 45 euros. Hotels must be booked through the travel "
    "desk. Receipts must be uploaded within 30 days of the expense.",
    "security": "Password and device security. Passwords must be at least 14 characters and are "
    "never shared. Laptops lock automatically after 5 minutes. Lost devices must be reported to "
    "IT within one hour so they can be wiped remotely.",
    "onboarding": "Onboarding checklist. On the first day, new hires collect their laptop, "
    "complete security training and meet their buddy. In the first week they set up payroll "
    "details and read the team handbook.",
}

ANSWERABLE = [
    ("How many vacation days do I get per year?", "leave"),
    ("Do part-time workers get holiday?", "leave"),
    ("How long is maternity leave?", "leave"),
    ("Can I carry over unused days off?", "leave"),
    ("Can I get my money back for a yearly subscription?", "refunds"),
    ("Are monthly plans refundable?", "refunds"),
    ("How long does a refund take to arrive?", "refunds"),
    ("How do I connect to the office network from home?", "vpn"),
    ("My VPN keeps disconnecting, what should I do?", "vpn"),
    ("What is the food allowance on a business trip?", "expenses"),
    ("How do I book a hotel for work travel?", "expenses"),
    ("What are the password rules?", "security"),
    ("I lost my laptop, who do I tell?", "security"),
    ("What happens on my first day?", "onboarding"),
]

UNANSWERABLE = [
    "What is the capital of France?",
    "Who won the football world cup in 2022?",
    "How do I bake sourdough bread?",
    "What is the company's revenue this year?",
    "Is there a gym in the office?",
    "What is our stock option vesting schedule?",
    "Can I bring my dog to work?",
    "How do I request a new monitor?",
]

PREFIX = "Represent this sentence for searching relevant passages: "


def main() -> None:
    settings = Settings()
    embedder = FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir)
    store = VectorStore(chromadb.EphemeralClient(), f"cal-{uuid.uuid4().hex}")
    for doc_id, text in DOCS.items():
        chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
        store.replace_document(doc_id, chunks, embedder.embed_documents(chunks), {}, doc_id)

    for label, prefix in (("plain", ""), ("prefix", PREFIX)):
        right, wrong_best, unans_best, misses = [], [], [], []
        for q, expected in ANSWERABLE:
            hits = store.query(embedder.embed_query(prefix + q), len(DOCS))
            by_doc = {h.document_id: h.score for h in hits}
            right.append(by_doc[expected])
            wrong_best.append(max(s for d, s in by_doc.items() if d != expected))
            if hits[0].document_id != expected:
                misses.append((q, hits[0].document_id))
        for q in UNANSWERABLE:
            unans_best.append(store.query(embedder.embed_query(prefix + q), 1)[0].score)

        def fmt(xs):
            return f"min {min(xs):.3f}  median {statistics.median(xs):.3f}  max {max(xs):.3f}"

        print(f"\n== {label} ==")
        print(
            f"top-1 accuracy: {len(ANSWERABLE) - len(misses)}/{len(ANSWERABLE)}  misses: {misses}"
        )
        print(f"correct doc score      : {fmt(right)}")
        print(f"best wrong doc score   : {fmt(wrong_best)}")
        print(f"unanswerable best score: {fmt(unans_best)}")
        print("unanswerable detail    :", [round(s, 3) for s in unans_best])
        print("correct detail         :", [round(s, 3) for s in right])
        for t in (0.55, 0.58, 0.6, 0.62, 0.65, 0.68, 0.7):
            kept = sum(s >= t for s in right)
            blocked = sum(s < t for s in unans_best)
            print(
                f"  threshold {t:.2f}: answerable kept {kept}/{len(right)}, "
                f"unanswerable blocked {blocked}/{len(unans_best)}"
            )
    sys.stdout.flush()


if __name__ == "__main__":
    main()
