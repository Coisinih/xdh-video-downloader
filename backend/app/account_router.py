import secrets

from fastapi import APIRouter, Depends, Request, Response, status

from .account_models import AuthResponse, Credentials, CurrentUserResponse, MembershipInfo, SupportRequest, SupportResponse
from .auth import CurrentUser, authenticate_user, check_auth_rate_limit, create_session, logout_session, register_user, request_client_address, require_csrf, require_user
from .database import utcnow_iso
from .entitlements import membership_for, remaining_free_downloads, require_vip

router = APIRouter(prefix="/api/v1", tags=["account"])


def _check_auth_limits(request: Request, email: str, action: str, identity_limit: int) -> None:
    """Apply a coarse IP limit plus a stricter IP-and-account limit.

    The two-level policy prevents one mistyped account from being brute-forced,
    while avoiding a tiny shared-IP limit that would lock out unrelated users
    behind the same office, school, carrier NAT, or test proxy.
    """
    database = request.app.state.database
    client_address = request_client_address(request)
    identity = f"{client_address}\0{email.strip().casefold()[:254]}"
    check_auth_rate_limit(database, client_address, f"{action}:ip", limit=50)
    check_auth_rate_limit(database, identity, f"{action}:identity", limit=identity_limit)


def _user_response(request: Request, user: CurrentUser, csrf_token: str | None = None) -> CurrentUserResponse:
    database = request.app.state.database
    membership = membership_for(database, user.id)
    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        csrf_token=csrf_token or user.csrf_token,
        membership=MembershipInfo(**membership.__dict__),
        remaining_free_downloads=remaining_free_downloads(database, user.id),
    )


@router.post("/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: Credentials, request: Request, response: Response):
    database = request.app.state.database
    _check_auth_limits(request, payload.email, "register", identity_limit=5)
    user_id = register_user(database, payload.email, payload.password)
    csrf_token = create_session(database, user_id, response)
    row = database.fetchone("SELECT email FROM users WHERE id = ?", (user_id,))
    return _user_response(request, CurrentUser(user_id, str(row["email"]), csrf_token), csrf_token)


@router.post("/auth/login", response_model=AuthResponse)
async def login(payload: Credentials, request: Request, response: Response):
    database = request.app.state.database
    _check_auth_limits(request, payload.email, "login", identity_limit=10)
    user_id = authenticate_user(database, payload.email, payload.password)
    database.execute("DELETE FROM user_sessions WHERE user_id = ? AND expires_at <= ?", (user_id, utcnow_iso()))
    csrf_token = create_session(database, user_id, response)
    row = database.fetchone("SELECT email FROM users WHERE id = ?", (user_id,))
    return _user_response(request, CurrentUser(user_id, str(row["email"]), csrf_token), csrf_token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, _user: CurrentUser = Depends(require_csrf)):
    logout_session(request, response)


@router.get("/me", response_model=CurrentUserResponse)
async def me(request: Request, user: CurrentUser = Depends(require_user)):
    return _user_response(request, user)


@router.post("/support/tickets", response_model=SupportResponse, status_code=status.HTTP_201_CREATED)
async def create_support_ticket(payload: SupportRequest, request: Request, user: CurrentUser = Depends(require_csrf)):
    database = request.app.state.database
    require_vip(database, user.id)
    ticket_id = secrets.token_urlsafe(15)
    database.execute(
        "INSERT INTO support_tickets(id, user_id, subject, message, created_at) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, user.id, payload.subject.strip(), payload.message.strip(), utcnow_iso()),
    )
    return SupportResponse(id=ticket_id, status="open")
