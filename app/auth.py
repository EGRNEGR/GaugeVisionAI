"""
GaugeVision AI — локальная аутентификация и ролевая модель доступа RBAC (DEF-07).

Реализует автономную (air-gapped) модель безопасности без внешних IdP:
  • 3 роли: `operator` (просмотр, квитирование) < `engineer` (настройка камер,
    калибровка, ТЗ, QR, прогоны) < `admin` (удаление, симуляция отказов,
    сканирование подсети, управление пользователями и аудит-лог);
  • PBKDF2-HMAC-SHA256 с уникальной солью для хранения паролей в SQLite;
  • сессии через HttpOnly/Secure/SameSite=Strict cookie (`gv_session`) и/или
    заголовок `Authorization: Bearer <token>` (в БД хранится только SHA-256 хэш токена);
  • проверка `Origin` для WebSocket-подключений и журнал аудита действий пользователей.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import hmac
import logging
import os
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket

from . import config, db

logger = logging.getLogger("gaugevision.auth")

SESSION_COOKIE_NAME = "gv_session"
ROLE_LEVEL: dict[str, int] = {"operator": 1, "engineer": 2, "admin": 3}
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "operator": ["read_telemetry", "ack_alarms", "view_architecture", "view_dispatch"],
    "engineer": [
        "read_telemetry", "ack_alarms", "view_architecture", "view_dispatch",
        "manage_cameras", "calibrate", "phone_session", "generate_specs", "demo_control", "flush_sf",
    ],
    "admin": [
        "read_telemetry", "ack_alarms", "view_architecture", "view_dispatch",
        "manage_cameras", "calibrate", "phone_session", "generate_specs", "demo_control", "flush_sf",
        "delete_cameras", "fault_injection", "network_discover", "manage_users", "view_audit",
    ],
}


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt_b = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_b, 120_000)
    return f"pbkdf2_sha256$120000${salt_b.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters_s, salt_hex, hash_hex = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters_s))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_auth_required() -> bool:
    env = os.environ.get("GAUGEVISION_AUTH_REQUIRED")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return config.AUTH_REQUIRED


def is_fault_injection_allowed() -> bool:
    env = os.environ.get("GAUGEVISION_ALLOW_FAULT_INJECTION")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return config.ALLOW_FAULT_INJECTION or config.is_demo_mode()


def initial_credentials_path() -> Path:
    """Файл одноразовых паролей, сгенерированных при первом запуске вне деморежима."""
    return config.get_db_path().resolve().parent / "initial_credentials.txt"


def _is_known_default(password: str) -> bool:
    return password in config.KNOWN_DEFAULT_PASSWORDS


async def bootstrap_default_users() -> list[str]:
    """
    Идемпотентно создаёт локальные учётные записи (operator / engineer / admin) при старте.

    В деморежиме используются пароли из окружения (по умолчанию — стендовые из `.env.example`).
    Вне деморежима известные стендовые пароли и пустые значения не принимаются: для каждой
    новой учётной записи генерируется случайный пароль, который однократно записывается в
    `initial_credentials.txt` рядом с БД (права 0600). Возвращает имена созданных записей.
    """
    accounts = (
        (config.ADMIN_USERNAME, config.ADMIN_PASSWORD, "admin"),
        (config.ENGINEER_USERNAME, config.ENGINEER_PASSWORD, "engineer"),
        (config.OPERATOR_USERNAME, config.OPERATOR_PASSWORD, "operator"),
    )
    production = not config.is_demo_mode()
    created: list[str] = []
    generated: list[tuple[str, str, str]] = []
    for uname, pwd, role in accounts:
        if not uname:
            continue
        if await db.get_user(uname) is not None:
            continue
        if production and (not pwd or _is_known_default(pwd)):
            pwd = secrets.token_urlsafe(14)
            generated.append((uname, role, pwd))
        if not pwd:
            continue
        await db.upsert_user(uname, hash_password(pwd), role)
        created.append(uname)
    if generated:
        path = initial_credentials_path()
        lines = [
            "# GaugeVision AI — одноразовые пароли первичного запуска (вне деморежима).",
            "# Стендовые пароли по умолчанию в промышленном режиме не принимаются.",
            "# Перенесите пароли в защищённое хранилище и удалите этот файл.",
        ] + [f"{u}\t{r}\t{p}" for u, r, p in generated]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
        logger.warning("Созданы учётные записи со случайными паролями: %s (см. %s)",
                       ", ".join(u for u, _, _ in generated), path)
    return created


# -- защита от подбора пароля ----------------------------------------------------
_login_failures: dict[str, deque[float]] = {}


def _failure_key(username: str, ip: str | None) -> str:
    return f"{username.strip().lower()}|{ip or '-'}"


def login_retry_after(username: str, ip: str | None) -> int | None:
    """Секунды до разблокировки, если для пары «пользователь + адрес» превышен лимит неудачных входов."""
    q = _login_failures.get(_failure_key(username, ip))
    if not q:
        return None
    now = time.monotonic()
    window = float(config.LOGIN_LOCKOUT_WINDOW_SECONDS)
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= config.LOGIN_MAX_FAILURES:
        return max(1, int(window - (now - q[0])) + 1)
    return None


def register_login_failure(username: str, ip: str | None) -> None:
    key = _failure_key(username, ip)
    q = _login_failures.setdefault(key, deque(maxlen=max(1, config.LOGIN_MAX_FAILURES) * 2))
    q.append(time.monotonic())
    if len(_login_failures) > 10_000:  # ограничение памяти при переборе имён
        for k in list(_login_failures)[:5_000]:
            _login_failures.pop(k, None)


def reset_login_failures(username: str, ip: str | None) -> None:
    _login_failures.pop(_failure_key(username, ip), None)


async def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    user = await db.get_user(username.strip())
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    if not config.is_demo_mode() and _is_known_default(password):
        # БД перенесена со стенда: стендовый пароль в промышленном режиме не действует
        logger.warning("Вход %s отклонён: стендовый пароль по умолчанию вне деморежима", user["username"])
        return None
    token = secrets.token_urlsafe(32)
    exp = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=max(300, config.SESSION_TTL_SECONDS))).isoformat(
        timespec="seconds"
    )
    await db.create_session(hash_token(token), user["username"], user["role"], exp)
    return {
        "token": token,
        "username": user["username"],
        "role": user["role"],
        "permissions": ROLE_PERMISSIONS.get(user["role"], []),
        "expires_at": exp,
    }


def extract_token_from_request(request: Request) -> str | None:
    auth_hdr = request.headers.get("authorization") or ""
    if auth_hdr.lower().startswith("bearer "):
        tok = auth_hdr[7:].strip()
        if tok:
            return tok
    api_key = (request.headers.get("x-api-key") or "").strip()
    if api_key:
        return api_key
    cookie_tok = (request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
    if cookie_tok:
        return cookie_tok
    return None


async def resolve_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    return await db.get_session(hash_token(token))


async def get_optional_user(request: Request) -> dict[str, Any] | None:
    tok = extract_token_from_request(request)
    return await resolve_session(tok)


def require_role(min_role: str):
    """FastAPI-зависимость проверки аутентификации и минимальной роли RBAC."""
    min_lv = ROLE_LEVEL[min_role]

    async def _dep(request: Request) -> dict[str, Any]:
        if not is_auth_required():
            return {"username": "local-bypass", "role": "admin", "auth_bypassed": True}
        sess = await get_optional_user(request)
        if sess is None:
            raise HTTPException(
                status_code=401,
                detail="Требуется аутентификация (выполните вход через /api/auth/login или передайте Bearer-токен)",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_lv = ROLE_LEVEL.get(str(sess.get("role")), 0)
        if user_lv < min_lv:
            ip = request.client.host if request.client else None
            await db.log_audit(
                username=sess.get("username"),
                role=sess.get("role"),
                action=f"FORBIDDEN {request.method} {request.url.path}",
                target=f"required={min_role}",
                status_code=403,
                ip=ip,
            )
            raise HTTPException(
                status_code=403,
                detail=f"Недостаточно прав: требуется роль «{min_role}», текущая роль — «{sess.get('role')}»",
            )
        return sess

    return _dep


def verify_ws_origin(ws: WebSocket) -> bool:
    """Проверяет заголовок Origin для защиты WebSocket от Cross-Site WebSocket Hijacking."""
    origin = (ws.headers.get("origin") or "").strip()
    if not origin:
        return True  # нативные клиенты / Python websockets без Origin
    host = (ws.headers.get("host") or "").strip().lower()
    try:
        parts = urlsplit(origin)
        orig_host = (parts.netloc or "").lower()
        orig_hostname = (parts.hostname or "").lower()
    except ValueError:
        return False
    if orig_host == host:
        return True
    if orig_hostname in ("localhost", "127.0.0.1", "::1") and host.split(":")[0] in ("localhost", "127.0.0.1", "testserver"):
        return True
    allowed_raw = os.environ.get("GAUGEVISION_CORS_ORIGINS", config.CORS_ORIGINS)
    allowed = {o.strip().lower() for o in allowed_raw.split(",") if o.strip()}
    return origin.lower() in allowed


async def authorize_ws(ws: WebSocket, min_role: str = "operator") -> dict[str, Any] | None:
    """Проверяет Origin и сессию/токен для WebSocket-соединения."""
    if not verify_ws_origin(ws):
        return None
    if not is_auth_required():
        return {"username": "local-bypass", "role": "admin"}
    tok = (
        (ws.query_params.get("token") or "").strip()
        or (ws.cookies.get(SESSION_COOKIE_NAME) or "").strip()
    )
    if not tok:
        auth_hdr = ws.headers.get("authorization") or ""
        if auth_hdr.lower().startswith("bearer "):
            tok = auth_hdr[7:].strip()
    sess = await resolve_session(tok)
    if sess is None:
        return None
    if ROLE_LEVEL.get(str(sess.get("role")), 0) < ROLE_LEVEL[min_role]:
        return None
    return sess
