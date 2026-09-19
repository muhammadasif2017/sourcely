"""API key format and randomness."""

import re

from app.core.security import hash_token
from app.services.api_keys import KEY_PREFIX, SHOWN_PREFIX_LENGTH, generate_key

KEY_PATTERN = re.compile(r"^sk_live_[A-Za-z0-9_-]{43}$")


def test_key_format():
    key = generate_key()
    assert key.startswith(KEY_PREFIX)
    assert KEY_PATTERN.match(key), key


def test_keys_are_unique():
    assert len({generate_key() for _ in range(1000)}) == 1000


def test_shown_prefix_reveals_only_a_few_random_characters():
    key = generate_key()
    # 12 characters shown, of which only 4 are random: the rest is the fixed "sk_live_".
    assert SHOWN_PREFIX_LENGTH - len(KEY_PREFIX) == 4
    assert key[:SHOWN_PREFIX_LENGTH].startswith(KEY_PREFIX)


def test_stored_hash_is_sha256_of_the_whole_key():
    key = generate_key()
    assert len(hash_token(key)) == 32
    assert hash_token(key) != hash_token(key[:-1])
