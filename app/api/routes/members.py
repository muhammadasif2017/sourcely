"""Member and invite routes. Signed-in users only; API keys get 403 through `SessionDep`."""

import uuid

from fastapi import APIRouter, Request, Response, status

from app.api.auth import MemberDep, SessionDep, require
from app.api.deps import DbDep, SettingsDep
from app.core.errors import AppError
from app.schemas.members import (
    InviteAccept,
    InviteAccepted,
    InviteCreate,
    InviteList,
    InviteOut,
    MemberList,
    MemberOut,
    RoleChange,
    RoleChanged,
)
from app.services import invites, workspaces
from app.services.email import EmailSender

router = APIRouter(tags=["members"])

MEMBER_NOT_FOUND = "Member not found"


def _not_allowed(exc: workspaces.NotAllowed) -> AppError:
    return AppError(status.HTTP_403_FORBIDDEN, exc.reason)


@router.get("/workspaces/{workspace_id}/members", response_model=MemberList)
def list_members(member: MemberDep, db: DbDep) -> MemberList:
    """Everyone in the workspace with their role. Admins and the owner."""
    require(member, "manage")
    return MemberList(
        members=[
            MemberOut(user_id=user.id, name=user.name, email=user.email, role=role)
            for user, role in workspaces.list_members(db, member.workspace_id)
        ]
    )


@router.patch("/workspaces/{workspace_id}/members/{user_id}", response_model=RoleChanged)
def change_member_role(
    user_id: uuid.UUID, body: RoleChange, member: MemberDep, db: DbDep
) -> RoleChanged:
    """Change a member's role. Only to, and only for, roles below the caller's own."""
    require(member, "manage")
    try:
        changed = workspaces.change_role(db, member.workspace_id, member.role, user_id, body.role)
    except workspaces.MemberNotFound as exc:
        raise AppError(status.HTTP_404_NOT_FOUND, MEMBER_NOT_FOUND) from exc
    except workspaces.NotAllowed as exc:
        raise _not_allowed(exc) from exc
    return RoleChanged(user_id=changed.user_id, role=changed.role)


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_member(
    user_id: uuid.UUID, member: MemberDep, current: SessionDep, db: DbDep
) -> Response:
    """Remove a member, or leave the workspace yourself (anyone but the owner)."""
    try:
        workspaces.remove_member(db, member.workspace_id, current.user.id, member.role, user_id)
    except workspaces.MemberNotFound as exc:
        raise AppError(status.HTTP_404_NOT_FOUND, MEMBER_NOT_FOUND) from exc
    except workspaces.NotAllowed as exc:
        raise _not_allowed(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/workspaces/{workspace_id}/invites",
    response_model=InviteList,
    status_code=status.HTTP_201_CREATED,
)
def create_invites(
    body: InviteCreate,
    request: Request,
    member: MemberDep,
    current: SessionDep,
    db: DbDep,
    settings: SettingsDep,
) -> InviteList:
    """Invite people by email with a role below your own. Each gets a single-use link."""
    require(member, "manage")
    sender: EmailSender = request.app.state.email_sender
    try:
        created = invites.create_invites(
            db,
            sender,
            settings.app_base_url,
            workspaces.get_workspace(db, member.workspace_id),
            current.user,
            member.role,
            [str(email) for email in body.emails],
            body.role,
        )
    except workspaces.NotAllowed as exc:
        raise _not_allowed(exc) from exc
    except invites.AlreadyMember as exc:
        raise AppError(status.HTTP_409_CONFLICT, f"Already a member: {exc.email}") from exc
    return InviteList(invites=[InviteOut.model_validate(i, from_attributes=True) for i in created])


@router.get("/workspaces/{workspace_id}/invites", response_model=InviteList)
def list_invites(member: MemberDep, db: DbDep) -> InviteList:
    """Invites that haven't been accepted and haven't expired."""
    require(member, "manage")
    return InviteList(
        invites=[
            InviteOut.model_validate(i, from_attributes=True)
            for i in invites.list_pending(db, member.workspace_id)
        ]
    )


@router.delete(
    "/workspaces/{workspace_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_invite(invite_id: uuid.UUID, member: MemberDep, db: DbDep) -> Response:
    """Revoke an invite; its link stops working."""
    require(member, "manage")
    if not invites.revoke(db, member.workspace_id, invite_id):
        raise AppError(status.HTTP_404_NOT_FOUND, "Invite not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invites/accept", response_model=InviteAccepted)
def accept_invite(body: InviteAccept, current: SessionDep, db: DbDep) -> InviteAccepted:
    """Join a workspace with the token from an invite email, signed in as the invited address."""
    try:
        accepted = invites.accept(db, body.token, current.user)
    except invites.InviteGone as exc:
        raise AppError(
            status.HTTP_410_GONE, "This invite is no longer valid. Ask for a new one."
        ) from exc
    except invites.WrongEmail as exc:
        raise AppError(
            status.HTTP_409_CONFLICT, "This invite is for a different email address"
        ) from exc
    return InviteAccepted(workspace_id=accepted.workspace_id, role=accepted.role)
