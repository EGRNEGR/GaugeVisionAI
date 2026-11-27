"""
Непрерывное испытание объединённой системы (не менее 60 мин, CPU): видеопотоки Multi-Gauge, прогнозная
аналитика, оптимизатор и генерация DOCX, Modbus TCP и MQTT, периодические отказы брокера.

Источники — синтетические видео щитов (scripts/make_panel_video.py), не видео объекта.

    python run_soak.py --videos a.mp4 b.mp4 --work <каталог> --amqtt <amqtt.exe> --tools-py <python> --minutes 60
                       [--mediamtx mediamtx.exe --ffmpeg ffmpeg.exe]

С --mediamtx второй видеофайл публикуется ffmpeg в RTSP-сервер mediamtx (с аутентификацией) и подключается
как источник rtsp; издатель останавливается на 20 с каждые 15 мин — проверка переподключения.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))
import run_e2e as E  # noqa: E402


def q(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    v = sorted(vals)
    return round(v[min(len(v) - 1, int(p * (len(v) - 1)))], 2)


def register_all(eng: httpx.Client, op: httpx.Client, sid: str, legend: dict[str, Any]) -> dict[str, dict[str, Any]]:
    det = E.wait_for(lambda: (lambda d: d if d.status_code == 200 and len(d.json()["candidates"]) >= len(legend["gauges"])
                              else None)(eng.post(f"/api/sources/{sid}/instruments/detect")), 120, 2.0)
    if det is None:
        raise RuntimeError(f"детектор не нашёл все приборы источника {sid}")
    d = det.json()
    fw, fh = d["frame"]["w"], d["frame"]["h"]
    own = {}
    for c in d["candidates"]:
        ax, ay = c["anchor"]["cx"], c["anchor"]["cy"]
        if ax > 1.5:
            ax, ay = ax / fw, ay / fh
        g = min(legend["gauges"], key=lambda g: math.hypot(g["cx"] - ax, g["cy"] - ay))
        gt = "temperature" if g["unit"] == "°C" else "pressure"
        if c["is_primary_dial"]:
            eng.patch(f"/api/cameras/{sid}", json={"name": g["code"], "unit": g["unit"], "gauge_type": gt,
                                                   "calibration": g["calibration"]})
            own[sid] = g
        else:
            r = eng.post(f"/api/sources/{sid}/instruments", json={"name": g["code"], "code": g["code"], "unit": g["unit"],
                                                                  "gauge_type": gt, "roi": c["anchor"],
                                                                  "calibration": g["calibration"]})
            if r.status_code == 201:
                own[r.json()["id"]] = g
    return own


class Rtsp:
    """RTSP-сервер mediamtx с аутентификацией и издатель ffmpeg (кольцевое воспроизведение файла, H.264)."""

    def __init__(self, mediamtx: str, ffmpeg: str, work: Path, video: Path) -> None:
        self.mediamtx, self.ffmpeg, self.work, self.video = mediamtx, ffmpeg, work, video
        self.port = E.free_port()
        self.url = f"rtsp://gvsoak:Soak-7351@127.0.0.1:{self.port}/panel"
        self.cfg = work / "mediamtx.yml"
        cfg_lines = ["logLevel: warn", f"rtspAddress: :{self.port}", "rtmp: no", "hls: no", "webrtc: no", "srt: no",
                     "api: no", "authInternalUsers:", "- user: gvsoak", "  pass: Soak-7351", "  ips: []",
                     "  permissions:", "  - action: publish", "  - action: read", "paths:", "  panel: {}"]
        self.cfg.write_text("\n".join(cfg_lines) + "\n", encoding="utf-8")
        self.srv: subprocess.Popen | None = None
        self.pub: subprocess.Popen | None = None

    def start_server(self) -> None:
        # cwd — рабочий каталог стенда: mediamtx создаёт там свои auto.crt / auto.key
        self.srv = subprocess.Popen([self.mediamtx, str(self.cfg)], stdout=open(self.work / "mediamtx.log", "a"),
                                    stderr=subprocess.STDOUT, cwd=str(self.work))
        time.sleep(2)

    def start_publisher(self) -> None:
        self.pub = subprocess.Popen(
            [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-re", "-stream_loop", "-1", "-i", str(self.video),
             "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "4", "-f", "rtsp",
             "-rtsp_transport", "tcp", self.url], stdout=open(self.work / "ffmpeg.log", "a"), stderr=subprocess.STDOUT)
        time.sleep(3)

    def stop_publisher(self) -> None:
        if self.pub:
            self.pub.kill()
            self.pub.wait(10)
            self.pub = None

    def stop(self) -> None:
        self.stop_publisher()
        if self.srv:
            self.srv.kill()
            self.srv.wait(10)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", nargs="+", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--amqtt", required=True)
    ap.add_argument("--tools-py", required=True)
    ap.add_argument("--minutes", type=float, default=60.0)
    ap.add_argument("--out", default=str(Path(__file__).with_name("soak_results.json")))
    ap.add_argument("--mediamtx", default=None)
    ap.add_argument("--ffmpeg", default=None)
    args = ap.parse_args()
    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    (work / "videos").mkdir(parents=True)
    legends = []
    for v in args.videos:
        shutil.copy(v, work / "videos" / Path(v).name)
        legends.append(json.loads(Path(v).with_suffix(".json").read_text(encoding="utf-8")))

    mqtt_port, http_port = E.free_port(), E.free_port()
    env = {**__import__("os").environ, "CUDA_VISIBLE_DEVICES": "", "GAUGEVISION_DEVICE": "cpu",
           "PYTHONIOENCODING": "utf-8", "GAUGEVISION_DEMO": "0", "GAUGEVISION_DB": str(work / "gv.db"),
           "GAUGEVISION_SF_DB": str(work / "sf.db"), "GAUGEVISION_VIDEOS_DIR": str(work / "videos"),
           "GAUGEVISION_INCIDENTS_DIR": str(work / "incidents"), "GAUGEVISION_AUTO_SPECS_DIR": str(work / "auto_specs"),
           "GAUGEVISION_LAN_IP": "127.0.0.1", "GAUGEVISION_ADMIN_PASS": E.PW["admin"],
           "GAUGEVISION_ENGINEER_PASS": E.PW["engineer"], "GAUGEVISION_OPERATOR_PASS": E.PW["operator"],
           "GAUGEVISION_MODBUS_ENABLED": "1", "GAUGEVISION_MODBUS_HOST": "127.0.0.1",
           "GAUGEVISION_MODBUS_PORT": "15020", "GAUGEVISION_MQTT_ENABLED": "1",
           "GAUGEVISION_MQTT_HOST": "127.0.0.1", "GAUGEVISION_MQTT_PORT": str(mqtt_port),
           "GAUGEVISION_MQTT_ACK_TIMEOUT": "2.0", "GAUGEVISION_ALLOW_LOOPBACK_STREAMS": "1"}
    rtsp = None
    if args.mediamtx and args.ffmpeg and len(args.videos) > 1:
        rtsp = Rtsp(args.mediamtx, args.ffmpeg, work, Path(args.videos[1]))
        rtsp.start_server()
        rtsp.start_publisher()
    broker = E.Broker(args.amqtt, work, mqtt_port)
    broker.start()
    rx = work / "mqtt_rx.jsonl"
    sink = subprocess.Popen([args.tools_py, str(Path(__file__).resolve().parents[1] / "e2e" / "mqtt_sink.py"),
                             str(mqtt_port), str(rx)], stdout=open(work / "sink.log", "w"), stderr=subprocess.STDOUT)
    server = E.Server(work, env, http_port)
    samples: list[dict[str, Any]] = []
    ops: list[dict[str, Any]] = []
    outages: list[dict[str, Any]] = []
    t0 = time.time()
    try:
        server.start()
        base = f"https://127.0.0.1:{http_port}"
        cli = {r: httpx.Client(base_url=base, verify=False, timeout=60) for r in E.PW}
        for r, c in cli.items():
            c.post("/api/auth/login", json={"username": r, "password": E.PW[r]})
        adm, eng, op = cli["admin"], cli["engineer"], cli["operator"]
        own: dict[str, dict[str, Any]] = {}
        for k, (v, lg) in enumerate(zip(args.videos, legends)):
            body = {"name": f"Щит {Path(v).stem} (синтетика)", "type": "video_file", "source_url": Path(v).name}
            if rtsp is not None and k == 1:
                body = {"name": f"Щит {Path(v).stem} по RTSP (синтетика)", "type": "rtsp", "source_url": rtsp.url}
            r = adm.post("/api/cameras", json=body)
            sid = r.json()["id"]
            E.wait_for(lambda: (lambda c: c and c[0]["status"] == "online")(
                [x for x in op.get("/api/cameras").json() if x["id"] == sid]), 60)
            own.update(register_all(eng, op, sid, lg))
        # python.exe из venv в Windows — лаунчер, сервис работает в дочернем интерпретаторе: меряем самый тяжёлый процесс
        root = psutil.Process(server.proc.pid)
        proc = max([root] + root.children(recursive=True), key=lambda p: p.memory_info().rss)
        proc.cpu_percent(None)
        n_cpu = psutil.cpu_count() or 1
        t_soak0 = time.time()
        end = t_soak0 + args.minutes * 60.0
        next_opt, next_pred, next_out, out_until = t_soak0 + 60, t_soak0 + 30, t_soak0 + 300, None
        next_pub, pub_until = t_soak0 + 450, None
        pub_events: list[dict[str, Any]] = []
        rtsp_id = next((c["id"] for c in op.get("/api/cameras").json() if c.get("type") == "rtsp"), None)
        frames_prev: dict[str, int] = {}
        t_prev = time.time()
        stop_ping = threading.Event()
        health_lat: list[float] = []

        def pinger() -> None:  # оперативный контур: /api/health и /api/instruments раз в секунду
            hc = httpx.Client(base_url=base, verify=False, timeout=10)
            while not stop_ping.is_set():
                t = time.perf_counter()
                try:
                    hc.get("/api/health")
                    health_lat.append((time.perf_counter() - t) * 1000)
                except Exception:  # noqa: BLE001
                    health_lat.append(10_000.0)
                time.sleep(1.0)
        threading.Thread(target=pinger, daemon=True).start()
        while time.time() < end:
            now = time.time()
            # отказ связи с брокером на 60 с каждые 10 мин (первый — на 5-й минуте)
            if out_until is None and now >= next_out:
                broker.stop()
                out_until = now + 60
                outages.append({"start": now - t_soak0})
            elif out_until is not None and now >= out_until:
                broker.start()
                outages[-1]["end"] = now - t_soak0
                out_until, next_out = None, now + 540
            if rtsp is not None and pub_until is None and now >= next_pub:
                rtsp.stop_publisher()
                pub_until = now + 20
                pub_events.append({"stop": now - t_soak0})
            elif rtsp is not None and pub_until is not None and now >= pub_until:
                rtsp.start_publisher()
                pub_events[-1]["start"] = now - t_soak0
                pub_until, next_pub = None, now + 900
            if now >= next_pred:
                t = time.perf_counter()
                r = op.get("/api/predictive/overview")
                ops.append({"op": "predictive_overview", "t": now - t_soak0, "ms": (time.perf_counter() - t) * 1000,
                            "http": r.status_code})
                next_pred = now + 30
            if now >= next_opt:
                t = time.perf_counter()
                r = eng.post("/api/optimizer/solve", json={"budget_rub": 600000, "objective": "weighted_utility",
                                                            "include_healthy": True, "include_frontier": True,
                                                            "time_limit_s": 3.0})
                ops.append({"op": "optimizer_solve", "t": now - t_soak0, "ms": (time.perf_counter() - t) * 1000,
                            "http": r.status_code, "status": r.json().get("status") if r.status_code == 200 else None})
                t = time.perf_counter()
                r = eng.post("/api/specs/generate", json={"period": "12h", "format": "docx"})
                ops.append({"op": "spec_docx", "t": now - t_soak0, "ms": (time.perf_counter() - t) * 1000,
                            "http": r.status_code, "bytes": len(r.content)})
                next_opt = now + 300
            # срез метрик каждые 10 с
            t = time.perf_counter()
            cams = op.get("/api/cameras").json()
            insts = op.get("/api/instruments").json()
            h = op.get("/api/health").json()
            sf = op.get("/api/architecture/store-forward").json()
            api_ms = (time.perf_counter() - t) * 1000
            dt = time.time() - t_prev
            t_prev = time.time()
            fps = {}
            for c in cams:
                ft = int((c.get("stream") or {}).get("frames_total") or 0)
                if c["id"] in frames_prev:  # первый отсчёт без предыдущего — не в статистику FPS
                    fps[c["id"][:8]] = round((ft - frames_prev[c["id"]]) / max(dt, 1e-3), 2)
                frames_prev[c["id"]] = ft
            mine = [x for x in insts if x["id"] in own]
            valid = sum(1 for x in mine if (x.get("reading") or {}).get("valid") and x.get("meas_state") == "valid")
            try:
                regs = E.modbus_read(0, 4 * 12)
                mb_ok = sum(1 for s in range(12) if regs[s * 4 + 2] in (0, 1, 2))
                mb_err = None
            except OSError as exc:
                mb_ok, mb_err = None, str(exc)
            mem = proc.memory_info()
            rtsp_status = next((c.get("status") for c in cams if c["id"] == rtsp_id), None)
            if pub_events and "start" in pub_events[-1] and "online_at" not in pub_events[-1] and rtsp_status == "online":
                pub_events[-1]["online_at"] = time.time() - t_soak0
            samples.append({"t": round(time.time() - t_soak0, 1), "cpu_pct": round(proc.cpu_percent(None) / n_cpu, 1),
                            "rtsp_status": rtsp_status,
                            "rss_mb": round(mem.rss / 2**20, 1), "threads": proc.num_threads(),
                            "fps": fps, "valid_instruments": valid, "instruments": len(mine),
                            "modbus_ok_slots": mb_ok, "modbus_error": mb_err, "api_snapshot_ms": round(api_ms, 1),
                            "loop_lag": h.get("loop_lag_ms"), "sf_pending": sf.get("pending_count"),
                            "sf_state": sf.get("sync_state"), "sf_evicted": sf.get("evicted_total"),
                            "broker_down": out_until is not None})
            time.sleep(max(0.0, 10.0 - (time.perf_counter() - t)))
        stop_ping.set()
        if out_until is not None:
            broker.start()
            outages[-1]["end"] = time.time() - t_soak0
        drained = E.wait_for(lambda: (op.get("/api/architecture/store-forward").json().get("pending_count") or 0) == 0,
                             180, 2.0)
        time.sleep(8)
        sf_end = op.get("/api/architecture/store-forward").json()
    finally:
        server.stop()
        broker.stop()
        sink.kill()
        if rtsp is not None:
            rtsp.stop()
    msgs = [json.loads(x) for x in rx.read_text(encoding="utf-8").splitlines() if x.strip()] if rx.exists() else []
    seqs = sorted({m["payload"].get("seq_id") for m in msgs if isinstance(m["payload"].get("seq_id"), int)})
    sfc = sqlite3.connect(str(work / "sf.db"))
    total_enq = sfc.execute("SELECT COUNT(*), MIN(seq_id), MAX(seq_id) FROM sf_queue").fetchone()
    sfc.close()
    gaps = [s for s in range(seqs[0], seqs[-1] + 1) if s not in set(seqs)] if seqs else []
    log_text = (work / "server.log").read_text(encoding="utf-8", errors="replace")
    errors = [ln for ln in log_text.splitlines() if " ERROR " in ln or "Traceback" in ln]
    lag_p95 = [s["loop_lag"]["p95"] for s in samples if s.get("loop_lag") and s["loop_lag"].get("p95") is not None]
    lag_max = [s["loop_lag"]["max"] for s in samples if s.get("loop_lag") and s["loop_lag"].get("max") is not None]
    fps_all = [v for s in samples for v in s["fps"].values()]
    res = {
        "synthetic_sources": True, "videos": [Path(v).name for v in args.videos], "minutes_planned": args.minutes,
        "duration_s": round(samples[-1]["t"], 1) if samples else 0, "samples": len(samples),
        "instruments": len(own), "outages": outages, "drained_after_end": bool(drained),
        "rtsp": {"used": rtsp is not None, "publisher_restarts": pub_events,
                 "reconnect_s": [round(e["online_at"] - e["start"], 1) for e in pub_events if "online_at" in e]},
        "summary": {
            "cpu_pct_of_machine": {"p50": q([s["cpu_pct"] for s in samples], .5), "p95": q([s["cpu_pct"] for s in samples], .95),
                                   "max": max(s["cpu_pct"] for s in samples)},
            "rss_mb": {"start": samples[0]["rss_mb"], "end": samples[-1]["rss_mb"], "max": max(s["rss_mb"] for s in samples),
                       "slope_mb_per_h": round((samples[-1]["rss_mb"] - samples[min(6, len(samples) - 1)]["rss_mb"])
                                               / max(1e-6, (samples[-1]["t"] - samples[min(6, len(samples) - 1)]["t"]) / 3600), 1)},
            "fps_per_source": {"p50": q(fps_all, .5), "p05": q(fps_all, .05), "min": min(fps_all) if fps_all else None},
            "health_latency_ms": {"p50": q(health_lat, .5), "p95": q(health_lat, .95), "p99": q(health_lat, .99),
                                  "max": max(health_lat) if health_lat else None, "n": len(health_lat)},
            "loop_lag_window_p95_ms": {"median": statistics.median(lag_p95) if lag_p95 else None, "max": max(lag_p95) if lag_p95 else None},
            "loop_lag_max_ms": max(lag_max) if lag_max else None,
            "valid_share": round(sum(s["valid_instruments"] for s in samples) / max(1, sum(s["instruments"] for s in samples)), 4),
            "modbus_errors": sum(1 for s in samples if s["modbus_error"]),
            "sf_pending_max": max((s["sf_pending"] or 0) for s in samples),
            "mqtt_messages": len(msgs), "mqtt_seq_range": [seqs[0], seqs[-1]] if seqs else None,
            "mqtt_seq_gaps": len(gaps), "sf_rows": total_enq[0], "sf_evicted": sf_end.get("evicted_total"),
            "server_errors": len(errors),
            "ops": {k: {"n": sum(1 for o in ops if o["op"] == k), "ok": sum(1 for o in ops if o["op"] == k and o["http"] == 200),
                        "p50_ms": q([o["ms"] for o in ops if o["op"] == k], .5),
                        "max_ms": round(max([o["ms"] for o in ops if o["op"] == k] or [0]), 1)}
                    for k in ("predictive_overview", "optimizer_solve", "spec_docx")},
        },
        "errors_excerpt": errors[:20], "ops": ops, "samples_series": samples,
    }
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
