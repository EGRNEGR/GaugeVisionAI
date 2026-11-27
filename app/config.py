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
# Пути и загрузка .env (автономный контур, без внешних зависимостей)
# ---------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent.parent


def _load_dotenv(env_path: Path) -> None:
    """Загружает переменные из .env в корне репозитория без перезаписи уже заданных."""
    if not env_path.is_file():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


_load_dotenv(BASE_DIR / ".env")

CERTS_DIR: Path = BASE_DIR / "certs"
STATIC_DIR: Path = BASE_DIR / "static"
DATA_DIR: Path = BASE_DIR / "data"
MODELS_DIR: Path = BASE_DIR / "models"
EXPORTS_DIR: Path = DATA_DIR / "exports"
DEMO_MODE: bool = os.environ.get("GAUGEVISION_DEMO", "").strip().lower() in ("1", "true", "yes", "on", "demo")
DEMO_DB_DEFAULT: Path = DATA_DIR / "gaugevision_demo.db"
DB_PATH: Path = Path(os.environ.get("GAUGEVISION_DB", DEMO_DB_DEFAULT if DEMO_MODE else DATA_DIR / "gaugevision.db"))
SF_DB_PATH: Path = Path(os.environ.get("GAUGEVISION_SF_DB", DATA_DIR / "store_forward.db"))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_sf_db_path() -> Path:
    explicit = os.environ.get("GAUGEVISION_SF_DB")
    if explicit:
        return Path(explicit)
    db_override = os.environ.get("GAUGEVISION_DB")
    if db_override:
        return Path(db_override).resolve().parent / "store_forward.db"
    return DATA_DIR / ("store_forward_demo.db" if is_demo_mode() else "store_forward.db")


def is_demo_mode() -> bool:
    env = os.environ.get("GAUGEVISION_DEMO")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on", "demo")
    return DEMO_MODE


def get_db_path() -> Path:
    explicit = os.environ.get("GAUGEVISION_DB")
    if explicit:
        return Path(explicit)
    return DEMO_DB_DEFAULT if is_demo_mode() else (DATA_DIR / "gaugevision.db")


def configure_runtime(*, demo: bool | None = None, db_path: str | None = None,
                      device: str | None = None) -> None:
    """Применяет параметры запуска из CLI до инициализации БД и конвейера."""
    global DEMO_MODE, DB_PATH, YOLO_DEVICE
    if demo is not None:
        DEMO_MODE = bool(demo)
        os.environ["GAUGEVISION_DEMO"] = "1" if demo else "0"
    if db_path:
        os.environ["GAUGEVISION_DB"] = db_path
    DB_PATH = get_db_path()
    if device:
        os.environ["GAUGEVISION_DEVICE"] = device
        YOLO_DEVICE = device


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
EVENTS_MAX: int = 1000          # записей журнала событий пульта в памяти сервера
EVENT_SNAPSHOTS_MAX: int = 150  # стоп-кадров срабатываний к последним событиям
TREND_BUCKETS_MAX: int = 1000   # точек агрегированного тренда за смену
READING_STALE_SECONDS: float = float(os.environ.get("GAUGEVISION_STALE_SECONDS", "6.0"))

# ---------------------------------------------------------------------------
# Multi-Gauge Vision: несколько приборов в кадре одного источника
# ---------------------------------------------------------------------------
MG_MAX_INSTRUMENTS_PER_SOURCE: int = 32
MG_MIN_ELLIPSE_AREA_FRAC: float = 0.002  # мин. площадь контура-кандидата в долях кадра (щит 4×4 и плотнее)
MG_MATCH_GATE: float = 0.45       # сопоставление: смещение центра ≤ доли радиуса якоря
MG_RADIUS_RATIO: tuple[float, float] = (0.70, 1.45)  # допустимое отношение радиусов найденного и якоря
MG_AMBIGUITY_MARGIN: float = 0.10  # второй кандидат хуже лучшего меньше чем на эту долю радиуса — неоднозначно
MG_LOST_AFTER: int = 3            # проходов детектора без сопоставления до состояния «потерян»
MG_REDETECT_UNLOCKED: int = 3     # период детекции, пока не все приборы захвачены, кадров
MG_WORKERS: int = max(1, min(4, (os.cpu_count() or 2) // 2))  # потоков обработки ROI
MG_REGISTER_OVERLAP: float = 0.5  # новый прибор ближе этой доли радиуса к существующему — дубликат
MG_TELEMETRY_INTERVAL: float = 5.0  # телеметрия каждого прибора многоприборного источника в MQTT, с

# ---------------------------------------------------------------------------
# Auto Calibration (экспериментальный модуль, NG-AC-01): по умолчанию выключен, включается только
# по итогам испытаний (reports/next_generation/AUTO_CALIBRATION_PROTOCOL.md)
# ---------------------------------------------------------------------------
AUTOCAL_ENABLED: bool = os.environ.get("GAUGEVISION_AUTOCAL", "0").lower() in ("1", "true", "yes")
AUTOCAL_OCR_THREADS: int = max(1, min(4, (os.cpu_count() or 2) // 2))

# ---------------------------------------------------------------------------
# Демонстрационный профиль (36 приборов: 1 живая камера + 35 симуляция)
# ---------------------------------------------------------------------------
DEMO_LIVE_CAM_ID: str = "demo-mtp160-steam"
DEMO_TOTAL_POSITIONS: int = 36
DEMO_SEED: int = int(os.environ.get("GAUGEVISION_DEMO_SEED", "42"))
DEMO_SIM_INTERVAL: float = 1.0
# Шаг записи телеметрии стендовых приборов в SQLite (instrument_readings), с
DEMO_SIM_PERSIST_INTERVAL: float = float(os.environ.get("GAUGEVISION_SIM_PERSIST_INTERVAL", "5.0"))
SIMULATOR_URL: str = os.environ.get(
    "GAUGEVISION_SIMULATOR_URL",
    "https://gaugevision-simulator.goodlyoatmeal32.chatgpt.site/",
)

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
CAMERA_TYPES: tuple[str, ...] = ("device", "rtsp", "http_mjpeg", "phone_ws", "video_file")

# Статусы потока (раздел 2.4 ТЗ) + расширенные статусы Edge-аналитики
CAMERA_STATUSES: tuple[str, ...] = ("online", "reconnecting", "offline")
EDGE_HEALTH_STATUSES: tuple[str, ...] = ("ONLINE", "DEGRADED", "OFFLINE")

# ---------------------------------------------------------------------------
# Трек №2: Архитектурная видеоаналитика, Adaptive FPS, Store-and-Forward, SCADA
# ---------------------------------------------------------------------------
EDGE_NODE_ID: str = os.environ.get("GAUGEVISION_EDGE_NODE_ID", "edge-ktc-01")
PLANT_NAME: str = os.environ.get("GAUGEVISION_PLANT_NAME", "ТЭЦ-22 ПАО «Интер РАО» (Котлотурбинный цех)")
PLANT_BRANCH: str = os.environ.get("GAUGEVISION_PLANT_BRANCH", "Филиал «Московская генерация»")

# Adaptive FPS (Event-Driven Inference)
ADAPTIVE_FPS_IDLE: float = _env_float("GAUGEVISION_ADAPTIVE_FPS_IDLE", 1.0)
ADAPTIVE_FPS_ACTIVE: float = _env_float("GAUGEVISION_ADAPTIVE_FPS_ACTIVE", 6.0)
ADAPTIVE_HOLD_SECONDS: float = _env_float("GAUGEVISION_ADAPTIVE_HOLD_SECONDS", 15.0)
ADAPTIVE_DELTA_PCT: float = _env_float("GAUGEVISION_ADAPTIVE_DELTA_PCT", 2.5)
ADAPTIVE_MOTION_MAD: float = _env_float("GAUGEVISION_ADAPTIVE_MOTION_MAD", 2.4)
ADAPTIVE_WAKE_CHECK_INTERVAL: float = _env_float("GAUGEVISION_ADAPTIVE_WAKE_INTERVAL", 0.12)
RING_BUFFER_PRE_FRAMES: int = _env_int("GAUGEVISION_RING_PRE_FRAMES", 12)
RING_BUFFER_POST_FRAMES: int = _env_int("GAUGEVISION_RING_POST_FRAMES", 8)
RING_BUFFER_MAX_CLIPS: int = _env_int("GAUGEVISION_RING_MAX_CLIPS", 20)

# Store-and-Forward буфер (SQLite WAL)
SF_BATCH_SIZE: int = _env_int("GAUGEVISION_SF_BATCH_SIZE", 40)
SF_MAX_QUEUE_ROWS: int = _env_int("GAUGEVISION_SF_MAX_QUEUE_ROWS", 25000)
SF_MAX_PENDING_MB: float = _env_float("GAUGEVISION_SF_MAX_PENDING_MB", 128.0)
SF_MIN_DISK_FREE_MB: float = _env_float("GAUGEVISION_SF_MIN_DISK_FREE_MB", 100.0)
SF_SYNC_INTERVAL: float = _env_float("GAUGEVISION_SF_SYNC_INTERVAL", 1.2)
SF_BATCH_DELAY_S: float = _env_float("GAUGEVISION_SF_BATCH_DELAY", 0.0)

# Промышленные протоколы интеграции АСУ ТП (MQTT 3.1.1 / Modbus TCP)
MQTT_ENABLED: bool = _env_bool("GAUGEVISION_MQTT_ENABLED", False)
MQTT_HOST: str = os.environ.get("GAUGEVISION_MQTT_HOST", "127.0.0.1")
MQTT_PORT: int = _env_int("GAUGEVISION_MQTT_PORT", 1883)
MQTT_TOPIC_PREFIX: str = os.environ.get("GAUGEVISION_MQTT_TOPIC_PREFIX", "interrao/tec22/ktc/gaugevision")
MQTT_CLIENT_ID: str = os.environ.get("GAUGEVISION_MQTT_CLIENT_ID", f"gv-{EDGE_NODE_ID}")
MQTT_USERNAME: str = os.environ.get("GAUGEVISION_MQTT_USERNAME", "")
MQTT_PASSWORD: str = os.environ.get("GAUGEVISION_MQTT_PASSWORD", "")
MQTT_QOS: int = _env_int("GAUGEVISION_MQTT_QOS", 1)
MQTT_KEEPALIVE: int = _env_int("GAUGEVISION_MQTT_KEEPALIVE", 30)
MQTT_ACK_TIMEOUT: float = _env_float("GAUGEVISION_MQTT_ACK_TIMEOUT", 2.5)
MQTT_TLS: bool = _env_bool("GAUGEVISION_MQTT_TLS", False)
MQTT_MAX_RETRIES: int = _env_int("GAUGEVISION_MQTT_MAX_RETRIES", 2)

MODBUS_ENABLED: bool = _env_bool("GAUGEVISION_MODBUS_ENABLED", False)
MODBUS_HOST: str = os.environ.get("GAUGEVISION_MODBUS_HOST", "127.0.0.1")
MODBUS_PORT: int = _env_int("GAUGEVISION_MODBUS_PORT", 15020)
MODBUS_UNIT_ID: int = _env_int("GAUGEVISION_MODBUS_UNIT_ID", 1)

# ---------------------------------------------------------------------------
# Безопасность, аутентификация / RBAC и ограничения видеоисточников (DEF-07)
# ---------------------------------------------------------------------------
AUTH_REQUIRED: bool = _env_bool("GAUGEVISION_AUTH_REQUIRED", True)
SESSION_TTL_SECONDS: int = _env_int("GAUGEVISION_SESSION_TTL", 12 * 3600)
ALLOW_FAULT_INJECTION: bool = _env_bool("GAUGEVISION_ALLOW_FAULT_INJECTION", False)
ALLOW_LOOPBACK_STREAMS: bool = _env_bool("GAUGEVISION_ALLOW_LOOPBACK_STREAMS", False)
ALLOW_EXTERNAL_STREAMS: bool = _env_bool("GAUGEVISION_ALLOW_EXTERNAL_STREAMS", False)
ALLOWED_STREAM_CIDRS: str = os.environ.get("GAUGEVISION_ALLOWED_STREAM_CIDRS", "")
CORS_ORIGINS: str = os.environ.get("GAUGEVISION_CORS_ORIGINS", "")
SECRET_KEY: str = os.environ.get("GAUGEVISION_SECRET_KEY", "")
ADMIN_USERNAME: str = os.environ.get("GAUGEVISION_ADMIN_USER", "admin")
ADMIN_PASSWORD: str = os.environ.get("GAUGEVISION_ADMIN_PASS", "GaugeAdmin!2026")
ENGINEER_USERNAME: str = os.environ.get("GAUGEVISION_ENGINEER_USER", "engineer")
ENGINEER_PASSWORD: str = os.environ.get("GAUGEVISION_ENGINEER_PASS", "GaugeEng!2026")
OPERATOR_USERNAME: str = os.environ.get("GAUGEVISION_OPERATOR_USER", "operator")
OPERATOR_PASSWORD: str = os.environ.get("GAUGEVISION_OPERATOR_PASS", "GaugeOp!2026")
# Публично известные стендовые пароли (.env.example, документация): вне деморежима не принимаются
KNOWN_DEFAULT_PASSWORDS: frozenset[str] = frozenset({"GaugeAdmin!2026", "GaugeEng!2026", "GaugeOp!2026"})
LOGIN_MAX_FAILURES: int = _env_int("GAUGEVISION_LOGIN_MAX_FAILURES", 5)
LOGIN_LOCKOUT_WINDOW_SECONDS: int = _env_int("GAUGEVISION_LOGIN_LOCKOUT_WINDOW", 300)
# Период повторной проверки сессии открытых WebSocket-подключений пульта, с
WS_SESSION_RECHECK_SECONDS: float = _env_float("GAUGEVISION_WS_SESSION_RECHECK", 15.0)


def get_videos_dir() -> Path:
    explicit = os.environ.get("GAUGEVISION_VIDEOS_DIR")
    if explicit:
        return Path(explicit).resolve()
    return (DATA_DIR / "videos").resolve()


def get_incidents_dir() -> Path:
    explicit = os.environ.get("GAUGEVISION_INCIDENTS_DIR")
    if explicit:
        return Path(explicit).resolve()
    return (get_db_path().resolve().parent / "incidents").resolve()


def get_auto_specs_dir() -> Path:
    explicit = os.environ.get("GAUGEVISION_AUTO_SPECS_DIR")
    if explicit:
        return Path(explicit).resolve()
    return (get_db_path().resolve().parent / "auto_specs").resolve()


# ---------------------------------------------------------------------------
# Трек №1: Умная диспетчеризация и генерация проектной документации / ТЗ
# ---------------------------------------------------------------------------
CRITICAL_WEAR_HEALTH_THRESHOLD: float = _env_float("GAUGEVISION_WEAR_THRESHOLD", 50.0)
# Минимальный шаг точек ряда диспетчерского анализа, с (цикл синхронизации архитектуры — 2 с, допуск на джиттер)
DISPATCH_MIN_SAMPLE_INTERVAL: float = _env_float("GAUGEVISION_DISPATCH_SAMPLE_INTERVAL", 1.5)
# Шумовой порог считывания: скачок между соседними точками ниже этой доли шкалы (%) не считается гидроударом
DISPATCH_JUMP_NOISE_PCT: float = _env_float("GAUGEVISION_DISPATCH_JUMP_NOISE_PCT", 1.5)
# «Регулярные перегрузки» (ТЗ, раздел 3 дефектной ведомости): минимум срабатываний уставок за период
# для включения исправного по остальным признакам прибора в ТЗ на модернизацию
SPEC_REGULAR_TRIPS_MIN: int = _env_int("GAUGEVISION_SPEC_REGULAR_TRIPS_MIN", 3)
AUTO_SPEC_COOLDOWN_SECONDS: float = _env_float("GAUGEVISION_AUTO_SPEC_COOLDOWN", 3600.0)
LLM_BASE_URL: str = os.environ.get("GAUGEVISION_LLM_BASE_URL", "").strip()
LLM_API_KEY: str = os.environ.get("GAUGEVISION_LLM_API_KEY", "").strip()
LLM_MODEL: str = os.environ.get("GAUGEVISION_LLM_MODEL", "qwen2.5:7b-instruct").strip()
LLM_TIMEOUT_SECONDS: float = _env_float("GAUGEVISION_LLM_TIMEOUT", 18.0)
LLM_MAX_TOKENS: int = _env_int("GAUGEVISION_LLM_MAX_TOKENS", 700)
# Рассуждающие модели (Qwen3, DeepSeek-R1 и др.) тратят весь лимит токенов на скрытые рассуждения
# и возвращают пустой content; по умолчанию рассуждения отключаются (reasoning_effort = none)
LLM_DISABLE_REASONING: bool = os.environ.get("GAUGEVISION_LLM_DISABLE_REASONING", "1").strip().lower() not in ("0", "false", "no")

# Конфигурируемые параметры ТЭО (ориентировочные справочные допущения)
ECO_COMMISSIONING_RATE: float = _env_float("GAUGEVISION_ECO_COMMISSIONING_RATE", 0.14)
ECO_ROUNDS_SAVINGS_RUB_YR: int = _env_int("GAUGEVISION_ECO_ROUNDS_SAVINGS_RUB", 38000)
ECO_OPEX_PER_SENSOR_RUB_YR: int = _env_int("GAUGEVISION_ECO_OPEX_RUB", 8000)


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
