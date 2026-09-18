"""Account routes: sign up, verify, sign in and out, password reset, and `/me`."""

from fastapi import APIRouter, Request, Response, status

from app.api.auth import SessionDep, clear_session_cookies, set_session_cookies
from app.api.deps import DbDep, EngineDep, SettingsDep
from app.core.errors import AppError
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    MeResponse,
    Message,
    PasswordResetConfirm,
    PasswordResetRequest,
    SignupRequest,
    UserOut,
    VerifyRequest,
    WorkspaceSummary,
)
from app.services import accounts, workspaces
from app.services.email import EmailSender

router = APIRouter(tags=["auth"])

SIGNUP_SENT = "Check your email to finish signing up"
RESET_SENT = "If that email has an account, we sent a reset link"
INVALID_LINK = "This link is invalid or has expired"


def _sender(request: Request) -> EmailSender:
    sender: EmailSender = request.app.state.email_sender
    return sender


def _user_out(user: object) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/auth/signup", response_model=Message, status_code=status.HTTP_202_ACCEPTED)
def signup(body: SignupRequest, request: Request, db: DbDep, settings: SettingsDep) -> Message:
    """Create an account and email a verification link. The reply never reveals if the email
    already had an account."""
    accounts.signup(
        db, _sender(request), settings.app_base_url, body.name, body.email, body.password
    )
    return Message(detail=SIGNUP_SENT)


@router.post("/auth/verify", response_model=AuthResponse)
def verify(
    body: VerifyRequest, response: Response, db: DbDep, settings: SettingsDep
) -> AuthResponse:
    """Confirm the email address from its link, and sign in."""
    try:
        user = accounts.verify_email(db, body.token)
    except accounts.InvalidToken as exc:
        raise AppError(status.HTTP_400_BAD_REQUEST, INVALID_LINK) from exc
    set_session_cookies(response, accounts.start_session(db, user), settings)
    return AuthResponse(user=_user_out(user))


@router.post("/auth/login", response_model=AuthResponse)
def login(
    body: LoginRequest,
    response: Response,
    db: DbDep,
    engine: EngineDep,
    settings: SettingsDep,
) -> AuthResponse:
    """Sign in with email and password. Throttled after repeated failures."""
    try:
        user = accounts.authenticate(db, body.email, body.password)
    except accounts.TooManyAttempts as exc:
        raise AppError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed sign-ins. Try again later.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except accounts.InvalidCredentials as exc:
        accounts.record_failed_login(engine, body.email)
        raise AppError(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect") from exc
    except accounts.EmailNotVerified as exc:
        raise AppError(status.HTTP_403_FORBIDDEN, "Email not verified") from exc
    set_session_cookies(response, accounts.start_session(db, user), settings)
    return AuthResponse(user=_user_out(user))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(current: SessionDep, db: DbDep, settings: SettingsDep) -> Response:
    """Sign out: end this session and clear the cookies."""
    accounts.end_session(db, current.session)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response, settings)
    return response


@router.post("/auth/password-reset", response_model=Message, status_code=status.HTTP_202_ACCEPTED)
def password_reset(
    body: PasswordResetRequest, request: Request, db: DbDep, settings: SettingsDep
) -> Message:
    """Email a reset link if the account exists. The reply is the same either way."""
    accounts.request_password_reset(db, _sender(request), settings.app_base_url, body.email)
    return Message(detail=RESET_SENT)


@router.post("/auth/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
def password_reset_confirm(body: PasswordResetConfirm, db: DbDep) -> Response:
    """Set a new password from a reset link. Every session of the account is signed out."""
    try:
        accounts.reset_password(db, body.token, body.password)
    except accounts.InvalidToken as exc:
        raise AppError(status.HTTP_400_BAD_REQUEST, INVALID_LINK) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
def me(current: SessionDep, db: DbDep) -> MeResponse:
    """The signed-in user and the workspaces they belong to, sorted by name."""
    return MeResponse(
        user=_user_out(current.user),
        workspaces=[
            WorkspaceSummary(id=workspace.id, name=workspace.name, role=role)
            for workspace, role in workspaces.memberships_of(db, current.user.id)
        ],
    )
