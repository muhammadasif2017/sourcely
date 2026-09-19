"""Invites: inviting people by email and accepting an invite."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.security import hash_token, new_token
from app.db.models import Invite, Membership, User, Workspace
from app.services.email import EmailMessage, EmailSender
from app.services.workspaces import NotAllowed, get_membership, rank

INVITE_TTL = timedelta(days=7)


class InviteError(Exception):
    """Base class for invite failures that routes turn into HTTP errors."""


class AlreadyMember(InviteError):
    """One of the invited emails already belongs to a member."""

    def __init__(self, email: str) -> None:
        super().__init__(email)
        self.email = email


class InviteGone(InviteError):
    """The invite doesn't exist, was used, revoked or has expired."""


class WrongEmail(InviteError):
    """The signed-in user isn't the person the invite was sent to."""


@dataclass(frozen=True)
class Accepted:
    """The workspace joined and the role held in it."""

    workspace_id: uuid.UUID
    role: str


def _now() -> datetime:
    return datetime.now(UTC)


def create_invites(
    db: Session,
    sender: EmailSender,
    base_url: str,
    workspace: Workspace,
    inviter: User,
    inviter_role: str,
    emails: list[str],
    role: str,
) -> list[Invite]:
    """Invite each email with `role`, replacing any pending invite for the same address.

    Raises `NotAllowed` if `role` isn't below the inviter's, and `AlreadyMember` for the first
    email that already belongs to a member. Emails arrive lowercased; duplicates are merged.
    """
    if rank(role) >= rank(inviter_role):
        raise NotAllowed("You can only invite people with a role lower than yours")
    unique = list(dict.fromkeys(emails))
    existing = set(
        db.scalars(
            select(func.lower(User.email))
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.workspace_id == workspace.id, User.email.in_(unique))
        )
    )
    for email in unique:
        if email in existing:
            raise AlreadyMember(email)
    invites: list[Invite] = []
    for email in unique:
        # A new invite replaces an old pending one, so only the latest link works.
        db.execute(
            delete(Invite).where(
                Invite.workspace_id == workspace.id,
                Invite.email == email,
                Invite.accepted_at.is_(None),
            )
        )
        token = new_token()
        invite = Invite(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            email=email,
            role=role,
            token_hash=hash_token(token),
            invited_by=inviter.id,
            expires_at=_now() + INVITE_TTL,
        )
        db.add(invite)
        invites.append(invite)
        sender.send(
            EmailMessage(
                to=email,
                subject=f"{inviter.name} invited you to {workspace.name} on Sourcely",
                body=(
                    f"{inviter.name} invited you to join the workspace {workspace.name} on "
                    f"Sourcely as {'an' if role == 'admin' else 'a'} {role}.\n\n"
                    f"Accept the invite here:\n{base_url}/invites/accept?token={token}\n\n"
                    "Sign in, or create an account with this email address, first. The link "
                    "works once and expires in 7 days."
                ),
            )
        )
    db.flush()
    return invites


def list_pending(db: Session, workspace_id: uuid.UUID) -> list[Invite]:
    """Invites not yet accepted and not expired, oldest first."""
    return list(
        db.scalars(
            select(Invite)
            .where(
                Invite.workspace_id == workspace_id,
                Invite.accepted_at.is_(None),
                Invite.expires_at > _now(),
            )
            .order_by(Invite.created_at, Invite.email)
        )
    )


def revoke(db: Session, workspace_id: uuid.UUID, invite_id: uuid.UUID) -> bool:
    """Delete an invite of this workspace, so its link stops working. False if not found."""
    invite = db.get(Invite, invite_id)
    if invite is None or invite.workspace_id != workspace_id:
        return False
    db.delete(invite)
    return True


def accept(db: Session, token: str, user: User) -> Accepted:
    """Join the invite's workspace. Raises `InviteGone` or `WrongEmail`.

    If the user is already a member (for example, invited twice), their current role is kept,
    so accepting an invite can never lower someone's role.
    """
    invite = db.scalar(
        select(Invite).where(Invite.token_hash == hash_token(token)).with_for_update()
    )
    if invite is None or invite.accepted_at is not None or invite.expires_at <= _now():
        raise InviteGone
    if invite.email.lower() != user.email.lower():
        raise WrongEmail
    invite.accepted_at = _now()
    existing = get_membership(db, invite.workspace_id, user.id)
    if existing is not None:
        return Accepted(workspace_id=invite.workspace_id, role=existing.role)
    db.add(Membership(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role))
    return Accepted(workspace_id=invite.workspace_id, role=invite.role)
