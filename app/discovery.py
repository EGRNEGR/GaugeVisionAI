"""
GaugeVision AI — zero-configuration network discovery (раздел 2.2 ТЗ).

1. ONVIF WS-Discovery: мультикаст-рассылка UDP SOAP-проб (Probe) на
   239.255.255.250:3702, сбор ProbeMatch-ответов камер ONVIF Profile S/T.
2. Fast Asynchronous Subnet Scanner: параллельный TCP-пинг подсети /24 по
   портам 554 (RTSP), 80/8080 (HTTP/MJPEG/web), 4747 (DroidCam), 8554 (RTSP MS).
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import uuid
from dataclasses import dataclass, field

from . import config

logger = logging.getLogger("gaugevision.discovery")

WS_DISCOVERY_ADDR = config.ONVIF_MULTICAST

PROBE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <s:Header>
    <a:Action s:mustUnderstand="1">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
    <a:MessageID>urn:uuid:{msg_id}</a:MessageID>
    <a:ReplyTo>
      <a:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
    </a:ReplyTo>
    <a:To s:mustUnderstand="1">urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
  </s:Header>
  <s:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </s:Body>
</s:Envelope>"""


@dataclass
class DiscoveredDevice:
    """Найденное сетевое устройство (камера/смартфон-нода/медиа-сервер)."""
    ip: str
    open_ports: list[int] = field(default_factory=list)
    source: str = "tcp_scan"          # "tcp_scan" | "onvif"
    vendor: str | None = None         # из ONVIF Scopes / HTTP Server header
    xaddrs: str | None = None         # ONVIF device service URL
    suggested_url: str | None = None  # готовый rtsp:// или http:// URL
    suggested_type: str = "rtsp"      # device | rtsp | http_mjpeg

    def as_dict(self) -> dict:
        return {
            "ip": self.ip,
            "open_ports": self.open_ports,
            "source": self.source,
            "vendor": self.vendor,
            "xaddrs": self.xaddrs,
            "suggested_url": self.suggested_url,
            "suggested_type": self.suggested_type,
        }


# ---------------------------------------------------------------------------
# Быстрый асинхронный TCP-пинг портов
# ---------------------------------------------------------------------------
async def _probe_port(ip: str, port: int, timeout: float) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
    except (OSError, asyncio.TimeoutError):
        return False
    try:
        writer.close()
        await writer.wait_closed()
    except OSError:
        pass
    return True


RTSP_PORTS = {554, 8554}


async def _verify_service(ip: str, port: int, timeout: float) -> tuple[bool, str | None]:
    """
    Проверка протокола на открытом порту (отсекает ложные срабатывания
    фаерволов/VPN-прокси, принимающих любое TCP-соединение):
    RTSP — запрос OPTIONS, ожидаем «RTSP/1.x»; HTTP — GET /, ожидаем «HTTP/1.x».
    Возвращает (подтверждено, заголовок Server).
    """
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
    except (OSError, asyncio.TimeoutError):
        return False, None
    try:
        if port in RTSP_PORTS:
            req = (f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\n"
                   f"User-Agent: GaugeVision\r\n\r\n")
            prefix = "RTSP/"
        else:
            req = f"GET / HTTP/1.0\r\nHost: {ip}\r\nUser-Agent: GaugeVision\r\n\r\n"
            prefix = "HTTP/"
        writer.write(req.encode("ascii"))
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=timeout * 3)
        text = data.decode("latin-1", errors="replace")
        server = None
        m = re.search(r"^Server:\s*(.+?)\s*$", text, re.I | re.M)
        if m:
            server = m.group(1)[:80]
        return text.startswith(prefix), server
    except (OSError, asyncio.TimeoutError, UnicodeError):
        return False, None
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


def _guess_device(ip: str, open_ports: set[int], servers: dict[int, str] | None = None) -> DiscoveredDevice:
    """Эвристика выбора типа источника по набору открытых портов и заголовкам Server."""
    dev = DiscoveredDevice(ip=ip, open_ports=sorted(open_ports))
    srv = " ".join((servers or {}).values()).lower()
    if "ip webcam" in srv and 8080 in open_ports:
        dev.suggested_url = f"http://{ip}:8080/video"
        dev.suggested_type = "http_mjpeg"
        dev.vendor = "Android IP Webcam"
        return dev
    if "hikvision" in srv or "dnvrs" in srv:
        dev.vendor = "Hikvision"
        if 554 in open_ports:
            dev.suggested_url = f"rtsp://{ip}:554/Streaming/Channels/101"
            dev.suggested_type = "rtsp"
            return dev
    if "dahua" in srv and 554 in open_ports:
        dev.vendor = "Dahua"
        dev.suggested_url = f"rtsp://{ip}:554/cam/realmonitor?channel=1&subtype=0"
        dev.suggested_type = "rtsp"
        return dev
    if 4747 in open_ports:
        # DroidCam / Android-нода: HTTP MJPEG на 4747
        dev.suggested_url = f"http://{ip}:4747/video"
        dev.suggested_type = "http_mjpeg"
        dev.vendor = "DroidCam (mobile node)"
    elif 554 in open_ports:
        dev.suggested_url = f"rtsp://{ip}:554/"
        dev.suggested_type = "rtsp"
        dev.vendor = dev.vendor or "IP camera (RTSP)"
    elif 8554 in open_ports:
        dev.suggested_url = f"rtsp://{ip}:8554/"
        dev.suggested_type = "rtsp"
        dev.vendor = dev.vendor or "RTSP Media Server"
    elif 8080 in open_ports or 80 in open_ports:
        port = 8080 if 8080 in open_ports else 80
        dev.suggested_url = f"http://{ip}:{port}/"
        dev.suggested_type = "http_mjpeg"
        dev.vendor = dev.vendor or "HTTP-устройство (веб-камера / MJPEG?)"
    if servers and not dev.vendor:
        dev.vendor = next(iter(servers.values()))
    elif servers and dev.vendor and dev.vendor.startswith(("IP camera", "HTTP-")):
        dev.vendor = f"{dev.vendor} · {next(iter(servers.values()))}"
    return dev


async def scan_subnet(base_ip: str | None = None,
                      ports: tuple[int, ...] = config.SCAN_PORTS,
                      timeout: float = config.SCAN_TIMEOUT) -> list[DiscoveredDevice]:
    """
    Параллельное сканирование подсети /24 (x.x.x.1–254) по заданным портам.

    Семья задач ограничена семафором SCAN_MAX_WORKERS, чтобы не забивать
    сокет-таблицу хоста. Возвращает список устройств с открытыми портами.
    """
    if base_ip is None:
        base_ip = config.get_lan_ip()
    try:
        network = ipaddress.IPv4Network(f"{base_ip}/24", strict=False)
    except ValueError:
        logger.error("Некорректный адрес подсети: %s", base_ip)
        return []

    hosts = [str(h) for h in network.hosts()]  # .1 – .254
    sem = asyncio.Semaphore(config.SCAN_MAX_WORKERS)
    results: dict[str, set[int]] = {}
    results_lock = asyncio.Lock()

    async def check(ip: str, port: int) -> None:
        async with sem:
            if await _probe_port(ip, port, timeout):
                async with results_lock:
                    results.setdefault(ip, set()).add(port)

    tasks = [asyncio.create_task(check(ip, p)) for ip in hosts for p in ports]
    logger.info("Сканирование подсети %s: %d задач (%d хостов × %d портов)",
                network, len(tasks), len(hosts), len(ports))
    await asyncio.gather(*tasks, return_exceptions=True)

    # Протокольная проверка открытых портов (RTSP OPTIONS / HTTP GET)
    verified: dict[str, set[int]] = {}
    servers: dict[str, dict[int, str]] = {}

    async def verify(ip: str, port: int) -> None:
        async with sem:
            ok, server = await _verify_service(ip, port, max(timeout, 0.6))
        if ok:
            verified.setdefault(ip, set()).add(port)
            if server:
                servers.setdefault(ip, {})[port] = server

    await asyncio.gather(*(verify(ip, p) for ip, ps in results.items() for p in ps),
                         return_exceptions=True)
    dropped = len(results) - len(verified)
    if dropped:
        logger.info("Отброшено хостов без подтверждения протокола: %d", dropped)

    devices = [_guess_device(ip, ports_open, servers.get(ip)) for ip, ports_open in verified.items()]
    devices.sort(key=lambda d: tuple(int(x) for x in d.ip.split(".")))
    return devices


# ---------------------------------------------------------------------------
# ONVIF WS-Discovery (мультикаст UDP SOAP Probe)
# ---------------------------------------------------------------------------
def _local_addresses() -> list[str]:
    """Все локальные IPv4-адреса хоста (для привязки мультикаст-сокета)."""
    addrs: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in addrs and not ip.startswith("127."):
                addrs.append(ip)
    except OSError:
        pass
    if not addrs:
        lan = config.get_lan_ip()
        if not lan.startswith("127."):
            addrs.append(lan)
    return addrs


def _parse_probe_match(payload: bytes, addr: str) -> DiscoveredDevice | None:
    """Разбор SOAP ProbeMatch: XAddrs и Scopes (вендор/модель)."""
    try:
        text = payload.decode("utf-8", errors="replace")
    except Exception:
        return None

    xaddrs_m = re.search(r"<[^>]*XAddrs[^>]*>\s*([^<]+?)\s*<", text)
    xaddrs = xaddrs_m.group(1).split()[0] if xaddrs_m else None

    vendor = None
    scopes_m = re.search(r"<[^>]*Scopes[^>]*>(.*?)</", text, re.S)
    if scopes_m:
        scopes = scopes_m.group(1).split()
        for sc in scopes:
            if "hardware/" in sc:
                vendor = sc.split("hardware/")[-1]
            elif "name/" in sc:
                vendor = vendor or sc.split("name/")[-1]

    ip = addr
    if xaddrs:
        m = re.search(r"https?://([^/:]+)", xaddrs)
        if m:
            ip = m.group(1)

    dev = DiscoveredDevice(
        ip=ip, open_ports=[80], source="onvif",
        vendor=vendor or "ONVIF camera", xaddrs=xaddrs,
    )
    # типовые RTSP-пути распространённых вендоров
    v = (vendor or "").lower()
    if "hikvision" in v:
        dev.suggested_url = f"rtsp://{ip}:554/Streaming/Channels/101"
    elif "dahua" in v:
        dev.suggested_url = f"rtsp://{ip}:554/cam/realmonitor?channel=1&subtype=0"
    elif "axis" in v:
        dev.suggested_url = f"rtsp://{ip}:554/axis-media/media.amp"
    else:
        dev.suggested_url = f"rtsp://{ip}:554/"
    dev.suggested_type = "rtsp"
    return dev


async def onvif_discover(timeout: float = config.ONVIF_PROBE_TIMEOUT) -> list[DiscoveredDevice]:
    """
    Мультикаст WS-Discovery Probe + сбор ProbeMatch-ответов (asyncio).

    ProbeMatch-ответы приходят юникастом на порт-отправитель, поэтому для
    каждого локального интерфейса открывается сокет на эфемерном порту
    (порт 3702 на Windows занят службой Function Discovery) с IP_MULTICAST_IF,
    Probe отправляется дважды (UDP без гарантии доставки).
    """
    loop = asyncio.get_running_loop()
    probe = PROBE_TEMPLATE.format(msg_id=uuid.uuid4()).encode("utf-8")
    mcast_ip, mcast_port = WS_DISCOVERY_ADDR
    found: dict[str, DiscoveredDevice] = {}
    sockets: list[socket.socket] = []

    local_ips = _local_addresses() or ["0.0.0.0"]
    for local_ip in local_ips:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.bind((local_ip, 0))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            if local_ip != "0.0.0.0":
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                                socket.inet_aton(local_ip))
            sock.setblocking(False)
            for _ in range(2):
                sock.sendto(probe, (mcast_ip, mcast_port))
            sockets.append(sock)
        except OSError as exc:
            logger.debug("ONVIF socket %s: %s", local_ip, exc)
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    if not sockets:
        logger.warning("ONVIF Probe: не удалось создать мультикаст-сокеты")
        return []

    async def reader(sock: socket.socket) -> None:
        while True:
            try:
                payload, addr = await loop.sock_recvfrom(sock, 65535)
            except (OSError, asyncio.CancelledError):
                return
            dev = _parse_probe_match(payload, addr[0])
            if dev is not None:
                found.setdefault(dev.ip, dev)

    readers = [asyncio.create_task(reader(s)) for s in sockets]
    try:
        await asyncio.sleep(timeout)
    finally:
        for t in readers:
            t.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        for s in sockets:
            s.close()

    logger.info("ONVIF WS-Discovery: найдено устройств: %d", len(found))
    return list(found.values())


# ---------------------------------------------------------------------------
# Совмещённое обнаружение (для REST /api/discover)
# ---------------------------------------------------------------------------
async def discover_all(timeout: float = 4.0, base_ip: str | None = None) -> list[dict]:
    """
    Параллельно: ONVIF Probe + TCP-скан подсети /24 (по умолчанию — подсеть хоста).

    ONVIF-устройства имеют приоритет при дедупликации по IP.
    """
    onvif_res, scan_res = await asyncio.gather(
        onvif_discover(timeout), scan_subnet(base_ip), return_exceptions=True
    )
    onvif_devs: list[DiscoveredDevice] = [] if isinstance(onvif_res, BaseException) else onvif_res
    scan_devs: list[DiscoveredDevice] = [] if isinstance(scan_res, BaseException) else scan_res
    if isinstance(onvif_res, BaseException):
        logger.warning("ONVIF discovery error: %s", onvif_res)
    if isinstance(scan_res, BaseException):
        logger.warning("Subnet scan error: %s", scan_res)

    # собственный хост не предлагаем как камеру (кроме реальных RTSP/DroidCam портов)
    own_ip = config.get_lan_ip()
    scan_devs = [d for d in scan_devs
                 if d.ip != own_ip or set(d.open_ports) & {554, 4747, 8554}]

    merged: dict[str, DiscoveredDevice] = {}
    for dev in scan_devs:
        merged[dev.ip] = dev
    for dev in onvif_devs:
        prev = merged.get(dev.ip)
        if prev:
            # обогащаем TCP-находку ONVIF-метаданными
            prev.source = "onvif+tcp"
            prev.vendor = dev.vendor or prev.vendor
            prev.xaddrs = dev.xaddrs
            prev.suggested_url = dev.suggested_url or prev.suggested_url
        else:
            merged[dev.ip] = dev

    devices = sorted(merged.values(),
                     key=lambda d: tuple(int(x) for x in d.ip.split(".")))
    return [d.as_dict() for d in devices]
