"""Accounts: sign-up, email verification, sign-in with throttling, sessions, password reset.

Everything here works on a SQLAlchemy `Session` owned by the caller (one per request), except
recording failed sign-ins, which uses its own short transaction: the request's transaction
rolls back when sign-in fails, and the failure must still be counted.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from app.core.security import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)
from app.db.models import AuthSession, EmailToken, LoginAttempt, User
from app.services.email import EmailMessage, EmailSender

VERIFY_TOKEN_TTL = timedelta(hours=24)
RESET_TOKEN_TTL = timedelta(hours=1)
MAX_FAILED_LOGINS = 5
FAILED_LOGIN_WINDOW = timedelta(minutes=15)
# `last_seen_at` is written at most this often, so reads don't each cost a write.
LAST_SEEN_RESOLUTION = timedelta(minutes=5)


class AccountError(Exception):
    """Base class for account failures that routes turn into HTTP errors."""


class InvalidToken(AccountError):
    """An email link that doesn't exist, was already used, or has expired."""


class InvalidCredentials(AccountError):
    """Wrong email or password. Deliberately doesn't say which."""


class EmailNotVerified(AccountError):
    """The password was right, but the email address isn't verified yet."""


class TooManyAttempts(AccountError):
    """Sign-in is throttled for this email. `retry_after` is in seconds."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"retry after {retry_after}s")
        self.retry_after = retry_after


@dataclass(frozen=True)
class NewSession:
    """Values for the two cookies set at sign-in. Only a hash of `token` is stored."""

    token: str
    csrf_token: str


def _now() -> datetime:
    return datetime.now(UTC)


def _issue_email_token(db: Session, user: User, purpose: str, ttl: timedelta) -> str:
    token = new_token()
    db.add(
        EmailToken(
            token_hash=hash_token(token),
            user_id=user.id,
            purpose=purpose,
            expires_at=_now() + ttl,
        )
    )
    return token


def _consume_email_token(db: Session, token: str, purpose: str) -> User:
    """Mark a valid token used and return its user, or raise `InvalidToken`."""
    row = db.get(EmailToken, hash_token(token), with_for_update=True)
    if row is None or row.purpose != purpose or row.used_at is not None or row.expires_at <= _now():
        raise InvalidToken
    row.used_at = _now()
    user = db.get(User, row.user_id)
    if user is None:
        raise InvalidToken
    return user


def find_user_by_email(db: Session, email: str) -> User | None:
    """The user with this email, compared case-insensitively (the column is citext)."""
    return db.scalar(select(User).where(User.email == email))


def signup(
    db: Session, sender: EmailSender, base_url: str, name: str, email: str, password: str
) -> None:
    """Create an unverified user and email a verification link.

    For an email that already has an account, nothing is created and the owner is told by
    email instead. The caller sees the same result either way, so sign-up can't be used to
    discover who has an account. The password is hashed in both cases to keep timing similar.
    """
    password_hash = hash_password(password)
    existing = find_user_by_email(db, email)
    if existing is not None:
        sender.send(
            EmailMessage(
                to=existing.email,
                subject="Sign-up attempt for your Sourcely account",
                body=(
                    f"Hi {existing.name},\n\n"
                    "Someone tried to create a Sourcely account with this email, but you "
                    "already have an account. If it was you, sign in instead, or reset your "
                    f"password at {base_url}/reset-password.\n\n"
                    "If it wasn't you, you can ignore this email."
                ),
            )
        )
        return
    user = User(id=uuid.uuid4(), email=email, name=name, password_hash=password_hash)
    db.add(user)
    db.flush()
    token = _issue_email_token(db, user, "verify", VERIFY_TOKEN_TTL)
    sender.send(
        EmailMessage(
            to=user.email,
            subject="Verify your Sourcely email",
            body=(
                f"Hi {name},\n\nConfirm your email address to finish signing up:\n"
                f"{base_url}/verify-email?token={token}\n\n"
                "The link works once and expires in 24 hours. If you didn't sign up, "
                "ignore this email."
            ),
        )
    )


def verify_email(db: Session, token: str) -> User:
    """Mark the user's email verified. Raises `InvalidToken`."""
    user = _consume_email_token(db, token, "verify")
    if user.email_verified_at is None:
        user.email_verified_at = _now()
    return user


def check_throttle(db: Session, email: str) -> None:
    """Raise `TooManyAttempts` if this email had too many recent failed sign-ins."""
    window_start = _now() - FAILED_LOGIN_WINDOW
    recent = db.execute(
        select(func.count(), func.min(LoginAttempt.attempted_at)).where(
            LoginAttempt.email == email, LoginAttempt.attempted_at > window_start
        )
    ).one()
    count, oldest = recent
    if count >= MAX_FAILED_LOGINS and oldest is not None:
        # Allowed again once the oldest failure in the window falls out of it.
        wait = (oldest + FAILED_LOGIN_WINDOW - _now()).total_seconds()
        raise TooManyAttempts(max(1, math.ceil(wait)))


def record_failed_login(engine: Engine, email: str) -> None:
    """Count a failed sign-in in its own transaction, which survives the request's rollback."""
    with Session(engine) as db, db.begin():
        db.add(LoginAttempt(email=email))


def authenticate(db: Session, email: str, password: str) -> User:
    """The user for these credentials.

    Raises `TooManyAttempts` (checked first, so even a right password is refused while
    throttled), `InvalidCredentials`, or `EmailNotVerified` (only after a right password).
    """
    check_throttle(db, email)
    user = find_user_by_email(db, email)
    # Always run one Argon2 verification, so unknown emails take as long as wrong passwords.
    ok = verify_password(user.password_hash if user else DUMMY_PASSWORD_HASH, password)
    if user is None or not ok:
        raise InvalidCredentials
    if user.email_verified_at is None:
        raise EmailNotVerified
    db.execute(delete(LoginAttempt).where(LoginAttempt.email == email))
    return user


def start_session(db: Session, user: User) -> NewSession:
    """Create a session for `user` and return the cookie values."""
    session = NewSession(token=new_token(), csrf_token=new_token())
    db.add(
        AuthSession(
            token_hash=hash_token(session.token), user_id=user.id, csrf_token=session.csrf_token
        )
    )
    return session


def resolve_session(db: Session, token: str, idle_days: int) -> tuple[User, AuthSession] | None:
    """The user and session behind a cookie value, or None if unknown or idle too long."""
    session = db.get(AuthSession, hash_token(token))
    if session is None:
        return None
    now = _now()
    if session.last_seen_at < now - timedelta(days=idle_days):
        db.delete(session)
        return None
    if session.last_seen_at < now - LAST_SEEN_RESOLUTION:
        session.last_seen_at = now
    user = db.get(User, session.user_id)
    return (user, session) if user is not None else None


def end_session(db: Session, session: AuthSession) -> None:
    """Sign out: delete the session row."""
    db.delete(session)


def request_password_reset(db: Session, sender: EmailSender, base_url: str, email: str) -> None:
    """Email a reset link if the account exists. The caller's response never says which."""
    user = find_user_by_email(db, email)
    if user is None:
        return
    token = _issue_email_token(db, user, "reset", RESET_TOKEN_TTL)
    sender.send(
        EmailMessage(
            to=user.email,
            subject="Reset your Sourcely password",
            body=(
                f"Hi {user.name},\n\nChoose a new password here:\n"
                f"{base_url}/reset-password?token={token}\n\n"
                "The link works once and expires in 1 hour. If you didn't ask for this, "
                "ignore this email: your password stays the same."
            ),
        )
    )


def reset_password(db: Session, token: str, new_password: str) -> None:
    """Set a new password and sign out every session of that user. Raises `InvalidToken`."""
    user = _consume_email_token(db, token, "reset")
    user.password_hash = hash_password(new_password)
    # Following a link sent to the address proves the user controls it.
    if user.email_verified_at is None:
        user.email_verified_at = _now()
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
