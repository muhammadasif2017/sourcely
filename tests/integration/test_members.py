import pytest
from sqlalchemy import text

from tests.conftest import csrf


def _workspace(owner):
    return owner.post("/workspaces", json={"name": "Team"}, headers=csrf(owner)).json()["id"]


def _add(owner_db, ws, email, role):
    owner_db.execute(
        text(
            "INSERT INTO memberships (workspace_id, user_id, role) "
            "SELECT :w, id, :r FROM users WHERE email = :e"
        ),
        {"w": ws, "r": role, "e": email},
    )


def _uid(owner_db, email):
    return str(
        owner_db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar_one()
    )


@pytest.fixture
def team(sign_in, owner_db):
    """A workspace with an owner, an admin, an editor and a viewer, each signed in."""
    clients = {"owner": sign_in("owner@example.com", name="Olive")}
    ws = _workspace(clients["owner"])
    for role, name in (("admin", "Adam"), ("editor", "Eda"), ("viewer", "Vic")):
        clients[role] = sign_in(f"{role}@example.com", name=name)
        _add(owner_db, ws, f"{role}@example.com", role)
    ids = {role: _uid(owner_db, f"{role}@example.com") for role in clients}
    return clients, ws, ids


def _set_role(client, ws, user_id, role):
    return client.patch(
        f"/workspaces/{ws}/members/{user_id}", json={"role": role}, headers=csrf(client)
    )


def _remove(client, ws, user_id):
    return client.delete(f"/workspaces/{ws}/members/{user_id}", headers=csrf(client))


# --- listing ------------------------------------------------------------------------------


def test_list_members_sorted_by_role_then_name(team):
    clients, ws, ids = team
    r = clients["admin"].get(f"/workspaces/{ws}/members")
    assert r.status_code == 200
    assert r.json()["members"] == [
        {"user_id": ids["owner"], "name": "Olive", "email": "owner@example.com", "role": "owner"},
        {"user_id": ids["admin"], "name": "Adam", "email": "admin@example.com", "role": "admin"},
        {"user_id": ids["editor"], "name": "Eda", "email": "editor@example.com", "role": "editor"},
        {"user_id": ids["viewer"], "name": "Vic", "email": "viewer@example.com", "role": "viewer"},
    ]


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_only_admins_list_members(team, role):
    clients, ws, _ = team
    assert clients[role].get(f"/workspaces/{ws}/members").status_code == 403


# --- changing roles -----------------------------------------------------------------------


def test_admin_changes_roles_below_their_own(team):
    clients, ws, ids = team
    r = _set_role(clients["admin"], ws, ids["editor"], "viewer")
    assert r.status_code == 200
    assert r.json() == {"user_id": ids["editor"], "role": "viewer"}
    assert clients["editor"].get("/me").json()["workspaces"][0]["role"] == "viewer"


@pytest.mark.parametrize(
    ("actor", "target", "role"),
    [
        ("admin", "viewer", "admin"),  # can't grant their own rank
        ("admin", "admin", "editor"),  # can't change someone at their rank (here: themself)
        ("admin", "owner", "viewer"),  # can't touch the owner
        ("owner", "owner", "admin"),  # the owner's role changes only by transfer
        ("editor", "viewer", "editor"),  # editors can't manage at all
    ],
)
def test_role_changes_that_are_refused(team, actor, target, role):
    clients, ws, ids = team
    assert _set_role(clients[actor], ws, ids[target], role).status_code == 403


def test_owner_can_promote_to_admin(team):
    clients, ws, ids = team
    assert _set_role(clients["owner"], ws, ids["editor"], "admin").status_code == 200


def test_owner_role_cannot_be_assigned(team):
    clients, ws, ids = team
    assert _set_role(clients["owner"], ws, ids["admin"], "owner").status_code == 422


def test_changing_a_non_member_is_404(team, sign_in, owner_db):
    clients, ws, _ = team
    sign_in("outsider@example.com")
    r = _set_role(clients["owner"], ws, _uid(owner_db, "outsider@example.com"), "viewer")
    assert r.status_code == 404
    assert r.json() == {"detail": "Member not found"}


# --- removing -----------------------------------------------------------------------------


def test_admin_removes_an_editor_who_then_gets_404(team):
    clients, ws, ids = team
    assert _remove(clients["admin"], ws, ids["editor"]).status_code == 204
    r = clients["editor"].get("/documents", headers={"X-Workspace-ID": ws})
    assert r.status_code == 404
    assert clients["editor"].get("/me").json()["workspaces"] == []


@pytest.mark.parametrize(
    ("actor", "target"),
    [("admin", "owner"), ("editor", "viewer"), ("viewer", "editor"), ("owner", "owner")],
)
def test_removals_that_are_refused(team, actor, target):
    clients, ws, ids = team
    assert _remove(clients[actor], ws, ids[target]).status_code == 403


@pytest.mark.parametrize("role", ["admin", "editor", "viewer"])
def test_members_can_leave(team, role):
    clients, ws, ids = team
    assert _remove(clients[role], ws, ids[role]).status_code == 204
    assert clients[role].get("/me").json()["workspaces"] == []


def test_owner_removes_an_admin(team):
    clients, ws, ids = team
    assert _remove(clients["owner"], ws, ids["admin"]).status_code == 204


def test_removing_a_non_member_is_404(team, sign_in, owner_db):
    clients, ws, _ = team
    sign_in("outsider@example.com")
    r = _remove(clients["owner"], ws, _uid(owner_db, "outsider@example.com"))
    assert r.status_code == 404


def test_member_routes_need_csrf(team):
    clients, ws, ids = team
    r = clients["owner"].delete(f"/workspaces/{ws}/members/{ids['viewer']}")
    assert r.status_code == 403
    assert clients["viewer"].get("/me").json()["workspaces"] != []
