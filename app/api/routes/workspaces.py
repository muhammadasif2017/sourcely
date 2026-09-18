"""Workspace routes: create, rename, delete and transfer ownership.

These routes name the workspace in the path, so they use `MemberDep` rather than the
`X-Workspace-ID` header that data routes use.
"""

from fastapi import APIRouter, Response, status

from app.api.auth import MemberDep, SessionDep, require
from app.api.deps import DbDep
from app.core.errors import AppError
from app.schemas.workspaces import (
    TransferResult,
    WorkspaceCreate,
    WorkspaceDelete,
    WorkspaceOut,
    WorkspaceRename,
    WorkspaceTransfer,
    WorkspaceWithRole,
)
from app.services import workspaces

router = APIRouter(tags=["workspaces"])


@router.post("/workspaces", response_model=WorkspaceWithRole, status_code=status.HTTP_201_CREATED)
def create_workspace(body: WorkspaceCreate, current: SessionDep, db: DbDep) -> WorkspaceWithRole:
    """Create a workspace. The caller becomes its owner."""
    workspace = workspaces.create_workspace(db, current.user, body.name)
    return WorkspaceWithRole(id=workspace.id, name=workspace.name, role="owner")


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
def rename_workspace(body: WorkspaceRename, member: MemberDep, db: DbDep) -> WorkspaceOut:
    """Rename the workspace. Admins and the owner only."""
    require(member, "manage")
    workspace = workspaces.rename(db, member.workspace_id, body.name)
    return WorkspaceOut(id=workspace.id, name=workspace.name)


@router.delete("/workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(body: WorkspaceDelete, member: MemberDep, db: DbDep) -> Response:
    """Delete the workspace and everything in it. The owner only, with the name as confirmation."""
    require(member, "own")
    if body.confirm_name != workspaces.get_workspace(db, member.workspace_id).name:
        raise AppError(status.HTTP_400_BAD_REQUEST, "Type the workspace name exactly to confirm")
    workspaces.delete_workspace(db, member.workspace_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workspaces/{workspace_id}/transfer", response_model=TransferResult)
def transfer_ownership(body: WorkspaceTransfer, member: MemberDep, db: DbDep) -> TransferResult:
    """Make another member the owner. The previous owner becomes an admin."""
    require(member, "own")
    if member.user_id is None:
        raise AppError(status.HTTP_403_FORBIDDEN, "Only a signed-in owner can transfer ownership")
    try:
        workspaces.transfer_ownership(db, member.workspace_id, member.user_id, body.user_id)
    except workspaces.InvalidTransfer as exc:
        raise AppError(status.HTTP_400_BAD_REQUEST, "You already own this workspace") from exc
    except workspaces.MemberNotFound as exc:
        raise AppError(status.HTTP_404_NOT_FOUND, "Member not found") from exc
    return TransferResult(owner_user_id=body.user_id)
