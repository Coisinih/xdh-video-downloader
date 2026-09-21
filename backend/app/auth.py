import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, Header, HTTPException, Request, Response

from .config import settings
from .database import Database, utcnow_iso

SESSION_COOKIE = "vidnest_session"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_dummy_password_hash = password_hasher.hash("VidNest-dummy-password-2026")


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    csrf_token: str


def normalize_email(email: str) -> str:
    value = email.strip().casefold()
    if len(value) > 254 or not EMAIL_PATTERN.fullmatch(value):
        raise HTTPException(422, "请输入有效的邮箱地址")
    return value


def validate_password(password: str) -> None:
    if not 10 <= len(password) <= 128:
        raise HTTPException(422, "密码长度必须为 10 至 128 个字符")
    categories = sum((any(char.islower() for char in password), any(char.isupper() for char in password), any(char.isdigit() for char in password), any(not char.isalnum() for char in password)))
    if categories < 3:
        raise HTTPException(422, "密码需包含大小写字母、数字、符号中的至少三类")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _database(request: Request) -> Database:
    return request.app.state.database


def check_auth_rate_limit(database: Database, client_address: str, action: str, limit: int = 10, window_seconds: int = 900) -> None:
    client_hash = hashlib.sha256(f"vidnest-auth:{client_address}".encode("utf-8")).hexdigest()
    window_start = int(time.time()) // window_seconds * window_seconds
    with database.transaction(immediate=True) as connection:
        row = connection.execute(
            "SELECT count FROM auth_rate_limits WHERE client_hash = ? AND action = ? AND window_start = ?",
            (client_hash, action, window_start),
        ).fetchone()
        count = int(row["count"] if row else 0)
        if count >= limit:
            raise HTTPException(429, "尝试次数过多，请 15 分钟后再试")
        connection.execute(
            """INSERT INTO auth_rate_limits(client_hash, action, window_start, count) VALUES (?, ?, ?, 1)
               ON CONFLICT(client_hash, action, window_start) DO UPDATE SET count = count + 1""",
            (client_hash, action, window_start),
        )


def request_client_address(request: Request) -> str:
    # Nginx overwrites X-Real-IP in the production image. The backend port must
    # not be exposed directly when trusting this header.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def create_session(database: Database, user_id: str, response: Response) -> str:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    now = datetime.now(UTC)
    database.execute(
        "INSERT INTO user_sessions(token_hash, user_id, csrf_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (_token_hash(token), user_id, csrf_token, (now + timedelta(seconds=settings.session_ttl_seconds)).isoformat(), now.isoformat()),
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return csrf_token


def register_user(database: Database, email: str, password: str) -> str:
    normalized = normalize_email(email)
    validate_password(password)
    user_id = secrets.token_urlsafe(18)
    try:
        database.execute(
            "INSERT INTO users(id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (user_id, normalized, password_hasher.hash(password), utcnow_iso()),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "该邮箱已经注册") from exc
    return user_id


def authenticate_user(database: Database, email: str, password: str) -> str:
    normalized = normalize_email(email)
    row = database.fetchone("SELECT id, password_hash FROM users WHERE email = ?", (normalized,))
    stored_hash = row["password_hash"] if row else _dummy_password_hash
    try:
        valid = password_hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        valid = False
    if not row or not valid:
        raise HTTPException(401, "邮箱或密码不正确")
    if password_hasher.check_needs_rehash(stored_hash):
        database.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hasher.hash(password), row["id"]))
    return str(row["id"])


def get_optional_user(request: Request) -> CurrentUser | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = _database(request).fetchone(
        """SELECT users.id, users.email, user_sessions.csrf_token, user_sessions.expires_at
           FROM user_sessions JOIN users ON users.id = user_sessions.user_id
           WHERE user_sessions.token_hash = ?""",
        (_token_hash(token),),
    )
    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
        _database(request).execute("DELETE FROM user_sessions WHERE token_hash = ?", (_token_hash(token),))
        return None
    return CurrentUser(str(row["id"]), str(row["email"]), str(row["csrf_token"]))


def require_user(user: CurrentUser | None = Depends(get_optional_user)) -> CurrentUser:
    if not user:
        raise HTTPException(401, "请先登录后再使用此功能")
    return user


def require_csrf(
    user: CurrentUser = Depends(require_user),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> CurrentUser:
    if not csrf_token or not hmac.compare_digest(user.csrf_token, csrf_token):
        raise HTTPException(403, "安全校验失败，请刷新页面后重试")
    return user


def logout_session(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _database(request).execute("DELETE FROM user_sessions WHERE token_hash = ?", (_token_hash(token),))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=settings.session_cookie_secure, samesite="lax")
