"""Cross-tenant tests, generated from the app's route table.

Every route that resolves a `Principal` (every workspace data route) must appear in CASES,
or `test_every_workspace_route_has_an_isolation_case` fails. So a new data route can't be
added without a test proving workspace B can't reach workspace A's data through it.
"""

import json
import uuid

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.auth import get_principal
from app.core.security import hash_token
from app.services.api_keys import generate_key
from app.services.rag import NO_CONTEXT_ANSWER
from tests.conftest import csrf

SECRET_TEXT = "Workspace A's secret: the launch code is purple giraffe"
SECRET_ID = "secret"


def _make_key(owner_db, name: str) -> str:
    workspace_id = uuid.uuid4()
    key = generate_key()
    owner_db.execute(
        text("INSERT INTO workspaces (id, name) VALUES (:id, :n)"), {"id": workspace_id, "n": name}
    )
    owner_db.execute(
        text(
            "INSERT INTO api_keys (id, workspace_id, name, prefix, key_hash) "
            "VALUES (:id, :w, 'k', :p, :h)"
        ),
        {"id": uuid.uuid4(), "w": workspace_id, "p": key[:12], "h": hash_token(key)},
    )
    return key


def _depends_on_principal(dependant) -> bool:
    return any(d.call is get_principal or _depends_on_principal(d) for d in dependant.dependencies)


def _api_routes(routes) -> list[APIRoute]:
    """Every APIRoute, including those inside included routers.

    FastAPI 0.141 keeps an included router as one `_IncludedRouter` entry in `app.routes`
    (with the router under `original_router`) instead of copying its routes, so walk into it.
    """
    found: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
        elif (included := getattr(route, "original_router", None)) is not None:
            found.extend(_api_routes(included.routes))
    return found


def _workspace_routes(app) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in _api_routes(app.routes)
        if _depends_on_principal(route.dependant)
        for method in route.methods
    }


@pytest.fixture
def tenants(app, owner_db):
    """Workspace A holds a secret document; workspace B is a separate tenant. Two clients."""
    a = TestClient(app, headers={"Authorization": f"Bearer {_make_key(owner_db, 'A')}"})
    b = TestClient(app, headers={"Authorization": f"Bearer {_make_key(owner_db, 'B')}"})
    a.__enter__()
    b.__enter__()
    r = a.post(
        "/documents",
        json={"text": SECRET_TEXT, "document_id": SECRET_ID, "metadata": {"level": "top"}},
    )
    assert r.status_code == 201
    yield a, b
    b.__exit__(None, None, None)
    a.__exit__(None, None, None)


def _a_still_has_secret(a: TestClient) -> None:
    docs = a.get("/documents").json()["documents"]
    assert [d["document_id"] for d in docs] == [SECRET_ID]
    hits = a.post("/search", json={"query": "launch code purple giraffe", "top_k": 1}).json()
    assert hits["results"][0]["text"] == SECRET_TEXT


def _list(a, b, llm):
    r = b.get("/documents")
    assert r.status_code == 200
    assert r.json() == {"documents": []}


def _create(a, b, llm):
    r = b.post("/documents", json={"text": "B's own text", "document_id": SECRET_ID})
    assert r.status_code == 201  # B gets its own document with the same id...
    _a_still_has_secret(a)  # ...and A's is untouched.


def _upload(a, b, llm):
    r = b.post(
        "/documents/upload",
        files={"file": ("x.txt", b"B's own file")},
        data={"document_id": SECRET_ID},
    )
    assert r.status_code == 201
    _a_still_has_secret(a)


def _delete(a, b, llm):
    assert b.delete(f"/documents/{SECRET_ID}").status_code == 404
    _a_still_has_secret(a)


def _search(a, b, llm):
    r = b.post("/search", json={"query": "launch code purple giraffe", "top_k": 20})
    assert r.status_code == 200
    assert r.json()["results"] == []
    filtered = b.post(
        "/search",
        json={"query": "launch code", "filters": {"document_ids": [SECRET_ID]}},
    )
    assert filtered.json()["results"] == []


def _ask(a, b, llm):
    r = b.post("/ask", json={"question": "What is the launch code?"})
    assert r.status_code == 200
    assert r.json()["answer"] == NO_CONTEXT_ANSWER
    assert r.json()["sources"] == []
    assert llm.calls == []  # A's text never reached the prompt


def _ask_stream(a, b, llm):
    r = b.post("/ask/stream", json={"question": "What is the launch code?"})
    assert r.status_code == 200
    first = r.text.split("\n\n")[0]
    assert json.loads(first.split("data: ", 1)[1])["sources"] == []
    assert "purple giraffe" not in r.text
    assert llm.calls == []


CASES = {
    ("GET", "/documents"): _list,
    ("POST", "/documents"): _create,
    ("POST", "/documents/upload"): _upload,
    ("DELETE", "/documents/{document_id}"): _delete,
    ("POST", "/search"): _search,
    ("POST", "/ask"): _ask,
    ("POST", "/ask/stream"): _ask_stream,
}


def test_route_discovery_finds_routes(app):
    # Guards the test below: an empty discovery would make it pass for the wrong reason.
    paths = {route.path for route in _api_routes(app.routes)}
    assert {"/health", "/documents", "/workspaces", "/auth/login"} <= paths


def test_every_workspace_route_has_an_isolation_case(app):
    assert _workspace_routes(app) == set(CASES), (
        "Add a cross-tenant case to CASES for each new workspace route"
    )


@pytest.mark.parametrize(("method", "path"), sorted(CASES))
def test_other_workspace_cannot_reach_data(tenants, llm, method, path):
    a, b = tenants
    CASES[(method, path)](a, b, llm)


@pytest.mark.parametrize(("method", "path"), sorted(CASES))
def test_workspace_routes_need_a_credential(anon_client, method, path):
    url = path.replace("{document_id}", SECRET_ID)
    assert anon_client.request(method, url).status_code == 401


# --- sessions, roles and the workspace header on data routes --------------------------------


def _session_workspace(sign_in, owner_db, role: str):
    owner = sign_in()
    ws = owner.post("/workspaces", json={"name": "Team"}, headers=csrf(owner)).json()["id"]
    if role == "owner":
        return owner, ws
    member = sign_in(f"{role}@example.com")
    owner_db.execute(
        text(
            "INSERT INTO memberships (workspace_id, user_id, role) "
            "SELECT :w, id, :r FROM users WHERE email = :e"
        ),
        {"w": ws, "r": role, "e": f"{role}@example.com"},
    )
    return member, ws


def test_session_works_with_workspace_header_and_csrf(sign_in, owner_db):
    owner, ws = _session_workspace(sign_in, owner_db, "owner")
    headers = {"X-Workspace-ID": ws, **csrf(owner)}
    assert (
        owner.post("/documents", json={"text": "Team notes."}, headers=headers).status_code == 201
    )
    assert len(owner.get("/documents", headers={"X-Workspace-ID": ws}).json()["documents"]) == 1
    # A write without the CSRF header is refused even with a valid session.
    r = owner.post("/documents", json={"text": "x"}, headers={"X-Workspace-ID": ws})
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("role", "can_write"), [("viewer", False), ("editor", True), ("admin", True)]
)
def test_roles_on_data_routes(sign_in, owner_db, role, can_write):
    member, ws = _session_workspace(sign_in, owner_db, role)
    read = {"X-Workspace-ID": ws}
    write = {**read, **csrf(member)}
    assert member.get("/documents", headers=read).status_code == 200
    assert member.post("/search", json={"query": "x"}, headers=write).status_code == 200
    created = member.post("/documents", json={"text": "Notes.", "document_id": "n"}, headers=write)
    assert created.status_code == (201 if can_write else 403)
    upload = member.post("/documents/upload", files={"file": ("a.txt", b"Notes.")}, headers=write)
    assert upload.status_code == (201 if can_write else 403)
    deleted = member.delete("/documents/n", headers=write)
    assert deleted.status_code == (204 if can_write else 403)
