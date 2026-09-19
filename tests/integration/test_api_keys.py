import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.auth import PrincipalDep
from tests.conftest import csrf


@pytest.fixture
def probe(app):
    """A test-only route that reports the resolved Principal."""

    @app.get("/_principal")
    def _principal(principal: PrincipalDep) -> dict[str, str | None]:
        return {
            "workspace_id": str(principal.workspace_id),
            "role": principal.role,
            "user_id": str(principal.user_id) if principal.user_id else None,
            "api_key_id": str(principal.api_key_id) if principal.api_key_id else None,
        }

    return "/_principal"


@pytest.fixture
def workspace(sign_in):
    owner = sign_in()
    r = owner.post("/workspaces", json={"name": "Acme"}, headers=csrf(owner))
    return owner, r.json()["id"]


def _create_key(client, workspace_id, name="Helpdesk bot"):
    return client.post(
        f"/workspaces/{workspace_id}/api-keys", json={"name": name}, headers=csrf(client)
    )


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


# --- managing keys ----------------------------------------------------------------------


def test_create_returns_the_key_once(workspace):
    owner, ws = workspace
    r = _create_key(owner, ws)
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"id", "name", "prefix", "key", "created_at"}
    assert body["key"].startswith("sk_live_")
    assert len(body["key"]) == len("sk_live_") + 43
    assert body["prefix"] == body["key"][:12]
    listed = owner.get(f"/workspaces/{ws}/api-keys").json()["api_keys"]
    assert len(listed) == 1
    assert "key" not in listed[0]
    assert listed[0]["prefix"] == body["prefix"]
    assert listed[0]["last_used_at"] is None
    assert listed[0]["revoked_at"] is None


def test_only_the_hash_is_stored(workspace, owner_db):
    owner, ws = workspace
    key = _create_key(owner, ws).json()["key"]
    row = owner_db.execute(text("SELECT key_hash, prefix FROM api_keys")).one()
    assert len(bytes(row.key_hash)) == 32
    assert key.encode() not in bytes(row.key_hash)
    assert row.prefix == key[:12]


@pytest.mark.parametrize("name", ["", "   ", "n" * 61])
def test_key_name_validation(workspace, name):
    owner, ws = workspace
    assert _create_key(owner, ws, name).status_code == 422


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_only_admins_manage_keys(workspace, sign_in, owner_db, role):
    owner, ws = workspace
    member = sign_in("member@example.com")
    owner_db.execute(
        text(
            "INSERT INTO memberships (workspace_id, user_id, role) "
            "SELECT :w, id, :r FROM users WHERE email = 'member@example.com'"
        ),
        {"w": ws, "r": role},
    )
    assert _create_key(member, ws).status_code == 403
    assert member.get(f"/workspaces/{ws}/api-keys").status_code == 403


def test_strangers_get_404(workspace, sign_in):
    _, ws = workspace
    stranger = sign_in("stranger@example.com")
    assert _create_key(stranger, ws).status_code == 404
    assert stranger.get(f"/workspaces/{ws}/api-keys").status_code == 404


def test_create_needs_csrf(workspace):
    owner, ws = workspace
    r = owner.post(f"/workspaces/{ws}/api-keys", json={"name": "x"})
    assert r.status_code == 403


# --- using keys ---------------------------------------------------------------------------


def test_key_resolves_to_editor_in_its_workspace(workspace, anon_client, probe):
    owner, ws = workspace
    created = _create_key(owner, ws).json()
    r = anon_client.get(probe, headers=_bearer(created["key"]))
    assert r.status_code == 200
    assert r.json() == {
        "workspace_id": ws,
        "role": "editor",
        "user_id": None,
        "api_key_id": created["id"],
    }


def test_matching_workspace_header_is_allowed_and_mismatch_is_400(workspace, anon_client, probe):
    owner, ws = workspace
    key = _create_key(owner, ws).json()["key"]
    assert anon_client.get(probe, headers={**_bearer(key), "X-Workspace-ID": ws}).status_code == 200
    other = owner.post("/workspaces", json={"name": "Other"}, headers=csrf(owner)).json()["id"]
    r = anon_client.get(probe, headers={**_bearer(key), "X-Workspace-ID": other})
    assert r.status_code == 400


@pytest.mark.parametrize(
    "authorization",
    ["Bearer sk_live_" + "x" * 43, "Bearer not-a-key", "Bearer ", "Basic abc"],
)
def test_invalid_keys_are_401(anon_client, probe, authorization):
    r = anon_client.get(probe, headers={"Authorization": authorization})
    assert r.status_code == 401


def test_revoked_key_stops_working_at_once(workspace, anon_client, probe):
    owner, ws = workspace
    created = _create_key(owner, ws).json()
    assert anon_client.get(probe, headers=_bearer(created["key"])).status_code == 200
    r = owner.delete(f"/workspaces/{ws}/api-keys/{created['id']}", headers=csrf(owner))
    assert r.status_code == 204
    assert anon_client.get(probe, headers=_bearer(created["key"])).status_code == 401
    listed = owner.get(f"/workspaces/{ws}/api-keys").json()["api_keys"]
    assert listed[0]["revoked_at"] is not None


def test_revoking_another_workspaces_key_is_404(workspace, sign_in):
    owner, ws = workspace
    key_id = _create_key(owner, ws).json()["id"]
    other = sign_in("other@example.com")
    other_ws = other.post("/workspaces", json={"name": "Mine"}, headers=csrf(other)).json()["id"]
    r = other.delete(f"/workspaces/{other_ws}/api-keys/{key_id}", headers=csrf(other))
    assert r.status_code == 404


def test_deleting_the_workspace_kills_its_keys(workspace, anon_client, probe):
    owner, ws = workspace
    key = _create_key(owner, ws).json()["key"]
    owner.request("DELETE", f"/workspaces/{ws}", json={"confirm_name": "Acme"}, headers=csrf(owner))
    assert anon_client.get(probe, headers=_bearer(key)).status_code == 401


def test_cookie_and_key_together_is_400(workspace, probe):
    owner, ws = workspace
    key = _create_key(owner, ws).json()["key"]
    r = owner.get(probe, headers={**_bearer(key), "X-Workspace-ID": ws})
    assert r.status_code == 400
    assert r.json() == {"detail": "Send either a session cookie or an API key, not both"}


def test_keys_cannot_use_session_only_endpoints(workspace, app):
    owner, ws = workspace
    key = _create_key(owner, ws).json()["key"]
    with TestClient(app) as bot:
        bot.headers.update(_bearer(key))
        assert bot.get("/me").status_code == 403
        assert bot.patch(f"/workspaces/{ws}", json={"name": "X"}).status_code == 403
        assert bot.post(f"/workspaces/{ws}/api-keys", json={"name": "x"}).status_code == 403
        assert bot.get(f"/workspaces/{ws}/api-keys").status_code == 403
        r = bot.post("/workspaces", json={"name": "X"})
        assert r.status_code == 403
        assert r.json() == {"detail": "This needs a signed-in user; API keys can't be used here"}


def test_last_used_is_updated_at_most_once_a_minute(workspace, anon_client, probe, owner_db):
    owner, ws = workspace
    key = _create_key(owner, ws).json()["key"]
    anon_client.get(probe, headers=_bearer(key))
    first = owner_db.execute(text("SELECT last_used_at FROM api_keys")).scalar_one()
    assert first is not None
    owner_db.execute(text("UPDATE api_keys SET last_used_at = now() - interval '30 seconds'"))
    recent = owner_db.execute(text("SELECT last_used_at FROM api_keys")).scalar_one()
    anon_client.get(probe, headers=_bearer(key))
    assert owner_db.execute(text("SELECT last_used_at FROM api_keys")).scalar_one() == recent
    owner_db.execute(text("UPDATE api_keys SET last_used_at = now() - interval '2 minutes'"))
    anon_client.get(probe, headers=_bearer(key))
    later = owner_db.execute(text("SELECT last_used_at FROM api_keys")).scalar_one()
    assert later > recent
