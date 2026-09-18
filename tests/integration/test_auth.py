import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

PASSWORD = "violet-anchor-tuesday-42"
SIGNUP_BODY = {"detail": "Check your email to finish signing up"}
RESET_BODY = {"detail": "If that email has an account, we sent a reset link"}
BAD_LOGIN = {"detail": "Email or password is incorrect"}


def _token(message) -> str:
    match = re.search(r"token=([A-Za-z0-9_-]+)", message.body)
    assert match, message.body
    return match.group(1)


def _signup(client, email="ayesha@example.com", password=PASSWORD, name="Ayesha"):
    return client.post("/auth/signup", json={"name": name, "email": email, "password": password})


def _signed_up_and_verified(client, outbox, email="ayesha@example.com"):
    _signup(client, email=email)
    r = client.post("/auth/verify", json={"token": _token(outbox.last(email))})
    assert r.status_code == 200
    return r


def _login(client, email="ayesha@example.com", password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def _csrf(client) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["sourcely_csrf"]}


# --- sign up and verify -----------------------------------------------------------------


def test_signup_sends_verification_email(anon_client, outbox):
    r = _signup(anon_client)
    assert r.status_code == 202
    assert r.json() == SIGNUP_BODY
    message = outbox.last("ayesha@example.com")
    assert "verify" in message.subject.lower()
    assert "/verify-email?token=" in message.body


def test_signup_for_existing_email_looks_identical(anon_client, outbox):
    _signup(anon_client)
    r = _signup(anon_client, email="Ayesha@Example.com", password="another-long-password-9")
    assert r.status_code == 202
    assert r.json() == SIGNUP_BODY
    message = outbox.last("Ayesha@Example.com")
    assert "already have an account" in message.body
    assert "token=" not in message.body


@pytest.mark.parametrize(
    "body",
    [
        {"name": "A", "email": "not-an-email", "password": PASSWORD},
        {"name": "A", "email": "a@example.com", "password": "short-11ch"},
        {"name": "A", "email": "a@example.com", "password": "x" * 129},
        {"name": "A", "email": "a@example.com", "password": "Q1W2E3R4T5Y6"},
        {"name": "   ", "email": "a@example.com", "password": PASSWORD},
        {"name": "n" * 81, "email": "a@example.com", "password": PASSWORD},
        {"email": "a@example.com", "password": PASSWORD},
    ],
)
def test_signup_validation(anon_client, outbox, body):
    assert anon_client.post("/auth/signup", json=body).status_code == 422
    assert outbox.messages == []


def test_verify_signs_in_and_sets_cookies(anon_client, outbox):
    r = _signed_up_and_verified(anon_client, outbox)
    assert r.json()["user"]["email"] == "ayesha@example.com"
    assert r.json()["user"]["name"] == "Ayesha"
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("sourcely_session="))
    csrf = next(c for c in cookies if c.startswith("sourcely_csrf="))
    assert "HttpOnly" in session and "SameSite=lax" in session and "Path=/" in session
    assert "HttpOnly" not in csrf
    assert anon_client.get("/me").status_code == 200


def test_verify_token_works_once(anon_client, outbox):
    _signup(anon_client)
    token = _token(outbox.last("ayesha@example.com"))
    assert anon_client.post("/auth/verify", json={"token": token}).status_code == 200
    r = anon_client.post("/auth/verify", json={"token": token})
    assert r.status_code == 400
    assert r.json() == {"detail": "This link is invalid or has expired"}


def test_expired_verify_token_is_rejected(anon_client, outbox, owner_db):
    _signup(anon_client)
    token = _token(outbox.last("ayesha@example.com"))
    owner_db.execute(text("UPDATE email_tokens SET expires_at = now() - interval '1 minute'"))
    assert anon_client.post("/auth/verify", json={"token": token}).status_code == 400


def test_unknown_verify_token_is_rejected(anon_client):
    assert anon_client.post("/auth/verify", json={"token": "nope"}).status_code == 400


# --- sign in ---------------------------------------------------------------------------


def test_login_with_right_password(anon_client, outbox):
    _signed_up_and_verified(anon_client, outbox)
    anon_client.cookies.clear()
    r = _login(anon_client)
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "ayesha@example.com"
    assert anon_client.get("/me").status_code == 200


def test_login_is_case_insensitive_for_email(anon_client, outbox):
    _signed_up_and_verified(anon_client, outbox)
    assert _login(anon_client, email="AYESHA@example.com").status_code == 200


def test_wrong_password_and_unknown_email_look_identical(anon_client, outbox):
    _signed_up_and_verified(anon_client, outbox)
    wrong = _login(anon_client, password="wrong-password-123")
    unknown = _login(anon_client, email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == BAD_LOGIN


def test_unverified_user_cannot_sign_in(anon_client):
    _signup(anon_client)
    r = _login(anon_client)
    assert r.status_code == 403
    assert r.json() == {"detail": "Email not verified"}


def test_login_throttled_after_five_failures(anon_client, outbox):
    _signed_up_and_verified(anon_client, outbox)
    for _ in range(5):
        assert _login(anon_client, password="wrong-password-123").status_code == 401
    r = _login(anon_client)  # even the right password
    assert r.status_code == 429
    assert 0 < int(r.headers["retry-after"]) <= 15 * 60
    # Another account isn't affected.
    _signed_up_and_verified(anon_client, outbox, email="sara@example.com")
    assert _login(anon_client, email="sara@example.com").status_code == 200


def test_old_failures_do_not_count(anon_client, outbox, owner_db):
    _signed_up_and_verified(anon_client, outbox)
    for _ in range(5):
        _login(anon_client, password="wrong-password-123")
    owner_db.execute(text("UPDATE login_attempts SET attempted_at = now() - interval '16 minutes'"))
    assert _login(anon_client).status_code == 200


# --- sessions --------------------------------------------------------------------------


def test_me_without_session_is_401(anon_client):
    assert anon_client.get("/me").status_code == 401
    anon_client.cookies.set("sourcely_session", "forged")
    assert anon_client.get("/me").status_code == 401


def test_me_returns_user_and_workspaces(anon_client, outbox):
    _signed_up_and_verified(anon_client, outbox)
    body = anon_client.get("/me").json()
    assert set(body["user"]) == {"id", "name", "email"}
    assert body["workspaces"] == []


def test_logout_needs_csrf_then_ends_session(anon_client, outbox):
    _signed_up_and_verified(anon_client, outbox)
    assert anon_client.post("/auth/logout").status_code == 403
    assert anon_client.post("/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    r = anon_client.post("/auth/logout", headers=_csrf(anon_client))
    assert r.status_code == 204
    assert anon_client.get("/me").status_code == 401


def test_idle_session_expires(anon_client, outbox, owner_db):
    _signed_up_and_verified(anon_client, outbox)
    owner_db.execute(text("UPDATE sessions SET last_seen_at = now() - interval '15 days'"))
    assert anon_client.get("/me").status_code == 401


def test_only_hashes_are_stored(anon_client, outbox, owner_db):
    _signed_up_and_verified(anon_client, outbox)
    raw = anon_client.cookies["sourcely_session"]
    stored = owner_db.execute(text("SELECT token_hash FROM sessions")).scalars().all()
    assert len(stored) == 1
    assert raw.encode() not in bytes(stored[0])
    password_hash = owner_db.execute(text("SELECT password_hash FROM users")).scalar_one()
    assert PASSWORD not in password_hash
    assert password_hash.startswith("$argon2id$")


# --- password reset --------------------------------------------------------------------


def test_reset_request_looks_identical_for_unknown_email(anon_client, outbox):
    r = anon_client.post("/auth/password-reset", json={"email": "nobody@example.com"})
    assert r.status_code == 202
    assert r.json() == RESET_BODY
    assert outbox.messages == []


def test_reset_changes_password_and_ends_every_session(anon_client, outbox, app):
    _signed_up_and_verified(anon_client, outbox)
    with TestClient(app) as other:
        assert _login(other).status_code == 200
        r = anon_client.post("/auth/password-reset", json={"email": "ayesha@example.com"})
        assert r.json() == RESET_BODY
        token = _token(outbox.last("ayesha@example.com"))
        new_password = "brand-new-password-77"
        r = anon_client.post(
            "/auth/password-reset/confirm", json={"token": token, "password": new_password}
        )
        assert r.status_code == 204
        assert anon_client.get("/me").status_code == 401
        assert other.get("/me").status_code == 401
    assert _login(anon_client).status_code == 401
    assert _login(anon_client, password=new_password).status_code == 200
    again = anon_client.post(
        "/auth/password-reset/confirm", json={"token": token, "password": "third-password-888"}
    )
    assert again.status_code == 400


def test_reset_confirm_validates_new_password(anon_client, outbox):
    _signed_up_and_verified(anon_client, outbox)
    anon_client.post("/auth/password-reset", json={"email": "ayesha@example.com"})
    token = _token(outbox.last("ayesha@example.com"))
    r = anon_client.post("/auth/password-reset/confirm", json={"token": token, "password": "short"})
    assert r.status_code == 422


def test_expired_reset_token_is_rejected(anon_client, outbox, owner_db):
    _signed_up_and_verified(anon_client, outbox)
    anon_client.post("/auth/password-reset", json={"email": "ayesha@example.com"})
    token = _token(outbox.last("ayesha@example.com"))
    owner_db.execute(
        text(
            "UPDATE email_tokens SET expires_at = now() - interval '1 second' "
            "WHERE purpose = 'reset'"
        )
    )
    r = anon_client.post(
        "/auth/password-reset/confirm", json={"token": token, "password": "brand-new-password-77"}
    )
    assert r.status_code == 400
