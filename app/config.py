"""
GaugeVision AI — конфигурация приложения.

Пути, сетевые константы, параметры конвейера зрения и телеметрии,
справочник типов приборов и промышленных единиц измерения (раздел 1 ТЗ).
"""
from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent.parent
CERTS_DIR: Path = BASE_DIR / "certs"
STATIC_DIR: Path = BASE_DIR / "static"
DATA_DIR: Path = BASE_DIR / "data"
MODELS_DIR: Path = BASE_DIR / "models"
DB_PATH: Path = Path(os.environ.get("GAUGEVISION_DB", DATA_DIR / "gaugevision.db"))

# Веса YOLOv8 для детекции корпуса прибора (опционально, раздел 5.1 ТЗ).
# Без файла весов конвейер автоматически работает на OpenCV-fallback
# (CLAHE + HoughCircles) — никаких обращений в интернет не выполняется.
YOLO_WEIGHTS: Path = Path(os.environ.get("GAUGEVISION_YOLO", MODELS_DIR / "gauge_yolov8.pt"))
# Классы, считающиеся «корпусом прибора» (COCO-модель yolov8n знает «clock»)
YOLO_CLASSES: tuple[str, ...] = ("gauge", "dial", "meter", "manometer", "clock")
# Устройство инференса YOLO: "auto" (CUDA при наличии, иначе CPU), "cuda:0", "cpu"
YOLO_DEVICE: str = os.environ.get("GAUGEVISION_DEVICE", "auto")
YOLO_IMGSZ: int = 640
YOLO_CONF: float = 0.35

CERT_FILE: Path = CERTS_DIR / "cert.pem"
KEY_FILE: Path = CERTS_DIR / "key.pem"

# ---------------------------------------------------------------------------
# Сервер (HTTPS only, раздел 3 ТЗ)
# ---------------------------------------------------------------------------
HOST: str = os.environ.get("GAUGEVISION_HOST", "0.0.0.0")
HTTPS_PORT: int = int(os.environ.get("GAUGEVISION_PORT", "8443"))
CERT_VALID_DAYS: int = 365
CERT_KEY_SIZE: int = 2048

# ---------------------------------------------------------------------------
# Конвейер зрения и телеметрия (разделы 5–7 ТЗ)
# ---------------------------------------------------------------------------
EMA_ALPHA: float = 0.25          # V̄t = α·Vt + (1−α)·V̄t−1
DIAL_SIZE: int = 640             # диаметр нормализованного циферблата, px
PROCESS_FPS: float = 3.0         # частота обработки показаний каждой камеры
DB_WRITE_INTERVAL: float = 1.0   # мин. интервал записи отсчёта в SQLite, c
HISTORY_DEFAULT_LIMIT: int = 500
HISTORY_KEEP_DAYS: int = int(os.environ.get("GAUGEVISION_KEEP_DAYS", "90"))
PREVIEW_MAX_WIDTH: int = 960     # ширина JPEG-превью с оверлеем для дашборда
TREND_WINDOW_DEFAULT: int = 60   # точек микрографика по умолчанию (30/60/120)
TREND_WINDOWS: tuple[int, ...] = (30, 60, 120)
SNAPSHOT_JPEG_QUALITY: int = 82
REDETECT_EVERY_N_FRAMES: int = 15  # повторная локализация циферблата
MJPEG_FPS: float = 8.0           # частота раздачи MJPEG-превью на дашборд
MAX_PROCESS_WIDTH: int = 1280    # кадры шире масштабируются перед анализом
MIN_NEEDLE_CONFIDENCE: float = 0.25  # ниже — отсчёт недостоверен, держим последнее значение

# ---------------------------------------------------------------------------
# Захват потоков (раздел 2 ТЗ)
# ---------------------------------------------------------------------------
CAPTURE_BUFFERSIZE: int = 1      # Zero Latency Mode
# Exponential Backoff Reconnection: 1с, 2с, 4с, 8с, максимум 15с
RECONNECT_BACKOFF: tuple[int, ...] = (1, 2, 4, 8, 15)
OFFLINE_AFTER_FAILS: int = 8     # подряд неудачных подключений -> «Офлайн»
PHONE_TIMEOUT: float = 6.0       # нет кадров от смартфона N сек -> офлайн
PHONE_CAPTURE_FPS: float = 4.0   # рекомендуемая частота кадров веб-клиента
VISION_EXECUTOR_WORKERS: int = 2

# ---------------------------------------------------------------------------
# Обнаружение устройств (раздел 2.2 ТЗ)
# ---------------------------------------------------------------------------
SCAN_PORTS: tuple[int, ...] = (554, 80, 8080, 4747, 8554)
SCAN_TIMEOUT: float = 0.35
SCAN_MAX_WORKERS: int = 220
ONVIF_MULTICAST: tuple[str, int] = ("239.255.255.250", 3702)
ONVIF_PROBE_TIMEOUT: float = 3.0

# ---------------------------------------------------------------------------
# Спектр приборов и профессиональные единицы измерения (раздел 1 ТЗ)
# ---------------------------------------------------------------------------
GAUGE_TYPES: dict[str, dict] = {
    "pressure": {
        "label": "Давление — манометр / вакуумметр / мановакуумметр "
                 "(питательная вода, пар, мазут, газ)",
        "units": ["МПа", "бар", "кгс/см²", "кПа"],
    },
    "temperature": {
        "label": "Температура — термометр манометрический / биметаллический",
        "units": ["°C"],
    },
    "draft": {
        "label": "Тяга и разрежение — тягомер / напоромер / тягонапоромер "
                 "(топки котлов, газоходы, дутьевые вентиляторы)",
        "units": ["кПа", "Па", "кгс/м²"],
    },
    "level": {
        "label": "Уровень — стрелочный уровнемер (барабан котла, деаэратор, "
                 "конденсатосборники)",
        "units": ["%", "мм", "м"],
    },
    "electrical": {
        "label": "Электрические щитовые приборы — амперметр / вольтметр / "
                 "ваттметр (ГРУ/ОРУ, возбуждение генераторов)",
        "units": ["А", "кА", "В", "кВ", "МВт"],
    },
    "flow": {
        "label": "Расход — дифференциальный расходомер (дифманометр) "
                 "перегретого пара и питательной воды",
        "units": ["т/ч", "м³/ч"],
    },
}

ALL_UNITS: list[str] = sorted({u for g in GAUGE_TYPES.values() for u in g["units"]})

# Типы источников видеопотока (таблица cameras.type)
CAMERA_TYPES: tuple[str, ...] = ("device", "rtsp", "http_mjpeg", "phone_ws")

# Статусы потока (раздел 2.4 ТЗ)
CAMERA_STATUSES: tuple[str, ...] = ("online", "reconnecting", "offline")


def get_lan_ip() -> str:
    """
    Реальный IP-адрес хоста в текущей Wi-Fi/LAN сети.

    Определяется программно через UDP-сокет «к шлюзу» (8.8.8.8) без фактической
    отправки пакетов: ОС сама выбирает исходящий интерфейс и его адрес.
    """
    override = os.environ.get("GAUGEVISION_LAN_IP")
    if override:
        return override
    cands = candidate_lan_ips()
    return cands[0] if cands else "127.0.0.1"


def _ip_rank(ip: str) -> int | None:
    """
    Приоритет адреса для доступа со смартфона (меньше — лучше); None — отбросить.

    Отбрасываются loopback, link-local 169.254/16 (интерфейс без DHCP) и
    198.18/15 — диапазон RFC 2544, который занимают TUN-адаптеры VPN/прокси
    (Clash, sing-box, v2rayN и т.п.): с такого адреса смартфон сервер не увидит.
    """
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return None
    if addr.is_loopback or addr.is_link_local or addr.is_unspecified or addr.is_multicast:
        return None
    if addr in ipaddress.IPv4Network("198.18.0.0/15"):
        return None
    if addr in ipaddress.IPv4Network("192.168.0.0/16"):
        return 0
    if addr in ipaddress.IPv4Network("10.0.0.0/8"):
        return 1
    if addr in ipaddress.IPv4Network("172.16.0.0/12"):
        return 2
    if addr in ipaddress.IPv4Network("100.64.0.0/10"):
        return 4  # CGNAT / overlay-VPN (Tailscale) — только в крайнем случае
    return 3


def candidate_lan_ips() -> list[str]:
    """
    Все пригодные IPv4-адреса хоста, отсортированные по приоритету.

    Источники: UDP-сокет «к шлюзу» (8.8.8.8 и широковещательные адреса частных
    сетей — connect() пакетов не отправляет, ОС лишь выбирает интерфейс) и
    адреса всех интерфейсов хоста. При равном приоритете выигрывает адрес,
    выбранный таблицей маршрутизации.
    """
    found: list[str] = []
    for probe in ("8.8.8.8", "192.168.255.255", "10.255.255.255", "172.31.255.255"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((probe, 80))
            ip = str(sock.getsockname()[0])
            if ip not in found:
                found.append(ip)
        except OSError:
            pass
        finally:
            sock.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = str(info[4][0])
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    ranked = [(r, i, ip) for i, ip in enumerate(found) if (r := _ip_rank(ip)) is not None]
    ranked.sort()
    return [ip for _, _, ip in ranked]


def capture_url(cam_id: str, token: str, lan_ip: str | None = None) -> str:
    """Ссылка веб-клиента захвата «Смартфон как камера» (раздел 2.3 ТЗ)."""
    ip = lan_ip or get_lan_ip()
    return f"https://{ip}:{HTTPS_PORT}/capture?cam_id={cam_id}&token={token}"
