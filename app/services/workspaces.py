"""Workspaces, memberships and the role rules (SPEC.md, Phase 1, "Roles")."""

import uuid
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Membership, User, Workspace

Role = Literal["owner", "admin", "editor", "viewer"]
ROLES: tuple[Role, ...] = ("owner", "admin", "editor", "viewer")

# What a caller wants to do, from least to most privileged:
#   read   list documents, search, ask
#   write  add, replace or delete documents
#   manage rename the workspace; members, invites and API keys
#   own    delete the workspace, transfer ownership
Action = Literal["read", "write", "manage", "own"]

_RANK: dict[str, int] = {"viewer": 0, "editor": 1, "admin": 2, "owner": 3}
_MINIMUM_ROLE: dict[Action, Role] = {
    "read": "viewer",
    "write": "editor",
    "manage": "admin",
    "own": "owner",
}


class WorkspaceError(Exception):
    """Base class for workspace failures that routes turn into HTTP errors."""


class MemberNotFound(WorkspaceError):
    """The user isn't a member of this workspace."""


class InvalidTransfer(WorkspaceError):
    """Ownership can't move to the current owner."""


def rank(role: str) -> int:
    """How privileged a role is: viewer 0 up to owner 3. Unknown roles rank below viewer."""
    return _RANK.get(role, -1)


def allowed(role: str, action: Action) -> bool:
    """True if `role` may perform `action`. This is the single place the role table lives."""
    return rank(role) >= rank(_MINIMUM_ROLE[action])


def create_workspace(db: Session, owner: User, name: str) -> Workspace:
    """A new workspace with `owner` as its only member."""
    workspace = Workspace(id=uuid.uuid4(), name=name)
    db.add(workspace)
    db.flush()
    db.add(Membership(workspace_id=workspace.id, user_id=owner.id, role="owner"))
    db.flush()
    return workspace


def memberships_of(db: Session, user_id: uuid.UUID) -> list[tuple[Workspace, str]]:
    """Every workspace the user belongs to, with their role, sorted by name (ignoring case)."""
    rows = db.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user_id)
        .order_by(func.lower(Workspace.name), Workspace.id)
    ).all()
    return [(workspace, role) for workspace, role in rows]


def get_membership(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
    """The user's membership in the workspace, or None if they don't belong to it."""
    return db.get(Membership, (workspace_id, user_id))


def get_workspace(db: Session, workspace_id: uuid.UUID) -> Workspace:
    """The workspace with this id. The caller has already checked membership."""
    return db.get_one(Workspace, workspace_id)


def rename(db: Session, workspace_id: uuid.UUID, name: str) -> Workspace:
    """Give the workspace a new name."""
    workspace = get_workspace(db, workspace_id)
    workspace.name = name
    return workspace


def delete_workspace(db: Session, workspace_id: uuid.UUID) -> None:
    """Delete the workspace. Foreign keys cascade to everything that belongs to it."""
    db.delete(db.get_one(Workspace, workspace_id))


def transfer_ownership(
    db: Session, workspace_id: uuid.UUID, current_owner_id: uuid.UUID, new_owner_id: uuid.UUID
) -> None:
    """Make another member the owner; the previous owner becomes an admin.

    Raises `InvalidTransfer` for the current owner and `MemberNotFound` for a non-member.
    """
    if new_owner_id == current_owner_id:
        raise InvalidTransfer
    new_owner = get_membership(db, workspace_id, new_owner_id)
    if new_owner is None:
        raise MemberNotFound
    old_owner = db.get_one(Membership, (workspace_id, current_owner_id))
    # Demote first and flush: the one-owner index is checked per statement, so promoting
    # first would briefly mean two owners and fail.
    old_owner.role = "admin"
    db.flush()
    new_owner.role = "owner"
    db.flush()
