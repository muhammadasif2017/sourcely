"""The role table from SPEC.md, Phase 1, as a table-driven test."""

import pytest

from app.services.workspaces import ROLES, Action, allowed

# (role, action) -> allowed, exactly as the spec's role table.
MATRIX = {
    "owner": {"read": True, "write": True, "manage": True, "own": True},
    "admin": {"read": True, "write": True, "manage": True, "own": False},
    "editor": {"read": True, "write": True, "manage": False, "own": False},
    "viewer": {"read": True, "write": False, "manage": False, "own": False},
}


@pytest.mark.parametrize(
    ("role", "action", "expected"),
    [(role, action, ok) for role, row in MATRIX.items() for action, ok in row.items()],
)
def test_permission_matrix(role, action, expected):
    assert allowed(role, action) is expected


def test_every_role_and_action_is_covered():
    assert set(MATRIX) == set(ROLES)
    assert {a for row in MATRIX.values() for a in row} == set(Action.__args__)


def test_unknown_role_is_never_allowed():
    assert not allowed("superuser", "read")
