import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.auth import PrincipalDep
from tests.conftest import csrf


def _create(client, name="Acme Support"):
    r = client.post("/workspaces", json={"name": name}, headers=csrf(client))
    assert r.status_code == 201, r.text
    return r.json()


def _add_member(owner_db, workspace_id, email, role):
    """Arrange a membership directly; invites and member management arrive in Task 17."""
    owner_db.execute(
        text(
            "INSERT INTO memberships (workspace_id, user_id, role) "
            "SELECT :w, id, :r FROM users WHERE email = :e"
        ),
        {"w": workspace_id, "r": role, "e": email},
    )


def _user_id(owner_db, email):
    return str(
        owner_db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar_one()
    )


# --- create and list --------------------------------------------------------------------


def test_create_workspace_makes_caller_owner(sign_in):
    owner = sign_in()
    body = _create(owner)
    assert body["name"] == "Acme Support"
    assert body["role"] == "owner"
    uuid.UUID(body["id"])
    assert owner.get("/me").json()["workspaces"] == [body]


def test_me_lists_workspaces_sorted_by_name(sign_in):
    owner = sign_in()
    b = _create(owner, "Beta")
    a = _create(owner, "alpha")
    assert [w["id"] for w in owner.get("/me").json()["workspaces"]] == [a["id"], b["id"]]


@pytest.mark.parametrize("name", ["", "   ", "n" * 61])
def test_workspace_name_validation(sign_in, name):
    owner = sign_in()
    r = owner.post("/workspaces", json={"name": name}, headers=csrf(owner))
    assert r.status_code == 422


def test_create_needs_session_and_csrf(sign_in, anon_client):
    assert anon_client.post("/workspaces", json={"name": "X"}).status_code == 401
    owner = sign_in()
    assert owner.post("/workspaces", json={"name": "X"}).status_code == 403


def test_name_is_trimmed(sign_in):
    owner = sign_in()
    assert _create(owner, "  Acme  ")["name"] == "Acme"


# --- rename ------------------------------------------------------------------------------


@pytest.mark.parametrize(("role", "status"), [("admin", 200), ("editor", 403), ("viewer", 403)])
def test_rename_needs_admin(sign_in, owner_db, role, status):
    owner = sign_in()
    ws = _create(owner)
    member = sign_in("member@example.com")
    _add_member(owner_db, ws["id"], "member@example.com", role)
    r = member.patch(f"/workspaces/{ws['id']}", json={"name": "Renamed"}, headers=csrf(member))
    assert r.status_code == status
    if status == 200:
        assert r.json() == {"id": ws["id"], "name": "Renamed"}


def test_owner_can_rename(sign_in):
    owner = sign_in()
    ws = _create(owner)
    r = owner.patch(f"/workspaces/{ws['id']}", json={"name": "New"}, headers=csrf(owner))
    assert r.status_code == 200
    assert owner.get("/me").json()["workspaces"][0]["name"] == "New"


def test_non_member_gets_404_not_403(sign_in):
    owner = sign_in()
    ws = _create(owner)
    stranger = sign_in("stranger@example.com")
    r = stranger.patch(f"/workspaces/{ws['id']}", json={"name": "Hijack"}, headers=csrf(stranger))
    assert r.status_code == 404
    assert r.json() == {"detail": "Workspace not found"}


def test_unknown_or_malformed_workspace_id_is_404(sign_in):
    owner = sign_in()
    for workspace_id in (uuid.uuid4(), "not-a-uuid"):
        r = owner.patch(f"/workspaces/{workspace_id}", json={"name": "X"}, headers=csrf(owner))
        assert r.status_code == 404


# --- delete ------------------------------------------------------------------------------


def _delete(client, workspace_id, confirm_name):
    return client.request(
        "DELETE",
        f"/workspaces/{workspace_id}",
        json={"confirm_name": confirm_name},
        headers=csrf(client),
    )


def test_owner_deletes_with_name_confirmation(sign_in, owner_db):
    owner = sign_in()
    ws = _create(owner)
    member = sign_in("member@example.com")
    _add_member(owner_db, ws["id"], "member@example.com", "editor")
    r = _delete(owner, ws["id"], "Wrong Name")
    assert r.status_code == 400
    assert r.json() == {"detail": "Type the workspace name exactly to confirm"}
    assert _delete(owner, ws["id"], "Acme Support").status_code == 204
    assert owner.get("/me").json()["workspaces"] == []
    assert member.get("/me").json()["workspaces"] == []
    count = owner_db.execute(text("SELECT count(*) FROM memberships")).scalar_one()
    assert count == 0


def test_admin_cannot_delete(sign_in, owner_db):
    owner = sign_in()
    ws = _create(owner)
    admin = sign_in("admin@example.com")
    _add_member(owner_db, ws["id"], "admin@example.com", "admin")
    assert _delete(admin, ws["id"], "Acme Support").status_code == 403


# --- transfer ownership ------------------------------------------------------------------


def test_transfer_ownership(sign_in, owner_db):
    owner = sign_in()
    ws = _create(owner)
    member = sign_in("member@example.com")
    _add_member(owner_db, ws["id"], "member@example.com", "editor")
    r = owner.post(
        f"/workspaces/{ws['id']}/transfer",
        json={"user_id": _user_id(owner_db, "member@example.com")},
        headers=csrf(owner),
    )
    assert r.status_code == 200
    assert r.json() == {"owner_user_id": _user_id(owner_db, "member@example.com")}
    assert owner.get("/me").json()["workspaces"][0]["role"] == "admin"
    assert member.get("/me").json()["workspaces"][0]["role"] == "owner"
    # The former owner is now an admin and can't delete any more.
    assert _delete(owner, ws["id"], "Acme Support").status_code == 403


def test_transfer_to_non_member_is_404(sign_in, owner_db):
    owner = sign_in()
    ws = _create(owner)
    sign_in("outsider@example.com")
    r = owner.post(
        f"/workspaces/{ws['id']}/transfer",
        json={"user_id": _user_id(owner_db, "outsider@example.com")},
        headers=csrf(owner),
    )
    assert r.status_code == 404
    assert r.json() == {"detail": "Member not found"}


def test_transfer_to_self_is_400(sign_in, owner_db):
    owner = sign_in()
    ws = _create(owner)
    r = owner.post(
        f"/workspaces/{ws['id']}/transfer",
        json={"user_id": _user_id(owner_db, "owner@example.com")},
        headers=csrf(owner),
    )
    assert r.status_code == 400


def test_only_owner_can_transfer(sign_in, owner_db):
    owner = sign_in()
    ws = _create(owner)
    admin = sign_in("admin@example.com")
    _add_member(owner_db, ws["id"], "admin@example.com", "admin")
    r = admin.post(
        f"/workspaces/{ws['id']}/transfer",
        json={"user_id": _user_id(owner_db, "admin@example.com")},
        headers=csrf(admin),
    )
    assert r.status_code == 403


def test_database_allows_only_one_owner(sign_in, owner_db):
    owner = sign_in()
    ws = _create(owner)
    sign_in("second@example.com")
    with pytest.raises(IntegrityError):
        _add_member(owner_db, ws["id"], "second@example.com", "owner")


# --- the Principal: session + X-Workspace-ID ----------------------------------------------


@pytest.fixture
def probe(app):
    """A test-only route that reports the resolved Principal."""

    @app.get("/_principal")
    def _principal(principal: PrincipalDep) -> dict[str, str]:
        return {"workspace_id": str(principal.workspace_id), "role": principal.role}

    return "/_principal"


def test_principal_from_session_and_header(sign_in, probe):
    owner = sign_in()
    ws = _create(owner)
    r = owner.get(probe, headers={"X-Workspace-ID": ws["id"]})
    assert r.status_code == 200
    assert r.json() == {"workspace_id": ws["id"], "role": "owner"}


def test_principal_needs_the_workspace_header(sign_in, probe):
    owner = sign_in()
    _create(owner)
    r = owner.get(probe)
    assert r.status_code == 400
    assert r.json() == {"detail": "X-Workspace-ID header required"}


@pytest.mark.parametrize("header", [str(uuid.uuid4()), "not-a-uuid"])
def test_principal_for_foreign_or_bad_workspace_is_404(sign_in, probe, header):
    owner = sign_in()
    _create(owner)
    assert owner.get(probe, headers={"X-Workspace-ID": header}).status_code == 404


def test_principal_of_another_users_workspace_is_404(sign_in, probe):
    owner = sign_in()
    ws = _create(owner)
    stranger = sign_in("stranger@example.com")
    assert stranger.get(probe, headers={"X-Workspace-ID": ws["id"]}).status_code == 404


def test_principal_without_session_is_401(anon_client, probe):
    r = anon_client.get(probe, headers={"X-Workspace-ID": str(uuid.uuid4())})
    assert r.status_code == 401
