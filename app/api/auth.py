"""Who is calling: resolving the session cookie, the CSRF check, and setting cookies.

Task 14 adds workspace resolution (`Principal`) and Task 15 API keys on top of this.
"""

import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request, Response, status

from app.api.deps import DbDep, SettingsDep
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import AuthSession, User
from app.services import accounts
from app.services.accounts import NewSession

SESSION_COOKIE = "sourcely_session"
CSRF_COOKIE = "sourcely_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class CurrentSession:
    """The signed-in user and their session row, for routes that need a browser session."""

    user: User
    session: AuthSession


def get_current_session(request: Request, db: DbDep, settings: SettingsDep) -> CurrentSession:
    """Resolve the session cookie, and check CSRF on anything that can change data.

    401 without a valid session; 403 when a write lacks the matching `X-CSRF-Token`.
    """
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
