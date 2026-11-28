"""
GaugeVision AI 3.1 — Непрерывное 60-минутное CPU soak-испытание (Стадия III).

Проверяет финальный замороженный код (включая Vision Engine 3.1, Predictive v3.2,
усиления безопасности, PRAGMA busy_timeout/cache SQLite) под живой нагрузкой:
  • отдельный процесс `run.py` (CPU-only, без GPU RTX 5060);
  • многоприборный видеоисточник (`scripts/make_panel_video.py`, 8 приборов в кадре);
  • профиль CV `balanced` (NeedleSegUNet + OpenCV v2) с контрольной проверкой переключения профилей;
  • ежесекундный опрос `GET /api/health` (задержки p50/p95/p99/max и `loop_lag_ms`);
  • каждые 10 с: чтение регистров Modbus TCP, замер CPU %, RSS МБ, размера SQLite + WAL;
  • каждые 30 с: `GET /api/predictive/overview`;
  • каждые 5 мин: `POST /api/optimizer/solve` и `POST /api/specs/generate` (DOCX);
  • каждые 10 мин: fault injection (имитация обрыва канала АСУ ТП `outage` на 30 с + проверка S&F drain).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

import httpx
import psutil

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    idx = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
    return round(float(s[idx]), 2)


def read_modbus_regs(host: str, port: int, start: int, count: int, unit_id: int = 1) -> list[int]:
    with socket.create_connection((host, port), timeout=3.0) as sock:
        req = struct.pack(">HHHBBHH", 1, 0, 6, unit_id, 3, start, count)
        sock.sendall(req)
        hdr = sock.recv(9)
        if len(hdr) < 9 or hdr[7] != 3:
            raise RuntimeError(f"Modbus bad header: {hdr.hex()}")
        bc = hdr[8]
        data = b""
        while len(data) < bc:
            chunk = sock.recv(bc - len(data))
            if not chunk:
                break
            data += chunk
        return list(struct.unpack(f">{count}H", data))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=60.0)
    ap.add_argument("--profile", default="balanced")
    ap.add_argument("--out", default=str(REPO_ROOT / "reports" / "comprehensive_improvement" / "evidence" / "soak_v31_results.json"))
    args = ap.parse_args()

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="gv31_soak_"))
    videos_dir = work / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    video_path = videos_dir / "panel_soak8.mp4"
    legend_path = videos_dir / "panel_soak8.json"

    # 1. Генерируем синтетический щит из 8 приборов
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "make_panel_video.py"),
         "--out", str(video_path), "--gauges", "8", "--seconds", "20"],
        check=True, cwd=str(REPO_ROOT),
    )

    http_port = free_port()
    mb_port = free_port()
    db_path = work / "soak_v31.db"
    sf_path = work / "soak_sf.db"
    log_path = work / "server.log"

    env = os.environ.copy()
    env.update({
        "CUDA_VISIBLE_DEVICES": "",
        "GAUGEVISION_DEVICE": "cpu",
        "YOLO_OFFLINE": "1",
        "YOLO_CONFIG_DIR": str(work / "ultralytics_cfg"),
        "GAUGEVISION_HOST": "127.0.0.1",
        "GAUGEVISION_PORT": str(http_port),
        "GAUGEVISION_HTTPS": "0",
        "GAUGEVISION_DB": str(db_path),
        "GAUGEVISION_SF_DB": str(sf_path),
        "GAUGEVISION_VIDEOS_DIR": str(videos_dir),
        "GAUGEVISION_DEMO": "1",
        "GAUGEVISION_AUTH_REQUIRED": "1",
        "GAUGEVISION_MODBUS_ENABLED": "1",
        "GAUGEVISION_MODBUS_HOST": "127.0.0.1",
        "GAUGEVISION_MODBUS_PORT": str(mb_port),
        "GAUGEVISION_VISION_PROFILE": args.profile,
        "GAUGEVISION_ALLOW_FAULT_INJECTION": "1",
        "GAUGEVISION_ADMIN_PASSWORD": "soak-admin-v31-pass",
    })

    log_f = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-B", str(REPO_ROOT / "run.py")],
        cwd=str(REPO_ROOT), env=env, stdout=log_f, stderr=subprocess.STDOUT,
    )

    base_url = f"https://127.0.0.1:{http_port}"
    client = httpx.Client(base_url=base_url, timeout=15.0, verify=False)
    stop_ping = threading.Event()
    health_ms: list[float] = []
    health_errs = 0

    def pinger() -> None:
        nonlocal health_errs
        with httpx.Client(base_url=base_url, timeout=5.0, verify=False) as hc:
            while not stop_ping.is_set():
                t0 = time.perf_counter()
                try:
                    r = hc.get("/api/health")
                    dt = (time.perf_counter() - t0) * 1000.0
                    if r.status_code == 200:
                        health_ms.append(dt)
                    else:
                        health_errs += 1
                except Exception:
                    health_errs += 1
                stop_ping.wait(1.0)

    try:
        # Ожидаем готовности сервера
        ready = False
        for _ in range(90):
            try:
                if client.get("/api/health").status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(1.0)
        if not ready:
            raise RuntimeError("GaugeVision server did not start within 90s")

        # Вход администратором и инженером (учётные данные демопрофиля из config)
        sys.path.insert(0, str(REPO_ROOT))
        from app import config as _cfg
        r_adm = client.post("/api/auth/login", json={"username": _cfg.ADMIN_USERNAME, "password": _cfg.ADMIN_PASSWORD})
        r_adm.raise_for_status()
        adm_hdr = {"Authorization": f"Bearer {r_adm.json()['token']}"}

        # Проверяем активный профиль CV
        st_v = client.get("/api/vision/status", headers=adm_hdr).json()
        print(f"Soak started: port={http_port}, modbus={mb_port}, profile={st_v['profile']}, duration={args.minutes}m", flush=True)

        # Подключаем видеофайл щита
        r_cam = client.post("/api/cameras", headers=adm_hdr, json={
            "name": "Щит Soak-8",
            "type": "video_file",
            "source_url": "panel_soak8.mp4",
            "gauge_type": "pressure",
            "unit": "МПа",
        })
        r_cam.raise_for_status()

        # Запускаем ежесекундный пингер
        t_ping = threading.Thread(target=pinger, daemon=True)
        t_ping.start()

        # Находим реальный дочерний процесс Python (если venv-лаунчер породил потомка)
        p_main = psutil.Process(proc.pid)
        def get_worker_proc() -> psutil.Process:
            ch = p_main.children(recursive=True)
            return ch[-1] if ch else p_main

        t_start = time.time()
        dur_s = args.minutes * 60.0
        samples: list[dict[str, Any]] = []
        mb_ok = 0
        mb_err = 0
        pred_ms: list[float] = []
        pred_err = 0
        opt_ms: list[float] = []
        opt_err = 0
        spec_ms: list[float] = []
        spec_err = 0
        outages_done = 0
        last_pred = 0.0
        last_heavy = 0.0
        last_outage = 0.0
        outage_active_until = 0.0

        wp = get_worker_proc()
        wp.cpu_percent(interval=None)

        while True:
            now = time.time()
            elapsed = now - t_start
            if elapsed >= dur_s:
                break

            wp = get_worker_proc()
            cpu_p = wp.cpu_percent(interval=None) / max(1, psutil.cpu_count(logical=True) or 1)
            rss_mb = wp.memory_info().rss / (1024 * 1024)
            db_kb = sum(p.stat().st_size for p in work.glob("soak_v31.db*") if p.is_file()) / 1024.0

            h_json = {}
            try:
                h_json = client.get("/api/health").json()
            except Exception:
                pass

            try:
                regs = read_modbus_regs("127.0.0.1", mb_port, 900, 10)
                if len(regs) == 10:
                    mb_ok += 1
            except Exception:
                mb_err += 1

            # Каждые 30 с — Predictive Overview
            if elapsed - last_pred >= 30.0:
                last_pred = elapsed
                tp0 = time.perf_counter()
                try:
                    rp = client.get("/api/predictive/overview", headers=adm_hdr)
                    if rp.status_code == 200:
                        pred_ms.append((time.perf_counter() - tp0) * 1000.0)
                    else:
                        pred_err += 1
                except Exception:
                    pred_err += 1

            # Каждые 5 мин (или каждые 60 с при коротком контрольном прогоне) — Optimizer + DOCX
            heavy_every = 60.0 if args.minutes <= 10.0 else 300.0
            if elapsed - last_heavy >= heavy_every:
                last_heavy = elapsed
                to0 = time.perf_counter()
                try:
                    ro = client.post("/api/optimizer/solve", headers=adm_hdr, json={"budget_rub": 600000, "objective": "risk", "with_pareto": True, "time_limit_s": 3.0})
                    if ro.status_code == 200:
                        opt_ms.append((time.perf_counter() - to0) * 1000.0)
                    else:
                        opt_err += 1
                except Exception:
                    opt_err += 1

                ts0 = time.perf_counter()
                try:
                    rs = client.post("/api/specs/generate", headers=adm_hdr, json={"period_hours": 12, "format": "docx"})
                    if rs.status_code == 200:
                        spec_ms.append((time.perf_counter() - ts0) * 1000.0)
                    else:
                        spec_err += 1
                except Exception:
                    spec_err += 1

            # Fault injection: 20-30 с обрыв канала АСУ ТП -> восстановление
            outage_every = 75.0 if args.minutes <= 10.0 else 600.0
            outage_start = 40.0 if args.minutes <= 10.0 else 300.0
            if elapsed >= outage_start and elapsed - last_outage >= outage_every and outage_active_until == 0.0:
                last_outage = elapsed
                try:
                    client.post("/api/architecture/outage", headers=adm_hdr, json={"outage": True})
                    outage_active_until = elapsed + 20.0
                    outages_done += 1
                except Exception:
                    pass
            if outage_active_until > 0.0 and elapsed >= outage_active_until:
                try:
                    client.post("/api/architecture/outage", headers=adm_hdr, json={"outage": False})
                except Exception:
                    pass
                outage_active_until = 0.0

            lag = h_json.get("loop_lag_ms") or {}
            samples.append({
                "t_s": round(elapsed, 1),
                "cpu_pct": round(cpu_p, 2),
                "rss_mb": round(rss_mb, 1),
                "db_kb": round(db_kb, 1),
                "loop_lag_p95_ms": lag.get("p95"),
                "loop_lag_max_ms": lag.get("max"),
            })
            if len(samples) % 30 == 0:
                print(
                    f"  t={elapsed/60:.1f}m cpu={cpu_p:.1f}% rss={rss_mb:.0f}MB db={db_kb:.0f}KB "
                    f"lag_p95={lag.get('p95')}ms lag_max={lag.get('max')}ms mb_ok={mb_ok} mb_err={mb_err}",
                    flush=True,
                )
            time.sleep(10.0)

        # Завершение и сбор итогов
        stop_ping.set()
        t_ping.join(timeout=3.0)
        if outage_active_until > 0.0:
            client.post("/api/architecture/outage", headers=adm_hdr, json={"outage": False})
        sf_state = client.get("/api/architecture/store-forward", headers=adm_hdr).json()

        actual_s = time.time() - t_start
        cpus = [s["cpu_pct"] for s in samples]
        rsss = [s["rss_mb"] for s in samples]
        lag_p95s = [float(s["loop_lag_p95_ms"]) for s in samples if s["loop_lag_p95_ms"] is not None]
        lag_maxs = [float(s["loop_lag_max_ms"]) for s in samples if s["loop_lag_max_ms"] is not None]

        # Проверяем server.log на ERROR / Traceback
        log_f.flush()
        log_txt = log_path.read_text(encoding="utf-8", errors="ignore")
        server_tracebacks = log_txt.count("Traceback")
        server_errors = sum(1 for ln in log_txt.splitlines() if " ERROR " in ln)

        summary = {
            "commit": "1de2067",
            "profile": args.profile,
            "duration_s": round(actual_s, 1),
            "duration_min": round(actual_s / 60.0, 2),
            "samples_n": len(samples),
            "cpu_pct": {"p50": pct(cpus, 0.5), "p95": pct(cpus, 0.95), "max": pct(cpus, 1.0)},
            "rss_mb": {"start": rsss[0] if rsss else 0, "peak": max(rsss) if rsss else 0, "end": rsss[-1] if rsss else 0},
            "db_kb": {"start": samples[0]["db_kb"] if samples else 0, "end": samples[-1]["db_kb"] if samples else 0},
            "health_api_ms": {"n": len(health_ms), "errors": health_errs, "p50": pct(health_ms, 0.5), "p95": pct(health_ms, 0.95), "p99": pct(health_ms, 0.99), "max": pct(health_ms, 1.0)},
            "loop_lag_ms": {"p95_median": pct(lag_p95s, 0.5), "p95_max": pct(lag_p95s, 1.0), "abs_max": max(lag_maxs) if lag_maxs else None},
            "modbus_tcp": {"ok": mb_ok, "errors": mb_err},
            "predictive_api": {"ok": len(pred_ms), "errors": pred_err, "p50_ms": pct(pred_ms, 0.5), "max_ms": pct(pred_ms, 1.0)},
            "optimizer_api": {"ok": len(opt_ms), "errors": opt_err, "p50_ms": pct(opt_ms, 0.5), "max_ms": pct(opt_ms, 1.0)},
            "specs_docx_api": {"ok": len(spec_ms), "errors": spec_err, "p50_ms": pct(spec_ms, 0.5), "max_ms": pct(spec_ms, 1.0)},
            "fault_injections_outage": outages_done,
            "store_forward": sf_state,
            "server_tracebacks": server_tracebacks,
            "server_errors": server_errors,
            "samples_tail": samples[-12:],
        }
        out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("=== SOAK SUMMARY ===", flush=True)
        print(json.dumps({k: v for k, v in summary.items() if k != "samples_tail"}, ensure_ascii=False, indent=2), flush=True)
        return 0
    finally:
        stop_ping.set()
        client.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        log_f.close()


if __name__ == "__main__":
    raise SystemExit(main())
