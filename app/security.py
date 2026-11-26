"""
GaugeVision AI — модуль безопасности: маскирование и шифрование учётных данных URL,
защита от Path Traversal и SSRF, санитизация невалидных чисел (DEF-07, DEF-09).
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import math
import os
import secrets
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken

from . import config

_ENC_PREFIX = "enc:v1:"
_ALLOWED_VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".m4v", ".ts", ".webm"}
_FERNET_CACHE: dict[str, Fernet] = {}


def _get_fernet() -> Fernet:
    """Возвращает Fernet-ключ шифрования секретов (из GAUGEVISION_SECRET_KEY или локального файла)."""
    env_secret = os.environ.get("GAUGEVISION_SECRET_KEY") or config.SECRET_KEY
    if env_secret:
        cache_key = f"env:{env_secret[:16]}"
        if cache_key not in _FERNET_CACHE:
            digest = hashlib.sha256(env_secret.encode("utf-8")).digest()
            _FERNET_CACHE[cache_key] = Fernet(base64.urlsafe_b64encode(digest))
        return _FERNET_CACHE[cache_key]

    key_file = config.get_db_path().resolve().parent / ".gv_secret.key"
    cache_key = f"file:{key_file}"
    if cache_key in _FERNET_CACHE:
        return _FERNET_CACHE[cache_key]

    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.is_file():
        raw_key = key_file.read_bytes().strip()
    else:
        raw_key = Fernet.generate_key()
        key_file.write_bytes(raw_key)
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
    f = Fernet(raw_key)
    _FERNET_CACHE[cache_key] = f
    return f


def has_url_credentials(url: str | None) -> bool:
    if not url:
        return False
    try:
        parts = urlsplit(url)
        return bool(parts.username or parts.password)
    except ValueError:
        return "@" in url


def mask_url_credentials(url: str | None) -> str | None:
    """Маскирует логин и пароль в RTSP/HTTP URL для API, UI и журналов."""
    if not url:
        return url
    raw = str(url).strip()
    if raw.startswith(_ENC_PREFIX):
        raw = decrypt_source_url(raw) or ""
    try:
        parts = urlsplit(raw)
        if not parts.scheme or (parts.username is None and parts.password is None):
            return raw
        host = parts.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port_s = f":{parts.port}" if parts.port is not None else ""
        masked_netloc = f"***:***@{host}{port_s}"
        return urlunsplit((parts.scheme, masked_netloc, parts.path, parts.query, parts.fragment))
    except ValueError:
        return "***"


def encrypt_source_url(url: str | None) -> str | None:
    """Шифрует source_url перед записью в SQLite, если в URL присутствуют учётные данные."""
    if not url:
        return url
    if url.startswith(_ENC_PREFIX):
        return url
    if not has_url_credentials(url):
        return url
    token = _get_fernet().encrypt(url.encode("utf-8")).decode("ascii")
    return f"{_ENC_PREFIX}{token}"


def decrypt_source_url(stored: str | None) -> str | None:
    """Расшифровывает source_url из SQLite для внутреннего использования воркером захвата."""
    if not stored:
        return stored
    if not stored.startswith(_ENC_PREFIX):
        return stored
    token = stored[len(_ENC_PREFIX):].encode("ascii")
    try:
        return _get_fernet().decrypt(token).decode("utf-8")
    except InvalidToken:
        return None


def _extra_allowed_cidrs() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.environ.get("GAUGEVISION_ALLOWED_STREAM_CIDRS", config.ALLOWED_STREAM_CIDRS)
    out: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(ipaddress.ip_network(tok, strict=False))
        except ValueError:
            continue
    return out


def _ip_allowed_for_stream(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> tuple[bool, str]:
    """Проверяет допустимость целевого IP для RTSP / HTTP-MJPEG (защита от SSRF)."""
    # Всегда блокируем cloud metadata / link-local (169.254.0.0/16, fe80::/10), unspecified и multicast
    if addr.is_link_local:
        return False, f"Адрес {addr} относится к link-local/metadata и запрещён политикой безопасности (SSRF)"
    if addr.is_unspecified or addr.is_multicast:
        return False, f"Адрес {addr} (unspecified/multicast) недопустим для видеопотока"

    for net in _extra_allowed_cidrs():
        if addr in net:
            return True, "allowed_cidr"

    if addr.is_loopback:
        allow_lb = os.environ.get("GAUGEVISION_ALLOW_LOOPBACK_STREAMS", "").strip().lower() in ("1", "true", "yes")
        if allow_lb or config.ALLOW_LOOPBACK_STREAMS:
            return True, "loopback_allowed"
        return False, "Loopback-адреса (127.0.0.0/8, ::1) запрещены для сетевых потоков (установите GAUGEVISION_ALLOW_LOOPBACK_STREAMS=1 для локального стенда)"

    # Разрешаем частные промышленные сети (RFC 1918 / ULA)
    if addr.is_private:
        return True, "private_industrial_lan"

    allow_ext = os.environ.get("GAUGEVISION_ALLOW_EXTERNAL_STREAMS", "").strip().lower() in ("1", "true", "yes")
    if allow_ext or config.ALLOW_EXTERNAL_STREAMS:
        return True, "external_allowed"
    return False, f"Внешний публичный адрес {addr} заблокирован в автономном промышленном контуре (air-gapped)"


def validate_network_stream_url(cam_type: str, url: str) -> str:
    """Строгая валидация RTSP/HTTP-MJPEG URL с защитой от SSRF."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise ValueError(f"Некорректный формат URL: {exc}") from exc

    scheme = (parts.scheme or "").lower()
    if cam_type == "rtsp" and scheme not in ("rtsp", "rtsps"):
        raise ValueError("RTSP-адрес должен начинаться с rtsp:// или rtsps://")
    if cam_type == "http_mjpeg" and scheme not in ("http", "https"):
        raise ValueError("HTTP/MJPEG-адрес должен начинаться с http:// или https://")

    host = (parts.hostname or "").strip()
    if not host:
        raise ValueError("В адресе потока не указан хост")

    try:
        _ = parts.port
    except ValueError as exc:
        raise ValueError("Некорректный номер порта в адресе потока") from exc

    # Проверка IP-литерала или DNS-разрешения (без блокировки в air-gapped при .local)
    ip_objs: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    try:
        ip_objs.append(ipaddress.ip_address(host))
    except ValueError:
        low_host = host.lower()
        if low_host in ("localhost", "metadata.google.internal", "metadata"):
            ip_objs.append(ipaddress.ip_address("127.0.0.1" if low_host == "localhost" else "169.254.169.254"))
        else:
            try:
                infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
                for info in infos:
                    ip_str = info[4][0].split("%")[0]
                    try:
                        ip_objs.append(ipaddress.ip_address(ip_str))
                    except ValueError:
                        pass
            except OSError:
                # В изолированном контуре DNS может быть недоступен — разрешаем только локальные суффиксы
                if not low_host.endswith((".local", ".lan", ".internal", ".corp")):
                    raise ValueError(f"Хост «{host}» не разрешается в локальном контуре")

    for ip_obj in ip_objs:
        ok, reason = _ip_allowed_for_stream(ip_obj)
        if not ok:
            raise ValueError(reason)

    return url


def validate_video_file_path(raw_path: str, allowed_root: Path | None = None) -> str:
    """
    Строгая валидация пути видеофайла (DEF-07):
      • запрещает '..', нулевые байты и произвольные абсолютные пути вне data/videos/;
      • проверяет канонический путь через Path.resolve().is_relative_to(allowed_root);
      • ограничивает допустимые расширения видеофайлов.
    Возвращает нормализованный относительный путь внутри allowed_root.
    """
    cleaned = (raw_path or "").strip()
    if not cleaned:
        raise ValueError("Не указан путь к видеофайлу")
    if "\x00" in cleaned or ".." in Path(cleaned).parts:
        raise ValueError("Путь к видеофайлу содержит недопустимые элементы ('..' или NUL)")

    root = (allowed_root or config.get_videos_dir()).resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    p = Path(cleaned)
    if p.is_absolute():
        resolved = p.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"Абсолютный путь вне разрешённой директории видео ({root.name}/) запрещён")
    else:
        resolved = (root / p).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Выход за пределы разрешённой директории видеофайлов запрещён (Path Traversal)")

    if resolved.suffix.lower() not in _ALLOWED_VIDEO_EXTS:
        raise ValueError(
            f"Недопустимое расширение файла «{resolved.suffix or 'нет'}». "
            f"Разрешены: {', '.join(sorted(_ALLOWED_VIDEO_EXTS))}"
        )

    rel = resolved.relative_to(root)
    return str(rel).replace("\\", "/")


def sanitize_non_finite(obj: Any) -> Any:
    """Рекурсивно заменяет NaN/Infinity и несериализуемые объекты (Exception/Path/bytes) для JSON (DEF-09)."""
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj):
            return "NaN"
        if math.isinf(obj):
            return "Infinity" if obj > 0 else "-Infinity"
        return obj
    if isinstance(obj, dict):
        return {str(k): sanitize_non_finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_non_finite(v) for v in obj]
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)
