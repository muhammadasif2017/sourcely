"""Who is calling: session cookies and CSRF, API keys, and the per-request `Principal`.

A `Principal` comes from either a browser session (plus `X-Workspace-ID`) or an API key
(`Authorization: Bearer sk_live_...`), never both.
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import DbDep, SettingsDep
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import AuthSession, User
from app.services import accounts, api_keys, workspaces
from app.services.accounts import NewSession
from app.services.workspaces import Action, allowed

SESSION_COOKIE = "sourcely_session"
CSRF_COOKIE = "sourcely_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
KEY_NOT_ALLOWED = "This needs a signed-in user; API keys can't be used here"


def _bearer_token(request: Request) -> str | None:
    """The token of an `Authorization: Bearer ...` header, or None if there's no such header."""
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else None


@dataclass(frozen=True)
class CurrentSession:
    """The signed-in user and their session row, for routes that need a browser session."""

    user: User
    session: AuthSession


def get_current_session(request: Request, db: DbDep, settings: SettingsDep) -> CurrentSession:
    """Resolve the session cookie, and check CSRF on anything that can change data.

    401 without a valid session; 403 when a write lacks the matching `X-CSRF-Token`, and 403 for
    an API key, which can't act as a person (`/me`, managing workspaces, members or keys).
    """
    if _bearer_token(request) is not None:
        raise AppError(status.HTTP_403_FORBIDDEN, KEY_NOT_ALLOWED)
    token = request.cookies.get(SESSION_COOKIE)
    resolved = accounts.resolve_session(db, token, settings.session_idle_days) if token else None
    if resolved is None:
        raise AppError(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    user, session = resolved
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        # compare_digest takes the same time however many characters match.
        if not secrets.compare_digest(sent.encode(), session.csrf_token.encode()):
            raise AppError(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token")
    return CurrentSession(user=user, session=session)


SessionDep = Annotated[CurrentSession, Depends(get_current_session)]


def set_session_cookies(response: Response, new: NewSession, settings: Settings) -> None:
    """The session cookie (hidden from JavaScript) and the CSRF cookie (readable by it)."""
    max_age = int(timedelta(days=settings.session_idle_days).total_seconds())
    for name, value, httponly in (
        (SESSION_COOKIE, new.token, True),
        # The web app reads this cookie and sends it back in X-CSRF-Token. Another site can't
        # read it, so it can't forge that header.
        (CSRF_COOKIE, new.csrf_token, False),
    ):
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            path="/",
            secure=settings.cookie_secure,
            httponly=httponly,
            samesite="lax",
        )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    """Remove both cookies from the browser."""
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="lax")


WORKSPACE_HEADER = "X-Workspace-ID"
WORKSPACE_NOT_FOUND = "Workspace not found"


@dataclass(frozen=True)
class Principal:
    """Who is calling, in which workspace, with which role. One per request.

    Exactly one of `user_id` (a browser session) and `api_key_id` (Task 15) is set.
    """

    user_id: uuid.UUID | None
    api_key_id: uuid.UUID | None
    workspace_id: uuid.UUID
    role: str

    def can(self, action: Action) -> bool:
        """True if this principal's role allows `action`."""
        return allowed(self.role, action)


def require(principal: Principal, action: Action) -> None:
    """403 unless the principal's role allows `action` in its workspace."""
    if not principal.can(action):
        raise AppError(status.HTTP_403_FORBIDDEN, "Your role in this workspace doesn't allow this")


def _parse_workspace_id(value: str) -> uuid.UUID:
    """A workspace id from a header or path. Malformed ids are 404, like unknown ones."""
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise AppError(status.HTTP_404_NOT_FOUND, WORKSPACE_NOT_FOUND) from exc


def _membership_principal(db: Session, workspace_id: uuid.UUID, user: User) -> Principal:
    membership = workspaces.get_membership(db, workspace_id, user.id)
    if membership is None:
        # 404, not 403: a non-member mustn't learn that the workspace exists.
        raise AppError(status.HTTP_404_NOT_FOUND, WORKSPACE_NOT_FOUND)
    return Principal(
        user_id=user.id, api_key_id=None, workspace_id=workspace_id, role=membership.role
    )


def _key_principal(request: Request, db: Session, token: str) -> Principal:
    """The principal for an API key: its own workspace, with the editor role."""
    if request.cookies.get(SESSION_COOKIE):
        raise AppError(
            status.HTTP_400_BAD_REQUEST, "Send either a session cookie or an API key, not both"
        )
    key = api_keys.resolve_key(db, token)
    if key is None:
        raise AppError(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key")
    # A key belongs to one workspace, so the header is optional; if sent, it must agree.
    header = request.headers.get(WORKSPACE_HEADER)
    if header and header.strip().lower() != str(key.workspace_id):
        raise AppError(
            status.HTTP_400_BAD_REQUEST, f"{WORKSPACE_HEADER} doesn't match the API key's workspace"
        )
    return Principal(user_id=None, api_key_id=key.id, workspace_id=key.workspace_id, role="editor")


def get_principal(request: Request, db: DbDep, settings: SettingsDep) -> Principal:
    """The caller of a workspace data request: an API key, or a session plus `X-Workspace-ID`.

    401 without a valid credential, 400 for a cookie and a key together or for a session
    request without the header, 404 for a workspace the user isn't in.
    """
    token = _bearer_token(request)
    if token is not None:
        return _key_principal(request, db, token)
    current = get_current_session(request, db, settings)
    header = request.headers.get(WORKSPACE_HEADER)
    if not header:
        raise AppError(status.HTTP_400_BAD_REQUEST, f"{WORKSPACE_HEADER} header required")
    return _membership_principal(db, _parse_workspace_id(header), current.user)


def get_workspace_member(workspace_id: str, current: SessionDep, db: DbDep) -> Principal:
    """The caller of a workspace management route, which names the workspace in its path."""
    return _membership_principal(db, _parse_workspace_id(workspace_id), current.user)


PrincipalDep = Annotated[Principal, Depends(get_principal)]
MemberDep = Annotated[Principal, Depends(get_workspace_member)]
