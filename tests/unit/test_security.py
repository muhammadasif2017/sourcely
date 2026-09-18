"""Password hashing, token generation and the common-password check."""

import pytest

from app.core.security import (
    hash_password,
    hash_token,
    is_common_password,
    new_token,
    verify_password,
)


def test_password_hash_is_argon2id_and_verifies():
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert "correct horse" not in hashed
    assert verify_password(hashed, "correct horse battery staple")
    assert not verify_password(hashed, "correct horse battery stapler")


def test_same_password_hashes_differently_each_time():
    # A random salt per hash: equal passwords don't reveal themselves in the database.
    assert hash_password("same password here") != hash_password("same password here")


def test_verify_never_raises_on_garbage_hash():
    assert not verify_password("not-a-hash", "whatever password")


def test_new_tokens_are_long_random_and_url_safe():
    tokens = {new_token() for _ in range(100)}
    assert len(tokens) == 100
    for token in tokens:
        assert len(token) >= 43
        assert all(c.isalnum() or c in "-_" for c in token)


def test_token_hash_is_sha256_and_stable():
    assert hash_token("abc") == hash_token("abc")
    assert len(hash_token("abc")) == 32
    assert hash_token("abc") != hash_token("abd")


@pytest.mark.parametrize("password", ["q1w2e3r4t5y6", "Q1W2E3R4T5Y6", "1qaz2wsx3edc"])
def test_common_passwords_are_detected_case_insensitively(password):
    assert is_common_password(password)


def test_uncommon_password_passes():
    assert not is_common_password("violet-anchor-tuesday-42")
