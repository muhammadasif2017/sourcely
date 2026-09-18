"""Split text into overlapping chunks on natural boundaries."""

# Coarsest boundary first: paragraphs, lines, sentences, words.
_SEPARATORS = ("\n\n", "\n", ". ", " ")


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split `text` into chunks of at most `size` characters.

    Splits on the coarsest boundary that fits (paragraph, line, sentence, word) and hard-cuts
    only text with no boundary at all. Consecutive chunks share up to `overlap` characters of
    trailing context, measured in whole pieces, so overlap never splits a sentence mid-way.
    Returns an empty list for blank text.
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap must be >= 0 and smaller than size")
    if not text.strip():
        return []

    chunks: list[str] = []
    window: list[str] = []
    length = 0
    for piece in _split(text, size, _SEPARATORS):
        if window and length + len(piece) > size:
            chunks.append("".join(window).strip())
            window, length = _tail(window, overlap)
            # The carried-over tail plus the new piece must still fit.
            while window and length + len(piece) > size:
                length -= len(window.pop(0))
        window.append(piece)
        length += len(piece)
    if window:
        chunks.append("".join(window).strip())
    return [c for c in chunks if c]


def _split(text: str, size: int, separators: tuple[str, ...]) -> list[str]:
    """Break text into pieces no longer than `size`, keeping separators attached."""
    if len(text) <= size:
        return [text]
    if not separators:
        return [text[i : i + size] for i in range(0, len(text), size)]

    sep, finer = separators[0], separators[1:]
    parts = text.split(sep)
    pieces: list[str] = []
    for i, part in enumerate(parts):
        piece = part + sep if i < len(parts) - 1 else part
        if piece:
            pieces.extend(_split(piece, size, finer))
    return pieces


def _tail(window: list[str], overlap: int) -> tuple[list[str], int]:
    """Return the trailing pieces of `window` whose total length fits in `overlap`."""
    tail: list[str] = []
    length = 0
    for piece in reversed(window):
        if length + len(piece) > overlap:
            break
        tail.insert(0, piece)
        length += len(piece)
    return tail, length
