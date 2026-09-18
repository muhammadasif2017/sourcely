import re

import pytest

from app.services.chunking import chunk_text

PARAGRAPH = (
    "Retrieval-augmented generation grounds a language model in external documents. "
    "The system embeds each chunk, stores the vectors, and retrieves the closest ones "
    "for every question."
)


def words(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def test_short_text_is_one_chunk() -> None:
    assert chunk_text("Hello world.", size=100, overlap=10) == ["Hello world."]


@pytest.mark.parametrize("text", ["", "   ", "\n\n\t"])
def test_blank_text_gives_no_chunks(text: str) -> None:
    assert chunk_text(text, size=100, overlap=10) == []


def test_every_chunk_respects_size() -> None:
    text = "\n\n".join([PARAGRAPH] * 12)
    chunks = chunk_text(text, size=150, overlap=30)
    assert len(chunks) > 1
    assert all(0 < len(c) <= 150 for c in chunks)


def test_no_words_are_lost_and_order_is_kept() -> None:
    text = "\n\n".join(f"Paragraph {i}. " + PARAGRAPH for i in range(10))
    chunks = chunk_text(text, size=120, overlap=0)
    assert words(" ".join(chunks)) == words(text)


def test_adjacent_chunks_overlap() -> None:
    sentences = " ".join(f"Sentence number {i} is here." for i in range(40))
    chunks = chunk_text(sentences, size=100, overlap=40)
    assert len(chunks) > 2
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        # The next chunk starts with text the previous chunk ended with.
        assert " ".join(words(nxt)[:3]) in prev


def test_prefers_paragraph_boundaries() -> None:
    first = "A" * 60
    second = "B" * 60
    chunks = chunk_text(f"{first}\n\n{second}", size=100, overlap=0)
    assert chunks == [first, second]


def test_unbroken_text_is_hard_cut() -> None:
    chunks = chunk_text("x" * 250, size=100, overlap=0)
    assert [len(c) for c in chunks] == [100, 100, 50]


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (100, -1), (100, 100), (100, 150)])
def test_invalid_parameters_raise(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_text("text", size=size, overlap=overlap)
