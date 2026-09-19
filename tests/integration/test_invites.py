import re

import pytest
from sqlalchemy import text

from tests.conftest import TEST_PASSWORD, csrf


def _token(message) -> str:
    match = re.search(r"token=([A-Za-z0-9_-]+)", message.body)
    assert match, message.body
    return match.group(1)


@pytest.fixture
def owner_ws(sign_in):
    owner = sign_in("owner@example.com", name="Olive")
    ws = owner.post("/workspaces", json={"name": "Acme"}, headers=csrf(owner)).json()["id"]
    return owner, ws


def _invite(client, ws, emails, role="editor"):
    return client.post(
        f"/workspaces/{ws}/invites", json={"emails": emails, "role": role}, headers=csrf(client)
    )


def _accept(client, token):
    return client.post("/invites/accept", json={"token": token}, headers=csrf(client))


# --- creating -----------------------------------------------------------------------------


def test_invite_sends_email_and_lists_pending(owner_ws, outbox):
    owner, ws = owner_ws
    r = _invite(owner, ws, ["sara@example.com", "Bilal@Example.com"], "viewer")
    assert r.status_code == 201
    invites = r.json()["invites"]
    assert [(i["email"], i["role"]) for i in invites] == [
        ("sara@example.com", "viewer"),
        ("bilal@example.com", "viewer"),
    ]
    message = outbox.last("sara@example.com")
    assert "Acme" in message.subject + message.body
    assert "Olive" in message.body
    assert "/invites/accept?token=" in message.body
    listed = owner.get(f"/workspaces/{ws}/invites").json()["invites"]
    assert {i["email"] for i in listed} == {"sara@example.com", "bilal@example.com"}


def test_duplicate_emails_are_merged(owner_ws):
    owner, ws = owner_ws
    r = _invite(owner, ws, ["a@example.com", "A@example.com"])
    assert [i["email"] for i in r.json()["invites"]] == ["a@example.com"]


def test_reinviting_replaces_the_pending_invite(owner_ws, outbox, anon_client, sign_in):
    owner, ws = owner_ws
    _invite(owner, ws, ["sara@example.com"], "viewer")
    old_token = _token(outbox.last("sara@example.com"))
    _invite(owner, ws, ["sara@example.com"], "editor")
    new_token = _token(outbox.last("sara@example.com"))
    assert len(owner.get(f"/workspaces/{ws}/invites").json()["invites"]) == 1
    sara = sign_in("sara@example.com")
    assert _accept(sara, old_token).status_code == 410
    assert _accept(sara, new_token).json()["role"] == "editor"


@pytest.mark.parametrize(
    "body",
    [
        {"emails": [], "role": "editor"},
        {"emails": [f"u{i}@example.com" for i in range(21)], "role": "editor"},
        {"emails": ["not-an-email"], "role": "editor"},
        {"emails": ["a@example.com"], "role": "owner"},
        {"emails": ["a@example.com"], "role": "boss"},
    ],
)
def test_invite_validation(owner_ws, body):
    owner, ws = owner_ws
    r = owner.post(f"/workspaces/{ws}/invites", json=body, headers=csrf(owner))
    assert r.status_code == 422


def test_inviting_an_existing_member_is_409(owner_ws):
    owner, ws = owner_ws
    r = _invite(owner, ws, ["owner@example.com"])
    assert r.status_code == 409
    assert r.json() == {"detail": "Already a member: owner@example.com"}


def test_admin_can_only_invite_below_admin(owner_ws, sign_in, owner_db):
    owner, ws = owner_ws
    admin = sign_in("admin@example.com")
    owner_db.execute(
        text(
            "INSERT INTO memberships (workspace_id, user_id, role) "
            "SELECT :w, id, 'admin' FROM users WHERE email = 'admin@example.com'"
        ),
        {"w": ws},
    )
    assert _invite(admin, ws, ["x@example.com"], "admin").status_code == 403
    assert _invite(admin, ws, ["x@example.com"], "editor").status_code == 201
    assert _invite(owner, ws, ["y@example.com"], "admin").status_code == 201


def test_editors_cannot_invite(owner_ws, sign_in, owner_db):
    owner, ws = owner_ws
    editor = sign_in("editor@example.com")
    owner_db.execute(
        text(
            "INSERT INTO memberships (workspace_id, user_id, role) "
            "SELECT :w, id, 'editor' FROM users WHERE email = 'editor@example.com'"
        ),
        {"w": ws},
    )
    assert _invite(editor, ws, ["x@example.com"], "viewer").status_code == 403


def test_only_the_token_hash_is_stored(owner_ws, outbox, owner_db):
    owner, ws = owner_ws
    _invite(owner, ws, ["sara@example.com"])
    token = _token(outbox.last("sara@example.com"))
    stored = bytes(owner_db.execute(text("SELECT token_hash FROM invites")).scalar_one())
    assert token.encode() not in stored and len(stored) == 32


# --- accepting ----------------------------------------------------------------------------


def test_accept_joins_the_workspace(owner_ws, outbox, sign_in):
    owner, ws = owner_ws
    _invite(owner, ws, ["sara@example.com"], "viewer")
    token = _token(outbox.last("sara@example.com"))
    sara = sign_in("sara@example.com")
    r = _accept(sara, token)
    assert r.status_code == 200
    assert r.json() == {"workspace_id": ws, "role": "viewer"}
    assert sara.get("/me").json()["workspaces"] == [{"id": ws, "name": "Acme", "role": "viewer"}]
    assert owner.get(f"/workspaces/{ws}/invites").json()["invites"] == []
    assert _accept(sara, token).status_code == 410  # single use


def test_invitee_can_sign_up_after_being_invited(owner_ws, outbox, anon_client):
    owner, ws = owner_ws
    _invite(owner, ws, ["new@example.com"], "editor")
    invite_token = _token(outbox.last("new@example.com"))
    anon_client.post(
        "/auth/signup",
        json={"name": "New", "email": "new@example.com", "password": TEST_PASSWORD},
    )
    verify = anon_client.post(
        "/auth/verify", json={"token": _token(outbox.last("new@example.com"))}
    )
    assert verify.status_code == 200
    assert _accept(anon_client, invite_token).json()["role"] == "editor"


def test_accept_with_another_email_is_409(owner_ws, outbox, sign_in):
    owner, ws = owner_ws
    _invite(owner, ws, ["sara@example.com"])
    token = _token(outbox.last("sara@example.com"))
    other = sign_in("other@example.com")
    r = _accept(other, token)
    assert r.status_code == 409
    assert r.json() == {"detail": "This invite is for a different email address"}
    assert other.get("/me").json()["workspaces"] == []


@pytest.mark.parametrize("state", ["expired", "revoked", "unknown"])
def test_invalid_invites_are_410(owner_ws, outbox, sign_in, owner_db, state):
    owner, ws = owner_ws
    r = _invite(owner, ws, ["sara@example.com"])
    token = _token(outbox.last("sara@example.com"))
    if state == "expired":
        owner_db.execute(text("UPDATE invites SET expires_at = now() - interval '1 minute'"))
    elif state == "revoked":
        invite_id = r.json()["invites"][0]["id"]
        assert (
            owner.delete(f"/workspaces/{ws}/invites/{invite_id}", headers=csrf(owner)).status_code
            == 204
        )
    else:
        token = "no-such-token"
    sara = sign_in("sara@example.com")
    r = _accept(sara, token)
    assert r.status_code == 410
    assert r.json() == {"detail": "This invite is no longer valid. Ask for a new one."}


def test_accept_needs_a_session_and_csrf(owner_ws, outbox, anon_client, sign_in):
    owner, ws = owner_ws
    _invite(owner, ws, ["sara@example.com"])
    token = _token(outbox.last("sara@example.com"))
    assert anon_client.post("/invites/accept", json={"token": token}).status_code == 401
    sara = sign_in("sara@example.com")
    assert sara.post("/invites/accept", json={"token": token}).status_code == 403


def test_revoking_another_workspaces_invite_is_404(owner_ws, sign_in):
    owner, ws = owner_ws
    invite_id = _invite(owner, ws, ["sara@example.com"]).json()["invites"][0]["id"]
    other = sign_in("other@example.com")
    other_ws = other.post("/workspaces", json={"name": "Mine"}, headers=csrf(other)).json()["id"]
    r = other.delete(f"/workspaces/{other_ws}/invites/{invite_id}", headers=csrf(other))
    assert r.status_code == 404
