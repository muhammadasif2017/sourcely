"""Request and response models for workspaces."""

import uuid
from typing import Annotated

from pydantic import BaseModel, StringConstraints

WorkspaceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
]


class WorkspaceCreate(BaseModel):
    """A new workspace."""

    name: WorkspaceName


class WorkspaceRename(BaseModel):
    """A new name for a workspace."""

    name: WorkspaceName


class WorkspaceDelete(BaseModel):
    """Deleting needs the exact current name, as a guard against the wrong workspace."""

    confirm_name: str


class WorkspaceTransfer(BaseModel):
    """The member who becomes the new owner."""

    user_id: uuid.UUID


class WorkspaceOut(BaseModel):
    """A workspace."""

    id: uuid.UUID
    name: str


class WorkspaceWithRole(WorkspaceOut):
    """A workspace and the caller's role in it."""

    role: str


class TransferResult(BaseModel):
    """Who owns the workspace now."""

    owner_user_id: uuid.UUID
