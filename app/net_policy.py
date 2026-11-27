"""
Сетевая политика развёртывания (закрытие замечаний OBS-SHARED-01..05 аудита безопасности).

- OBS-SHARED-01: веб-сервер на всех интерфейсах (`0.0.0.0`) нужен смартфону-камере в локальной
  сети, поэтому значение по умолчанию сохранено; вне демопрофиля это выводится предупреждением,
  а в строгом режиме (`GAUGEVISION_STRICT_NETWORK=1`) запуск без явного `GAUGEVISION_HOST` запрещён.
- OBS-SHARED-02: MQTT без TLS допускается только к брокеру на loopback; к внешнему брокеру — только
  TLS с проверкой сертификата (`GAUGEVISION_MQTT_CA_FILE` — локальный корневой сертификат) или явное
  разрешение `GAUGEVISION_MQTT_ALLOW_PLAINTEXT=1`.
- OBS-SHARED-03: Modbus TCP вне loopback поднимается только со списком разрешённых адресов клиентов
  `GAUGEVISION_MODBUS_ALLOWED_CLIENTS` (IP или CIDR через запятую); соединения с других адресов
  закрываются без ответа.
- OBS-SHARED-04: адрес LLM проходит фильтр: только http/https, без link-local и адресов метаданных
  облака; публичные адреса — только с `GAUGEVISION_LLM_ALLOW_PUBLIC=1` (облачный API не обязателен).
- OBS-SHARED-05: ссылка на внешний симулятор — только в демопрофиле; при заданном
  `GAUGEVISION_LAN_IP` адрес хоста не определяется пробным UDP-сокетом к 8.8.8.8.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
from urllib.parse import urlsplit

from . import config

log = logging.getLogger("gaugevision.net")

_WILDCARD = {"0.0.0.0", "::", ""}


def _env_on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def strict_mode() -> bool:
    return _env_on("GAUGEVISION_STRICT_NETWORK")


def _resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0].split("%")[0]))
        except ValueError:
            continue
    return out


def is_loopback_host(host: str) -> bool:
    if (host or "").strip().lower() == "localhost":
        return True
    addrs = _resolve(host)
    return bool(addrs) and all(a.is_loopback for a in addrs)


# -- MQTT (OBS-SHARED-02) ------------------------------------------------------
def mqtt_transport_error() -> str | None:
    """Причина запрета соединения с брокером или None, если соединение допустимо."""
    if config.MQTT_TLS or is_loopback_host(config.MQTT_HOST):
        return None
    if _env_on("GAUGEVISION_MQTT_ALLOW_PLAINTEXT"):
        return None
    return (f"MQTT без TLS к брокеру вне loopback ({config.MQTT_HOST}) запрещён: включите "
            "GAUGEVISION_MQTT_TLS=1 (при собственном УЦ — GAUGEVISION_MQTT_CA_FILE) "
            "или явно разрешите GAUGEVISION_MQTT_ALLOW_PLAINTEXT=1")


def mqtt_ssl_context():
    """Контекст TLS с проверкой сертификата и имени брокера; локальный корневой сертификат — опционально."""
    import ssl

    ca_file = os.environ.get("GAUGEVISION_MQTT_CA_FILE", "").strip()
    return ssl.create_default_context(cafile=ca_file or None)


# -- Modbus TCP (OBS-SHARED-03) ------------------------------------------------
def modbus_allowed_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    nets = []
    for part in os.environ.get("GAUGEVISION_MODBUS_ALLOWED_CLIENTS", "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            log.warning("GAUGEVISION_MODBUS_ALLOWED_CLIENTS: пропущен некорректный адрес %r", part)
    return nets


def modbus_bind_error() -> str | None:
    if is_loopback_host(config.MODBUS_HOST) or modbus_allowed_networks():
        return None
    return (f"Modbus TCP на {config.MODBUS_HOST} (вне loopback) без списка разрешённых клиентов "
            "запрещён: задайте GAUGEVISION_MODBUS_ALLOWED_CLIENTS (IP SCADA-сервера или CIDR)")


def modbus_client_allowed(peer_ip: str | None) -> bool:
    nets = modbus_allowed_networks()
    if not peer_ip:
        return not nets
    try:
        addr = ipaddress.ip_address(peer_ip.split("%")[0])
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    if not nets:
        return is_loopback_host(config.MODBUS_HOST)
    return any(addr in n for n in nets)


# -- LLM (OBS-SHARED-04) -------------------------------------------------------
_METADATA = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}


def llm_url_error(url: str) -> str | None:
    """Причина отказа в адресе LLM-сервера или None, если адрес допустим."""
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "адрес LLM должен быть http(s)://хост[:порт]/…"
    if parts.username or parts.password:
        return "учётные данные в адресе LLM запрещены — используйте GAUGEVISION_LLM_API_KEY"
    addrs = _resolve(parts.hostname)
    if not addrs:
        return f"имя {parts.hostname} не разрешается"
    for a in addrs:
        if a in _METADATA or a.is_link_local or a.is_multicast or a.is_unspecified or a.is_reserved:
            return f"адрес {a} недопустим для LLM (link-local, метаданные облака или служебный)"
        if a.is_global and not _env_on("GAUGEVISION_LLM_ALLOW_PUBLIC"):
            return (f"публичный адрес {a}: облачный LLM требует явного GAUGEVISION_LLM_ALLOW_PUBLIC=1 "
                    "(по умолчанию — только локальный сервер в контуре)")
    return None


# -- Веб-сервер (OBS-SHARED-01) и сводка ---------------------------------------
def posture(bind_host: str) -> list[dict[str, str]]:
    """Сводка сетевых рисков текущей конфигурации: severity block — запуск в строгом режиме запрещён."""
    out: list[dict[str, str]] = []
    if bind_host.strip() in _WILDCARD and not config.is_demo_mode():
        out.append({"id": "OBS-SHARED-01", "severity": "block" if strict_mode() else "warning",
                    "text": "веб-сервер слушает все интерфейсы; задайте GAUGEVISION_HOST — адрес "
                            "технологического VLAN (смартфон-камера должна быть в той же сети)"})
    if config.MQTT_ENABLED and (err := mqtt_transport_error()):
        out.append({"id": "OBS-SHARED-02", "severity": "block", "text": err})
    if config.MODBUS_ENABLED and (err := modbus_bind_error()):
        out.append({"id": "OBS-SHARED-03", "severity": "block", "text": err})
    if config.LLM_BASE_URL and (err := llm_url_error(config.LLM_BASE_URL)):
        out.append({"id": "OBS-SHARED-04", "severity": "warning", "text": f"LLM отключён: {err}"})
    return out


def startup_check(bind_host: str) -> list[dict[str, str]]:
    """Журналирует сводку при запуске; в строгом режиме блокирующие пункты останавливают запуск."""
    items = posture(bind_host)
    for it in items:
        log.warning("[%s] %s", it["id"], it["text"])
    if strict_mode():
        blocking = [it for it in items if it["severity"] == "block"]
        if blocking:
            raise SystemExit("Строгий сетевой режим: " + "; ".join(f"{b['id']}: {b['text']}" for b in blocking))
    return items
