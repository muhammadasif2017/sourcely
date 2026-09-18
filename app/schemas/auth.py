"""Request and response models for accounts and sessions."""

import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field, StringConstraints

from app.core.security import is_common_password

MIN_PASSWORD_CHARS = 12
MAX_PASSWORD_CHARS = 128


def _not_common(password: str) -> str:
    if is_common_password(password):
        raise ValueError("Choose a less common password")
    return password


# Rules for a password being *set*. Sign-in accepts any string, so a rule change never locks
# out an existing account.
NewPassword = Annotated[
    str,
    StringConstraints(min_length=MIN_PASSWORD_CHARS, max_length=MAX_PASSWORD_CHARS),
    AfterValidator(_not_common),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Token = Annotated[str, StringConstraints(min_length=1, max_length=256)]


def _lower(email: str) -> str:
    return email.lower()


Email = Annotated[EmailStr, Field(max_length=254), AfterValidator(_lower)]


class SignupRequest(BaseModel):
    """A new account."""

    name: Name
    email: Email
    password: NewPassword


class VerifyRequest(BaseModel):
    """The token from a verification email."""

    token: Token


class LoginRequest(BaseModel):
    """Sign-in credentials."""

    email: Email
    password: str = Field(max_length=MAX_PASSWORD_CHARS)


class PasswordResetRequest(BaseModel):
    """Ask for a password reset link."""

    email: Email


class PasswordResetConfirm(BaseModel):
    """The token from a reset email and the new password."""

    token: Token
    password: NewPassword


class Message(BaseModel):
    """A plain confirmation message."""

    detail: str


class UserOut(BaseModel):
    """The public view of a user."""

    id: uuid.UUID
    name: str
    email: str


class AuthResponse(BaseModel):
    """The signed-in user, returned by sign-in and verification."""

    user: UserOut


class WorkspaceSummary(BaseModel):
    """A workspace the user belongs to, with their role in it."""

    id: uuid.UUID
    name: str
    role: str


class MeResponse(BaseModel):
    """The signed-in user and their workspaces."""

    user: UserOut
    workspaces: list[WorkspaceSummary]
