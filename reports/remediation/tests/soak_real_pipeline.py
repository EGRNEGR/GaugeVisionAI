"""
Непрерывный soak-тест работающего GaugeVision AI (по умолчанию 3600 с, строго CPU).

Нагружается настоящий процесс `run.py --demo` (HTTPS, RBAC, SQLite WAL), а не отдельные классы:
  • CV-каналы: 2 стендовых Edge-потока, RTSP-камера (mediamtx + ffmpeg, с паролем),
    видеофайл (VideoFileWorker), смартфон-камера по WSS с периодическими авариями;
  • клиенты HMI: 2 WebSocket-пульта, SSE-поток, REST-опрос как у интерфейса,
    предпросмотр ТЗ каждую минуту, скачивание .docx каждые 10 минут, смена сценариев;
  • реальные отказы: остановка стороннего MQTT-брокера amqtt на 60 с каждые 10 минут,
    остановка RTSP-издателя на 30 с каждые 15 минут, симуляция обрыва АСУ ТП из UI
    и деградация видеосигнала каждые 20 минут;
  • метрики каждые SOAK_SAMPLE_S (15 с) дописываются в samples.jsonl: RSS/private bytes,
    потоки, дескрипторы, TCP-соединения, CPU процесса сервера; FPS/задержка/состояние
    каналов; очередь S&F; размеры SQLite и WAL; число отсчётов и событий; клипы;
    автодокументы; задержка API; сообщения WS/SSE/MQTT; ошибки журнала.
По завершении — анализ трендов (утечки, деградация, накопление очередей) в summary.json.

  python reports/remediation/tests/soak_real_pipeline.py --out reports/remediation/evidence/soak
Переменные: SOAK_DURATION_S (3600), SOAK_SAMPLE_S (15).
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gv_harness as H  # noqa: E402

import cv2  # noqa: E402
import httpx  # noqa: E402
import psutil  # noqa: E402
import websockets  # noqa: E402

DURATION = int(os.environ.get("SOAK_DURATION_S", "3600"))
SAMPLE_S = int(os.environ.get("SOAK_SAMPLE_S", "15"))


class Counters:
    def __init__(self) -> None:
        self.ws_msgs = 0
        self.ws_reconnects = 0
        self.sse_events = 0
        self.phone_frames = 0
        self.phone_errors = 0
        self.api_calls = 0
        self.keepalive_retries = 0
        self.api_errors: list[str] = []
        self.api_lat_ms: list[float] = []
        self.specs_preview = 0
        self.docx_ok = 0
        self.docx_bad = 0
        self.faults: list[dict[str, Any]] = []
        self.lock = threading.Lock()


def sqlite_count(path: Path, sql: str) -> int | None:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            return int(con.execute(sql).fetchone()[0])
        finally:
            con.close()
    except sqlite3.Error:
        return None


def fsize(*paths: Path) -> float:
    return round(sum(p.stat().st_size for p in paths if p.is_file()) / 1048576.0, 3)


def dir_stats(d: Path) -> tuple[int, float]:
    if not d.is_dir():
        return 0, 0.0
    files = [p for p in d.rglob("*") if p.is_file()]
    return len(files), round(sum(p.stat().st_size for p in files) / 1048576.0, 3)


def linreg_slope(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3:
        return 0.0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0


async def ws_dashboard(base_wss: str, token: str, c: Counters, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with websockets.connect(f"{base_wss}/ws/dashboard?token={token}", ssl=H.insecure_ssl(),
                                          max_size=None, ping_interval=20) as ws:
                while not stop.is_set():
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=5.0)
                        c.ws_msgs += 1
                    except asyncio.TimeoutError:
                        continue
        except Exception:
            c.ws_reconnects += 1
            await asyncio.sleep(2.0)


async def sse_client(base: str, token: str, c: Counters, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with httpx.AsyncClient(verify=False, timeout=None) as cl:
                async with cl.stream("GET", f"{base}/api/events/stream", headers={"Authorization": f"Bearer {token}"}) as r:
                    async for line in r.aiter_lines():
                        if stop.is_set():
                            return
                        if line.startswith("event:"):
                            c.sse_events += 1
        except Exception:
            await asyncio.sleep(2.0)


async def phone_client(base_wss: str, cam_id: str, token: str, c: Counters, stop: asyncio.Event, t0: float) -> None:
    while not stop.is_set():
        try:
            async with websockets.connect(f"{base_wss}/ws/phone/{cam_id}?token={token}", ssl=H.insecure_ssl(),
                                          max_size=None) as ws:
                await ws.recv()
                while not stop.is_set():
                    v = H.value_profile(time.time() - t0, period=300.0)
                    ok, buf = cv2.imencode(".jpg", H.gauge_frame(v, code="К1-Р01"), [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                    await ws.send(buf.tobytes())
                    await ws.recv()
                    c.phone_frames += 1
                    await asyncio.sleep(0.33)
        except Exception:
            c.phone_errors += 1
            await asyncio.sleep(1.0)


async def api_call(cl: httpx.AsyncClient, c: Counters, method: str, path: str, **kw: Any) -> httpx.Response | None:
    t = time.perf_counter()
    try:
        try:
            r = await cl.request(method, path, **kw)
        except httpx.RemoteProtocolError:
            # гонка keep-alive: сервер закрыл простаивающее соединение в момент повторного использования
            c.keepalive_retries += 1
            r = await cl.request(method, path, **kw)
        c.api_calls += 1
        if r.status_code >= 400:
            c.api_errors.append(f"{method} {path} {r.status_code}")
        return r
    except Exception as exc:
        c.api_errors.append(f"{method} {path} {type(exc).__name__}")
        return None
    finally:
        c.api_lat_ms.append((time.perf_counter() - t) * 1000.0)


async def hmi_poller(base: str, token: str, c: Counters, stop: asyncio.Event, t0: float) -> None:
    hdr = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=base, verify=False, timeout=120, headers=hdr) as cl:
        last_prev = last_docx = last_scn = 0.0
        scenarios = ["mixed", "peak", "cascade", "nominal"]
        while not stop.is_set():
            el = time.time() - t0
            for p in ("/api/dispatch/overview", "/api/architecture/status", "/api/instruments", "/api/events?limit=100",
                      "/api/dispatch/incidents?limit=8", "/api/specs/auto"):
                await api_call(cl, c, "GET", p)
            if el - last_prev >= 60:
                last_prev = el
                r = await api_call(cl, c, "POST", "/api/specs/preview", json={"period": "12h"})
                if r is not None and r.status_code == 200:
                    c.specs_preview += 1
            if el - last_docx >= 600:
                last_docx = el
                r = await api_call(cl, c, "POST", "/api/specs/generate", json={"period": "24h", "format": "docx"})
                ok = False
                if r is not None and r.status_code == 200:
                    try:
                        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                            ok = "word/document.xml" in zf.namelist()
                    except zipfile.BadZipFile:
                        ok = False
                if ok:
                    c.docx_ok += 1
                else:
                    c.docx_bad += 1
            if el - last_scn >= 900:
                last_scn = el
                scn = scenarios[int(el // 900) % len(scenarios)]
                await api_call(cl, c, "POST", "/api/demo/scenario", json={"scenario": scn})
            await asyncio.sleep(4.0)


async def fault_scheduler(base: str, admin_token: str, broker: H.AmqttBroker, rtsp: H.RtspStand | None,
                          c: Counters, stop: asyncio.Event, t0: float) -> None:
    hdr = {"Authorization": f"Bearer {admin_token}"}
    state = {"mqtt": False, "rtsp": False, "ui": False}
    async with httpx.AsyncClient(base_url=base, verify=False, timeout=60, headers=hdr) as cl:
        while not stop.is_set():
            el = time.time() - t0
            want_mqtt_down = 300 <= el % 600 < 360
            want_rtsp_down = rtsp is not None and 450 <= el % 900 < 480
            want_ui = 900 <= el % 1200 < 930
            if want_mqtt_down != state["mqtt"]:
                state["mqtt"] = want_mqtt_down
                await asyncio.to_thread(broker.stop if want_mqtt_down else broker.start)
                c.faults.append({"t": round(el, 1), "fault": "mqtt_broker", "down": want_mqtt_down})
            if want_rtsp_down != state["rtsp"] and rtsp is not None:
                state["rtsp"] = want_rtsp_down
                await asyncio.to_thread(rtsp.stop_publisher if want_rtsp_down else rtsp.start_publisher)
                c.faults.append({"t": round(el, 1), "fault": "rtsp_publisher", "down": want_rtsp_down})
            if want_ui != state["ui"]:
                state["ui"] = want_ui
                await api_call(cl, c, "POST", "/api/architecture/outage", json={"active": want_ui})
                await api_call(cl, c, "POST", "/api/architecture/degrade",
                               json={"stream_id": "edge-bench-ta2t02", "mode": "steam" if want_ui else "recover"})
                c.faults.append({"t": round(el, 1), "fault": "ui_outage_and_steam", "down": want_ui})
            await asyncio.sleep(1.0)
        if state["mqtt"]:
            await asyncio.to_thread(broker.start)
        if state["rtsp"] and rtsp is not None:
            await asyncio.to_thread(rtsp.start_publisher)
        if state["ui"]:
            await api_call(cl, c, "POST", "/api/architecture/outage", json={"active": False})


def server_process(pid: int) -> psutil.Process:
    """Процесс интерпретатора сервера: python.exe из venv на Windows — лаунчер, сервер работает
    в дочернем процессе базового интерпретатора; берётся потомок с наибольшей памятью."""
    root = psutil.Process(pid)
    kids = [k for k in root.children(recursive=True) if "python" in k.name().lower()]
    return max(kids, key=lambda k: k.memory_info().rss) if kids else root


def proc_metrics(p: psutil.Process) -> dict[str, Any]:
    with p.oneshot():
        mi = p.memory_info()
        conns = p.net_connections(kind="tcp")
        return {
            "rss_mb": round(mi.rss / 1048576.0, 1),
            "private_mb": round(getattr(mi, "private", mi.vms) / 1048576.0, 1),
            "threads": p.num_threads(),
            "handles": p.num_handles() if hasattr(p, "num_handles") else p.num_fds(),
            "tcp_conns": len(conns),
            "tcp_established": sum(1 for x in conns if x.status == psutil.CONN_ESTABLISHED),
            "remote_non_loopback": sorted({f"{x.raddr.ip}:{x.raddr.port}" for x in conns
                                           if x.raddr and not x.raddr.ip.startswith(("127.", "::1"))}),
            "cpu_pct": p.cpu_percent(interval=None),
        }


async def sampler(server: H.GaugeServer, base: str, token: str, c: Counters, sub: H.MqttSubscriber,
                  out: Path, stop: asyncio.Event, t0: float, samples: list[dict[str, Any]]) -> None:
    d = server.data_dir
    jl = out / "samples.jsonl"
    hdr = {"Authorization": f"Bearer {token}"}
    sp = server_process(server.pid)
    sp.cpu_percent(interval=None)
    meta_pid = {"launcher_pid": server.pid, "server_pid": sp.pid}
    (out / "server_process.json").write_text(json.dumps(meta_pid), encoding="utf-8")
    async with httpx.AsyncClient(base_url=base, verify=False, timeout=60, headers=hdr) as cl:
        while not stop.is_set():
            await asyncio.sleep(SAMPLE_S)
            el = round(time.time() - t0, 1)
            rec: dict[str, Any] = {"t": el, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            try:
                rec["server_alive"] = server.proc is not None and server.proc.poll() is None
                rec.update(proc_metrics(sp))
                lat = []
                for _ in range(5):
                    t = time.perf_counter()
                    await cl.get("/api/health")
                    lat.append((time.perf_counter() - t) * 1000.0)
                rec["health_lat_ms_p50"] = round(statistics.median(lat), 1)
                rec["health_lat_ms_max"] = round(max(lat), 1)
                st = (await cl.get("/api/architecture/status")).json()
                rec["streams"] = {s["id"][:18]: {"status": s["status"], "health": s["health_status"], "fps": s["fps"],
                                                 "inf_ms": s["inference_ms"], "frames": s["frames_total"],
                                                 "mode": (s.get("adaptive") or {}).get("mode"),
                                                 "clips": (s.get("ring_buffer") or {}).get("persisted_clips")}
                                  for s in st["streams"]}
                sf = st["store_forward"]
                rec["sf"] = {k: sf[k] for k in ("pending_count", "pending_alarms", "delivered_total", "db_size_mb",
                                                "evicted_total", "queue_overflow", "sync_state", "max_retries")}
                mq = st["scada"]["mqtt"]
                rec["mqtt"] = {k: mq[k] for k in ("connected", "broker_sent", "puback_received", "publish_failures", "reconnects")}
            except Exception as exc:
                rec["sample_error"] = f"{type(exc).__name__}: {exc}"[:300]
            rec["sqlite_mb"] = {
                "main": fsize(d / "gaugevision.db"), "main_wal": fsize(d / "gaugevision.db-wal"),
                "sf": fsize(d / "store_forward.db"), "sf_wal": fsize(d / "store_forward.db-wal"),
            }
            rec["rows"] = {
                "readings": sqlite_count(d / "gaugevision.db", "SELECT COUNT(*) FROM readings"),
                "instrument_readings": sqlite_count(d / "gaugevision.db", "SELECT COUNT(*) FROM instrument_readings"),
                "events": sqlite_count(d / "gaugevision.db", "SELECT COUNT(*) FROM events"),
                "sf_queue": sqlite_count(d / "store_forward.db", "SELECT COUNT(*) FROM sf_queue"),
                "sf_blob_mb": round((sqlite_count(d / "store_forward.db", "SELECT COALESCE(SUM(LENGTH(frame_blob)),0) FROM sf_queue") or 0) / 1048576.0, 3),
            }
            rec["incident_files"], rec["incident_mb"] = dir_stats(d / "incidents")
            rec["auto_spec_files"], _ = dir_stats(d / "auto_specs")
            log = server.log_path.read_text(encoding="utf-8", errors="replace") if server.log_path.is_file() else ""
            rec["log_errors"] = log.count(" ERROR ") + log.count("Traceback")
            rec["clients"] = {"ws_msgs": c.ws_msgs, "ws_reconnects": c.ws_reconnects, "sse_events": c.sse_events,
                              "phone_frames": c.phone_frames, "phone_errors": c.phone_errors,
                              "api_calls": c.api_calls, "api_errors": len(c.api_errors), "keepalive_retries": c.keepalive_retries,
                              "api_lat_p95_ms": round(sorted(c.api_lat_ms)[int(len(c.api_lat_ms) * 0.95)], 1) if c.api_lat_ms else None,
                              "specs_preview": c.specs_preview, "docx_ok": c.docx_ok, "docx_bad": c.docx_bad,
                              "mqtt_received": len(sub.messages()) if sub.out.is_file() else 0}
            c.api_lat_ms.clear()
            samples.append(rec)
            with open(jl, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[soak t={el:7.1f}] rss={rec.get('rss_mb')}MB thr={rec.get('threads')} h={rec.get('handles')} "
                  f"pend={rec.get('sf', {}).get('pending_count')} rows={rec['rows']['readings']} "
                  f"lat={rec.get('health_lat_ms_p50')}ms err={rec['log_errors']}", flush=True)


def analyze(samples: list[dict[str, Any]], c: Counters, recon: dict[str, Any], duration: float) -> dict[str, Any]:
    ok = [s for s in samples if "rss_mb" in s]
    warm = [s for s in ok if s["t"] >= min(600.0, duration * 0.25)]  # после прогрева
    xs = [s["t"] / 3600.0 for s in warm]
    rss_slope = linreg_slope(xs, [s["rss_mb"] for s in warm])
    thr_slope = linreg_slope(xs, [s["threads"] for s in warm])
    hnd_slope = linreg_slope(xs, [s["handles"] for s in warm])
    tcp_slope = linreg_slope(xs, [s["tcp_conns"] for s in warm])
    lat_first = statistics.median([s["health_lat_ms_p50"] for s in warm[: max(1, len(warm) // 4)]]) if warm else None
    lat_last = statistics.median([s["health_lat_ms_p50"] for s in warm[-max(1, len(warm) // 4):]]) if warm else None
    per_stream: dict[str, dict[str, Any]] = {}
    for s in warm:
        for sid, v in (s.get("streams") or {}).items():
            ps = per_stream.setdefault(sid, {"fps": [], "inf": [], "online": 0, "n": 0, "frames_first": v["frames"]})
            ps["fps"].append(v["fps"] or 0.0)
            if v["inf_ms"]:
                ps["inf"].append(v["inf_ms"])
            ps["online"] += 1 if v["status"] == "online" else 0
            ps["n"] += 1
            ps["frames_last"] = v["frames"]
    streams = {sid: {"fps_median": round(statistics.median(v["fps"]), 2), "fps_min": round(min(v["fps"]), 2),
                     "inference_ms_median": round(statistics.median(v["inf"]), 1) if v["inf"] else None,
                     "online_share": round(v["online"] / v["n"], 3),
                     "frames_progress": (v.get("frames_last") or 0) - (v.get("frames_first") or 0)}
               for sid, v in per_stream.items()}
    pend = [s["sf"]["pending_count"] for s in ok if "sf" in s]
    remote = sorted({r for s in ok for r in s.get("remote_non_loopback", [])})
    rows = [s["rows"]["readings"] for s in ok if s["rows"]["readings"] is not None]
    ev = [s["rows"]["events"] for s in ok if s["rows"]["events"] is not None]
    last = ok[-1] if ok else {}
    crit = {
        "server_alive_whole_run": all(s.get("server_alive") for s in samples),
        "rss_growth_mb_per_h_below_50": rss_slope < 50.0,
        "threads_stable": bool(warm) and abs(warm[-1]["threads"] - warm[0]["threads"]) <= 10,
        "handles_stable": hnd_slope < 200.0,
        "tcp_connections_stable": bool(warm) and abs(warm[-1]["tcp_conns"] - warm[0]["tcp_conns"]) <= 10,
        "api_latency_no_degradation": (lat_last is not None and lat_first is not None and lat_last <= max(50.0, lat_first * 2.0)),
        "all_cv_streams_progressing": bool(streams) and all(v["frames_progress"] > 0 for v in streams.values()),
        "sf_queue_drains": bool(pend) and pend[-1] <= 20,
        "sf_blob_bytes_not_accumulating": (last.get("rows", {}).get("sf_blob_mb") or 0.0) < 5.0,
        "readings_persisted_monotonic": bool(rows) and all(b >= a for a, b in zip(rows, rows[1:])) and rows[-1] > rows[0],
        "events_persisted": bool(ev) and ev[-1] > ev[0],
        "no_server_log_errors": (last.get("log_errors") or 0) == 0,
        "no_api_errors": len(c.api_errors) == 0,
        "docx_generated_valid": c.docx_ok >= int(duration // 600) and c.docx_bad == 0,
        "mqtt_no_loss": recon.get("sent_but_not_received") == 0,
        "no_external_connections": not remote,
    }
    return {
        "duration_s": duration,
        "samples": len(samples),
        "rss_mb": {"start": ok[0]["rss_mb"] if ok else None, "end": last.get("rss_mb"),
                   "max": max((s["rss_mb"] for s in ok), default=None), "slope_mb_per_h_after_warmup": round(rss_slope, 2)},
        "threads": {"start": ok[0]["threads"] if ok else None, "end": last.get("threads"), "slope_per_h": round(thr_slope, 2)},
        "handles": {"start": ok[0]["handles"] if ok else None, "end": last.get("handles"), "slope_per_h": round(hnd_slope, 1)},
        "tcp_conns": {"start": ok[0]["tcp_conns"] if ok else None, "end": last.get("tcp_conns"), "slope_per_h": round(tcp_slope, 2)},
        "health_latency_p50_ms": {"first_quarter": lat_first, "last_quarter": lat_last},
        "streams": streams,
        "sf_pending": {"max": max(pend, default=None), "end": pend[-1] if pend else None},
        "rows": {"readings_end": rows[-1] if rows else None, "events_end": ev[-1] if ev else None},
        "sqlite_mb_end": last.get("sqlite_mb"),
        "incident_files_end": last.get("incident_files"),
        "clients": last.get("clients"),
        "faults": c.faults,
        "api_errors_sample": c.api_errors[:20],
        "remote_non_loopback_connections": remote,
        "mqtt_reconciliation": recon,
        "criteria": crit,
        "passed": all(crit.values()),
    }


async def run(out: Path) -> int:
    tools = H.load_tools()
    work = Path(tempfile.mkdtemp(prefix="gv_soak_"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "samples.jsonl").unlink(missing_ok=True)
    rtsp_video = H.make_gauge_video(work / "rtsp.mp4", [(10.0, 9.0), (10.0, 12.5)], fps=10)
    rtsp = H.RtspStand(tools, work / "rtsp", rtsp_video) if tools.get("mediamtx") and tools.get("ffmpeg") else None
    broker = H.AmqttBroker(tools, work / "mqtt")
    sub = H.MqttSubscriber(tools, broker.port, work / "mqtt" / "received.jsonl")
    server = H.GaugeServer(work / "server", extra_env={
        "GAUGEVISION_MQTT_ENABLED": "1", "GAUGEVISION_MQTT_HOST": "127.0.0.1",
        "GAUGEVISION_MQTT_PORT": str(broker.port), "GAUGEVISION_MQTT_ACK_TIMEOUT": "2.0",
        "GAUGEVISION_MQTT_KEEPALIVE": "10", "GAUGEVISION_MODBUS_ENABLED": "1",
        "GAUGEVISION_MODBUS_HOST": "127.0.0.1", "GAUGEVISION_MODBUS_PORT": str(H.free_port()),
        "GAUGEVISION_ALLOW_LOOPBACK_STREAMS": "1",
    })
    c = Counters()
    samples: list[dict[str, Any]] = []
    stop = asyncio.Event()
    summary: dict[str, Any] = {}
    meta = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "duration_target_s": DURATION,
            "sample_s": SAMPLE_S, "device": "cpu", "rtsp": rtsp is not None}
    try:
        if rtsp:
            rtsp.start_server()
            rtsp.start_publisher()
        broker.start()
        sub.start()
        # видеофайл стенда в разрешённом каталоге data/videos сервера
        H.make_gauge_video(server.data_dir / "videos" / "bench_loop.mp4", [(20.0, 10.0), (5.0, 15.6), (20.0, 11.0)], fps=8)
        server.start()
        meta["server_pid"] = server.pid
        eng = H.Api(server.base, "engineer", H.ENGINEER_PASS)
        adm = H.Api(server.base, "admin", H.ADMIN_PASS)
        opr = H.Api(server.base, "operator", H.OPERATOR_PASS)
        if rtsp:
            r = eng.post("/api/cameras", {"name": "Soak RTSP", "type": "rtsp", "source_url": rtsp.view_url,
                                          "calibration": H.CALIBRATION, "thresholds": H.THRESHOLDS})
            assert r.status_code == 201, r.text
        r = eng.post("/api/cameras", {"name": "Soak видеофайл", "type": "video_file", "source_url": "bench_loop.mp4",
                                      "calibration": H.CALIBRATION, "thresholds": H.THRESHOLDS})
        assert r.status_code == 201, r.text
        sess = eng.post("/api/phone/session", {}).json()
        base_wss = server.base.replace("https://", "wss://")
        t0 = time.time()
        tasks = [
            asyncio.create_task(ws_dashboard(base_wss, opr.token, c, stop)),
            asyncio.create_task(ws_dashboard(base_wss, adm.token, c, stop)),
            asyncio.create_task(sse_client(server.base, opr.token, c, stop)),
            asyncio.create_task(phone_client(base_wss, sess["cam_id"], sess["token"], c, stop, t0)),
            asyncio.create_task(hmi_poller(server.base, eng.token, c, stop, t0)),
            asyncio.create_task(fault_scheduler(server.base, adm.token, broker, rtsp, c, stop, t0)),
            asyncio.create_task(sampler(server, server.base, adm.token, c, sub, out, stop, t0, samples)),
        ]
        while time.time() - t0 < DURATION:
            await asyncio.sleep(5.0)
            if server.proc is None or server.proc.poll() is not None:
                print("[soak] процесс сервера завершился досрочно", flush=True)
                break
            (out / "progress.json").write_text(json.dumps({**meta, "elapsed_s": round(time.time() - t0, 1),
                                                           "samples": len(samples), "status": "running"},
                                                          ensure_ascii=False), encoding="utf-8")
        elapsed = round(time.time() - t0, 1)
        stop.set()
        await asyncio.wait(tasks, timeout=90)
        # досылка после последнего окна отказа и сверка MQTT
        t_d = time.time()
        while time.time() - t_d < 120 and adm.get("/api/architecture/store-forward")["pending_count"] > 0:
            time.sleep(2)
        time.sleep(4)
        sf_db = server.data_dir / "store_forward.db"
        con = sqlite3.connect(f"file:{sf_db}?mode=ro", uri=True)
        rows = con.execute("SELECT event_uuid, status FROM sf_queue").fetchall()
        con.close()
        got: dict[str, int] = {}
        for m in sub.messages():
            if m.get("event_uuid") and not m["topic"].endswith("/frame"):
                got[m["event_uuid"]] = got.get(m["event_uuid"], 0) + 1
        sent = [u for u, s in rows if s == "sent"]
        recon = {"sf_rows": len(rows), "sent": len(sent), "pending": sum(1 for _, s in rows if s == "pending"),
                 "received_unique": len(got), "sent_but_not_received": sum(1 for u in sent if u not in got),
                 "duplicates": sum(v - 1 for v in got.values() if v > 1)}
        summary = analyze(samples, c, recon, elapsed)
        eng.close()
        adm.close()
        opr.close()
    except Exception:
        summary["exception"] = traceback.format_exc()[-3000:]
        summary["passed"] = False
    finally:
        stop.set()
        rc = server.stop()
        log = server.log_path.read_text(encoding="utf-8", errors="replace") if server.log_path.is_file() else ""
        summary["server_exit_code"] = rc
        summary["graceful_shutdown_logged"] = "Application shutdown complete" in log
        sub.stop()
        broker.stop()
        if rtsp:
            rtsp.stop()
        for p in (server.log_path, work / "mqtt" / "amqtt_broker.log"):
            if p.is_file():
                tail = p.read_text(encoding="utf-8", errors="replace")[-400_000:]
                (out / p.name).write_text(tail, encoding="utf-8")
    summary["meta"] = {**meta, "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "progress.json").write_text(json.dumps({**meta, "status": "completed", "passed": summary.get("passed")},
                                                  ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary.get("criteria", summary), ensure_ascii=False, indent=2))
    print("SOAK PASSED" if summary.get("passed") else "SOAK FAILED")
    return 0 if summary.get("passed") else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(H.ROOT / "reports" / "remediation" / "evidence" / "soak"))
    args = ap.parse_args()
    return asyncio.run(run(Path(args.out)))


if __name__ == "__main__":
    sys.exit(main())
