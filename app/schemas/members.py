"""Request and response models for members and invites."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.auth import Email, Token

# Roles that can be given to someone. "owner" only moves by transfer.
AssignableRole = Literal["admin", "editor", "viewer"]
MAX_INVITES_PER_REQUEST = 20


class MemberOut(BaseModel):
    """A member of a workspace."""

    user_id: uuid.UUID
    name: str
    email: str
    role: str


class MemberList(BaseModel):
    """Members, owner first, then by role and name."""

    members: list[MemberOut]


class RoleChange(BaseModel):
    """A member's new role."""

    role: AssignableRole


class RoleChanged(BaseModel):
    """The member and the role they now have."""

    user_id: uuid.UUID
    role: str


class InviteCreate(BaseModel):
    """People to invite, all with the same role."""

    emails: Annotated[list[Email], Field(min_length=1, max_length=MAX_INVITES_PER_REQUEST)]
    role: AssignableRole


class InviteOut(BaseModel):
    """A pending invite. The token is only ever in the email."""

    id: uuid.UUID
    email: str
    role: str
    expires_at: datetime


class InviteList(BaseModel):
    """Invites."""

    invites: list[InviteOut]


class InviteAccept(BaseModel):
    """The token from an invite email."""

    token: Token


class InviteAccepted(BaseModel):
    """The workspace joined and the role held in it."""

    workspace_id: uuid.UUID
    role: str
