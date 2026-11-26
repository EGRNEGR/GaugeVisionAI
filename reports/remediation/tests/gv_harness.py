"""
Общий каркас стендовых испытаний повторной приёмки GaugeVision AI.

Запускает настоящий сервер `run.py --demo` (HTTPS, uvicorn) в изолированном каталоге
данных, сторонние компоненты окружения (MQTT-брокер amqtt, RTSP-сервер mediamtx,
издатель ffmpeg, клиенты amqtt/pymodbus) и даёт клиентов REST / WebSocket.

Пути к сторонним инструментам не зашиты в код: они читаются из JSON-файла,
который создаёт `setup_validation_tools.py`, или из переменных окружения
GV_TOOLS_PY, GV_AMQTT, GV_MEDIAMTX, GV_FFMPEG.
"""
from __future__ import annotations

import json
import math
import os
import signal
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]
TESTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ADMIN_PASS = "Stand-Admin-7341"
ENGINEER_PASS = "Stand-Engineer-7341"
OPERATOR_PASS = "Stand-Operator-7341"
CALIBRATION = {"v_min": 0.0, "theta_min": 135.0, "v_max": 16.0, "theta_max": 45.0, "direction": "cw"}
THRESHOLDS = {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True}


def load_tools(path: str | None = None) -> dict[str, str]:
    """Пути к инструментам стенда: JSON (по умолчанию tests/.validation_tools.json) + переменные окружения."""
    cfg: dict[str, str] = {}
    p = Path(path) if path else TESTS_DIR / ".validation_tools.json"
    if p.is_file():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    for key, env in (("tools_py", "GV_TOOLS_PY"), ("amqtt", "GV_AMQTT"),
                     ("mediamtx", "GV_MEDIAMTX"), ("ffmpeg", "GV_FFMPEG")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def free_even_port_pair() -> int:
    for _ in range(200):
        p = free_port()
        p -= p % 2
        try:
            for q in (p, p + 1):
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.bind(("127.0.0.1", q))
                s.close()
            return p
        except OSError:
            continue
    raise RuntimeError("нет свободной пары чётный/нечётный UDP-портов")


def _spawn(cmd: list[str], log_path: Path, *, env: dict[str, str] | None = None,
           cwd: Path | None = None) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    fh = open(log_path, "ab", buffering=0)
    return subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env, cwd=str(cwd) if cwd else None,
                            creationflags=flags)


def stop_process(proc: subprocess.Popen | None, timeout: float = 20.0, graceful: bool = True) -> int | None:
    if proc is None or proc.poll() is not None:
        return None if proc is None else proc.returncode
    if graceful and os.name == "nt":
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, ValueError):
            pass
    elif graceful:
        proc.terminate()
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait(timeout=10)


# ---------------------------------------------------------------------------
# Сервер GaugeVision AI
# ---------------------------------------------------------------------------
class GaugeServer:
    def __init__(self, data_dir: Path, *, port: int | None = None, extra_env: dict[str, str] | None = None,
                 python: str | None = None) -> None:
        self.data_dir = data_dir
        self.port = port or free_port()
        self.extra_env = extra_env or {}
        self.python = python or sys.executable
        self.proc: subprocess.Popen | None = None
        self.log_path = data_dir / "server.log"
        self.base = f"https://127.0.0.1:{self.port}"

    def env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GAUGEVISION_")}
        d = self.data_dir
        env.update({
            "CUDA_VISIBLE_DEVICES": "",
            "GAUGEVISION_DEVICE": "cpu",
            "GAUGEVISION_DEMO": "1",
            "GAUGEVISION_DB": str(d / "gaugevision.db"),
            "GAUGEVISION_SF_DB": str(d / "store_forward.db"),
            "GAUGEVISION_INCIDENTS_DIR": str(d / "incidents"),
            "GAUGEVISION_AUTO_SPECS_DIR": str(d / "auto_specs"),
            "GAUGEVISION_VIDEOS_DIR": str(d / "videos"),
            "GAUGEVISION_ADMIN_PASS": ADMIN_PASS,
            "GAUGEVISION_ENGINEER_PASS": ENGINEER_PASS,
            "GAUGEVISION_OPERATOR_PASS": OPERATOR_PASS,
            "GAUGEVISION_AUTH_REQUIRED": "1",
            "GAUGEVISION_LAN_IP": "127.0.0.1",
            "YOLO_CONFIG_DIR": str(d / "yolo_cfg"),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        })
        env.update(self.extra_env)
        return env

    def start(self, timeout: float = 180.0) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "videos").mkdir(exist_ok=True)
        cmd = [self.python, "-B", "run.py", "--demo", "--device", "cpu", "--host", "127.0.0.1",
               "--port", str(self.port), "--lan-ip", "127.0.0.1", "--db", str(self.data_dir / "gaugevision.db")]
        self.proc = _spawn(cmd, self.log_path, env=self.env(), cwd=ROOT)
        t_end = time.time() + timeout
        last_err = None
        while time.time() < t_end:
            if self.proc.poll() is not None:
                raise RuntimeError(f"сервер завершился при старте (rc={self.proc.returncode}), см. {self.log_path}")
            try:
                r = httpx.get(f"{self.base}/api/health", verify=False, timeout=3.0)
                if r.status_code == 200:
                    return
            except httpx.HTTPError as exc:
                last_err = exc
            time.sleep(1.0)
        raise TimeoutError(f"сервер не ответил за {timeout} с: {last_err}")

    def stop(self) -> int | None:
        rc = stop_process(self.proc, timeout=40.0)
        self.proc = None
        return rc

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None


class Api:
    def __init__(self, base: str, username: str = "admin", password: str = ADMIN_PASS) -> None:
        self.base = base
        self.client = httpx.Client(base_url=base, verify=False, timeout=60.0)
        r = self.client.post("/api/auth/login", json={"username": username, "password": password})
        r.raise_for_status()
        self.token = r.json()["token"]
        self.client.headers["Authorization"] = f"Bearer {self.token}"
        self.client.cookies.clear()

    def get(self, path: str, **kw: Any) -> Any:
        r = self.client.get(path, **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: Any = None, **kw: Any) -> httpx.Response:
        return self.client.post(path, json=body, **kw)

    def close(self) -> None:
        self.client.close()


def insecure_ssl() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ---------------------------------------------------------------------------
# Видеоматериал стенда: стрелочный прибор с известным значением
# ---------------------------------------------------------------------------
def gauge_frame(value: float, *, width: int = 640, height: int = 480, code: str = "СТ-01"):
    from app.stream_manager import render_gauge_frame

    return render_gauge_frame(code=code, name="Стендовый манометр", unit="МПа", value=value,
                              v_min=0.0, v_max=16.0, thresholds=THRESHOLDS, width=width, height=height)


def make_gauge_video(path: Path, schedule: list[tuple[float, float]], fps: int = 10) -> Path:
    """schedule: [(секунды, значение)] — ступенчатый профиль показаний с известной эталонной величиной."""
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    wr = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (640, 480))
    for seconds, value in schedule:
        frm = gauge_frame(value)
        for _ in range(int(round(seconds * fps))):
            wr.write(frm)
    wr.release()
    return path


def value_profile(t: float, period: float = 120.0) -> float:
    """Плавный профиль показаний для смартфон-камеры: 13,0 → 15,7 (авария) → 13,0 МПа."""
    ph = (t % period) / period
    return 13.0 + 2.7 * max(0.0, math.sin(ph * 2 * math.pi)) ** 2


# ---------------------------------------------------------------------------
# Сторонние компоненты: MQTT-брокер amqtt, RTSP-сервер mediamtx, издатель ffmpeg
# ---------------------------------------------------------------------------
class AmqttBroker:
    def __init__(self, tools: dict[str, str], work: Path, port: int | None = None) -> None:
        self.exe = tools["amqtt"]
        self.port = port or free_port()
        self.work = work
        self.proc: subprocess.Popen | None = None
        self.cfg = work / "amqtt_broker.yaml"
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(
            "listeners:\n  default:\n    type: tcp\n    bind: 127.0.0.1:%d\n"
            "plugins:\n  amqtt.plugins.authentication.AnonymousAuthPlugin:\n    allow_anonymous: true\n" % self.port,
            encoding="utf-8",
        )
        self.starts = 0

    def start(self) -> None:
        self.proc = _spawn([self.exe, "-c", str(self.cfg)], self.work / "amqtt_broker.log")
        self.starts += 1
        t_end = time.time() + 20
        while time.time() < t_end:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
                return
            except OSError:
                time.sleep(0.2)
        raise TimeoutError("брокер amqtt не открыл порт")

    def stop(self) -> None:
        stop_process(self.proc, timeout=5.0, graceful=False)
        self.proc = None


class MqttSubscriber:
    """Подписчик amqtt в отдельном процессе: пишет каждое полученное сообщение в JSONL."""

    def __init__(self, tools: dict[str, str], port: int, out: Path, topic: str = "interrao/#") -> None:
        self.cmd = [tools["tools_py"], "-B", str(TESTS_DIR / "mqtt_subscriber.py"), "--port", str(port),
                    "--topic", topic, "--out", str(out)]
        self.out = out
        self.log = out.with_suffix(".log")
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.proc = _spawn(self.cmd, self.log)
        time.sleep(1.5)

    def stop(self) -> None:
        stop_process(self.proc, timeout=5.0, graceful=False)
        self.proc = None

    def messages(self) -> list[dict[str, Any]]:
        if not self.out.is_file():
            return []
        out = []
        for ln in self.out.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out


class RtspStand:
    """RTSP-сервер mediamtx с аутентификацией и издатель ffmpeg (кольцевое воспроизведение файла)."""

    VIEW_USER = "gv_viewer"
    VIEW_PASS = "V1ew-Secret-77"

    def __init__(self, tools: dict[str, str], work: Path, video: Path, port: int | None = None) -> None:
        self.mediamtx = tools["mediamtx"]
        self.ffmpeg = tools["ffmpeg"]
        self.work = work
        self.video = video
        self.port = port or free_port()
        self.rtp = free_even_port_pair()  # mediamtx: RTP — чётный порт, RTCP — следующий
        self.mtx: subprocess.Popen | None = None
        self.pub: subprocess.Popen | None = None
        self.cfg = work / "mediamtx.yml"

    @property
    def view_url(self) -> str:
        return f"rtsp://{self.VIEW_USER}:{self.VIEW_PASS}@127.0.0.1:{self.port}/gauge"

    def start_server(self) -> None:
        self.work.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(
            "logLevel: info\n"
            f"rtspAddress: 127.0.0.1:{self.port}\n"
            f"rtpAddress: 127.0.0.1:{self.rtp}\n"
            f"rtcpAddress: 127.0.0.1:{self.rtp + 1}\n"
            "rtmp: no\nhls: no\nwebrtc: no\nsrt: no\napi: no\nmetrics: no\npprof: no\nplayback: no\n"
            "authMethod: internal\n"
            "authInternalUsers:\n"
            "  - user: gv_publisher\n    pass: Pub-Secret-55\n    ips: []\n    permissions:\n      - action: publish\n"
            f"  - user: {self.VIEW_USER}\n    pass: {self.VIEW_PASS}\n    ips: []\n    permissions:\n      - action: read\n"
            "paths:\n  all_others:\n",
            encoding="utf-8",
        )
        self.mtx = _spawn([self.mediamtx, str(self.cfg)], self.work / "mediamtx.log", cwd=self.work)
        t_end = time.time() + 20
        while time.time() < t_end:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
                return
            except OSError:
                time.sleep(0.2)
        raise TimeoutError("mediamtx не открыл RTSP-порт")

    def start_publisher(self) -> None:
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "warning", "-re", "-stream_loop", "-1",
               "-i", str(self.video), "-an", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
               "-g", "10", "-pix_fmt", "yuv420p", "-rtsp_transport", "tcp", "-f", "rtsp",
               f"rtsp://gv_publisher:Pub-Secret-55@127.0.0.1:{self.port}/gauge"]
        self.pub = _spawn(cmd, self.work / "ffmpeg_publisher.log")

    def stop_publisher(self) -> None:
        stop_process(self.pub, timeout=5.0, graceful=False)
        self.pub = None

    def stop(self) -> None:
        self.stop_publisher()
        stop_process(self.mtx, timeout=5.0, graceful=False)
        self.mtx = None


def modbus_probe(tools: dict[str, str], port: int, unit: int = 1, start: int = 0, count: int = 16) -> dict[str, Any]:
    """Чтение регистров сторонним клиентом pymodbus (отдельный процесс)."""
    out = subprocess.run([tools["tools_py"], "-B", str(TESTS_DIR / "modbus_probe.py"), "--port", str(port),
                          "--unit", str(unit), "--start", str(start), "--count", str(count)],
                         capture_output=True, text=True, timeout=30)
    line = next((ln for ln in out.stdout.splitlines() if ln.startswith("{")), None)
    if not line:
        raise RuntimeError(f"modbus_probe: rc={out.returncode} {out.stdout[-400:]} {out.stderr[-800:]}")
    return json.loads(line)
