"""
Проверка чистой автономной установки GaugeVision AI и отсутствия скрытых сетевых зависимостей.

  python reports/remediation/tests/offline_install_check.py --wheels <wheelhouse> \
      --base-python "C:\\Program Files\\Python312\\python.exe" --out reports/remediation/evidence/offline_install

Этапы:
  1. Новое venv; `pip install --no-index --find-links <wheels> -r requirements.lock` при
     неработающем прокси и PIP_NO_INDEX=1 (обращение к любому индексу невозможно).
  2. `pip check`, сверка установленного набора с requirements.lock.
  3. Наличие и контрольная сумма весов YOLOv8, наличие всех локальных статических ресурсов
     HMI, отсутствие внешних URL в загружаемых ресурсах.
  4. Запуск `run.py --demo` из нового venv с аудит-хуком Python (sitecustomize): каждая
     попытка DNS-разрешения/подключения к нелокальному адресу пишется в журнал со стеком.
  5. Проверка работы: YOLOv8 на CPU, CV-инференс стендовых каналов, HMI и статика, SQLite
     (отсчёты, события), аналитика (36 приборов), генерация .docx, Modbus TCP.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gv_harness as H  # noqa: E402

SITECUSTOMIZE = r'''
import json, os, sys, threading, traceback
_OUT = os.environ.get("GV_NET_AUDIT")
_LOCK = threading.Lock()
_EVENTS = {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.gethostbyname", "urllib.Request"}

def _is_local(host):
    h = str(host or "")
    return h in ("", "localhost", "::1", "0.0.0.0") or h.startswith("127.")

def _hook(event, args):
    if event not in _EVENTS:
        return
    try:
        if event in ("socket.connect", "socket.sendto"):
            tgt = args[1]
            host = tgt[0] if isinstance(tgt, tuple) else tgt
        else:
            host = args[0]
            tgt = args[:2] if event == "socket.getaddrinfo" else args[0]
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if _is_local(host):
            return
        stack = [f"{f.filename}:{f.lineno}:{f.name}" for f in traceback.extract_stack()[-9:-1]]
        with _LOCK, open(_OUT, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": event, "host": str(host), "target": str(tgt), "stack": stack}) + "\n")
    except Exception:
        pass

if _OUT:
    sys.addaudithook(_hook)
'''

NO_NET_ENV = {"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
              "NO_PROXY": "127.0.0.1,localhost", "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}


def run(cmd: list[str], log: Path, env: dict[str, str] | None = None, timeout: int = 1800) -> tuple[int, float]:
    t0 = time.time()
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env, timeout=timeout).returncode
    return rc, round(time.time() - t0, 1)


def modbus_fc3(port: int, start: int, count: int, unit: int = 1) -> list[int] | int:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
        s.sendall(struct.pack(">HHHBBHH", 1, 0, 6, unit, 3, start, count))
        hdr = s.recv(9)
        if hdr[7] & 0x80:
            return hdr[8]
        data = b""
        while len(data) < hdr[8]:
            data += s.recv(hdr[8] - len(data))
        return list(struct.unpack(f">{count}H", data))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wheels", required=True)
    ap.add_argument("--base-python", required=True)
    ap.add_argument("--out", default=str(H.ROOT / "reports" / "remediation" / "evidence" / "offline_install"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gv_offline_"))
    res: dict[str, Any] = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "checks": {}}
    ck = res["checks"]
    wheels = Path(args.wheels)
    ck["wheelhouse"] = {"files": len(list(wheels.glob("*.whl"))),
                        "size_mb": round(sum(p.stat().st_size for p in wheels.glob("*")) / 1048576.0, 1)}

    # 1. Чистое окружение и установка только из wheelhouse
    venv = work / "venv"
    rc, _ = run([args.base_python, "-m", "venv", str(venv)], out / "venv_create.log")
    py = str(venv / "Scripts" / "python.exe")
    env = {**os.environ, **NO_NET_ENV}
    rc_i, t_i = run([py, "-m", "pip", "install", "--no-index", "--find-links", str(wheels), "-r",
                     str(H.ROOT / "requirements.lock")], out / "pip_install_offline.log", env=env)
    ck["pip_install"] = {"rc": rc_i, "seconds": t_i}
    rc_c, _ = run([py, "-m", "pip", "check"], out / "pip_check.log", env=env)
    ck["pip_check_rc"] = rc_c
    frz = subprocess.run([py, "-m", "pip", "freeze"], capture_output=True, text=True, env=env).stdout
    (out / "pip_freeze_installed.txt").write_text(frz, encoding="utf-8")
    lock = {ln.strip().lower() for ln in (H.ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")}
    inst = {ln.strip().lower() for ln in frz.splitlines() if ln.strip()}
    ck["lock_vs_installed"] = {"lock_entries": len(lock), "missing": sorted(lock - inst), "extra": sorted(inst - lock)}
    imp = subprocess.run([py, "-B", "-c", "import torch, ultralytics, cv2, fastapi, aiosqlite, cryptography, httpx;"
                          "print(torch.__version__, ultralytics.__version__, cv2.__version__, torch.cuda.is_available())"],
                         capture_output=True, text=True, env={**env, "CUDA_VISIBLE_DEVICES": "", "YOLO_OFFLINE": "1"},
                         cwd=str(H.ROOT))
    ck["imports"] = {"rc": imp.returncode, "versions": imp.stdout.strip(), "stderr_tail": imp.stderr[-400:]}

    # 2. Модели и статические ресурсы
    w = H.ROOT / "models" / "gauge_yolov8.pt"
    ck["yolo_weights"] = {"exists": w.is_file(), "bytes": w.stat().st_size if w.is_file() else 0,
                          "sha256": hashlib.sha256(w.read_bytes()).hexdigest() if w.is_file() else None}
    idx = (H.ROOT / "static" / "index.html").read_text(encoding="utf-8")
    refs = sorted(set(re.findall(r'(?:src|href)="(/static/[^"#?]+)', idx)))
    js_imports = set()
    for js in (H.ROOT / "static" / "js").rglob("*.js"):
        for m in re.findall(r"""from\s+['"](\.{1,2}/[^'"]+)['"]""", js.read_text(encoding="utf-8")):
            js_imports.add(str((js.parent / m).resolve().relative_to(H.ROOT.resolve())).replace("\\", "/"))
    missing_static = [r for r in refs if not (H.ROOT / r.lstrip("/")).is_file()] + \
                     [m for m in sorted(js_imports) if not (H.ROOT / m).is_file()]
    # Загружаемые браузером ресурсы (скрипты, стили, изображения, шрифты, import/fetch) отделяются
    # от навигационных ссылок <a href>, которые открываются только по щелчку пользователя
    ext_urls, ext_links = [], []
    res_re = re.compile(r"""(?:<script[^>]*\ssrc|<link[^>]*\shref|<img[^>]*\ssrc|<source[^>]*\ssrc|url\(|@import|fetch\(|new WebSocket\(|import\s[^;]*from)\s*=?\s*['"(]?\s*['"]?(https?://[^'")\s]+)""", re.I)
    a_re = re.compile(r"""<a\s[^>]*href=['"](https?://[^'"]+)""", re.I)
    for f in list((H.ROOT / "static").rglob("*.html")) + list((H.ROOT / "static").rglob("*.css")) + list((H.ROOT / "static").rglob("*.js")):
        txt = f.read_text(encoding="utf-8", errors="replace")
        ext_urls += [f"{f.name}: {m}" for m in res_re.findall(txt)]
        ext_links += [f"{f.name}: {m}" for m in a_re.findall(txt)]
    ck["static"] = {"index_refs": len(refs), "js_module_imports": len(js_imports), "missing": missing_static,
                    "external_resource_urls": ext_urls, "external_navigation_links": ext_links}

    # 3. Запуск из нового окружения с аудитом сетевых вызовов
    audit_dir = work / "audit"
    audit_dir.mkdir()
    (audit_dir / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    audit_log = out / "runtime_network_audit.jsonl"
    audit_log.unlink(missing_ok=True)
    mb_port = H.free_port()
    srv = H.GaugeServer(work / "server", python=py, extra_env={
        **NO_NET_ENV, "PYTHONPATH": str(audit_dir), "GV_NET_AUDIT": str(audit_log),
        "GAUGEVISION_MODBUS_ENABLED": "1", "GAUGEVISION_MODBUS_HOST": "127.0.0.1", "GAUGEVISION_MODBUS_PORT": str(mb_port),
    })
    try:
        t0 = time.time()
        srv.start(timeout=240)
        ck["server_start_s"] = round(time.time() - t0, 1)
        api = H.Api(srv.base, "engineer", H.ENGINEER_PASS)
        meta = api.get("/api/meta")
        ck["meta"] = {"yolo": meta["yolo"], "yolo_device": meta["yolo_device"], "demo": meta["demo_mode"]}
        time.sleep(25)
        streams = api.get("/api/architecture/streams")
        ck["cv_bench_streams"] = [{"id": s["id"], "status": s["status"], "value": s["value"],
                                   "inference_ms": s["inference_ms"], "frames": s["frames_total"]}
                                  for s in streams if s.get("is_bench")]
        page = api.client.get("/")
        assets = {r: api.client.get(r).status_code for r in refs}
        ck["hmi"] = {"index": page.status_code, "assets_ok": sum(1 for v in assets.values() if v == 200),
                     "assets_total": len(assets), "csp": page.headers.get("content-security-policy", "")[:80]}
        disp = api.get("/api/dispatch/overview")
        ck["analytics"] = {"instruments": disp["summary"]["total"], "avg_health": disp["summary"]["avg_health_score"]}
        r = api.post("/api/specs/generate", {"period": "12h", "format": "docx"})
        docx_ok = False
        if r.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                docx_ok = "word/document.xml" in zf.namelist()
                media = len([n for n in zf.namelist() if n.startswith("word/media/")])
            (out / "offline_generated_spec.docx").write_bytes(r.content)
        ck["docx"] = {"status": r.status_code, "valid": docx_ok, "bytes": len(r.content), "media": media if docx_ok else 0}
        regs = modbus_fc3(mb_port, 900, 6)
        ck["modbus_system_block"] = regs
        api.close()
    finally:
        rc_s = srv.stop()
        ck["server_exit_code"] = rc_s
        log = srv.log_path.read_text(encoding="utf-8", errors="replace") if srv.log_path.is_file() else ""
        (out / "offline_server.log").write_text(log, encoding="utf-8")
        ck["yolo_loaded_logged"] = "YOLOv8 загружена" in log and "устройство cpu" in log
        ck["graceful_shutdown_logged"] = "Application shutdown complete" in log
        ck["log_errors"] = log.count(" ERROR ") + log.count("Traceback")
    dbf = srv.data_dir / "gaugevision.db"
    con = sqlite3.connect(f"file:{dbf}?mode=ro", uri=True)
    ck["sqlite"] = {
        "journal_mode": con.execute("PRAGMA journal_mode").fetchone()[0],
        "instrument_readings": con.execute("SELECT COUNT(*) FROM instrument_readings").fetchone()[0],
        "events": con.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "users": con.execute("SELECT COUNT(*) FROM users").fetchone()[0],
    }
    con.close()

    # 4. Анализ сетевого аудита
    hostname = socket.gethostname().lower()
    events = []
    if audit_log.is_file():
        for ln in audit_log.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    classified: dict[str, list[dict[str, Any]]] = {"local_hostname_lookup": [], "udp_route_probe_no_packets": [],
                                                   "external_attempt": []}
    for e in events:
        host = e["host"].lower()
        stack = " ".join(e["stack"])
        if host == hostname:
            classified["local_hostname_lookup"].append(e)
        elif e["event"] == "socket.connect" and "candidate_lan_ips" in stack:
            classified["udp_route_probe_no_packets"].append(e)
        else:
            classified["external_attempt"].append(e)
    ck["runtime_network_audit"] = {
        "events_total": len(events),
        "local_hostname_lookup": len(classified["local_hostname_lookup"]),
        "udp_route_probe_no_packets": sorted({e["host"] for e in classified["udp_route_probe_no_packets"]}),
        "external_attempts": classified["external_attempt"][:20],
    }
    shutil.rmtree(venv, ignore_errors=True)
    verdict = {
        "offline_install_ok": ck["pip_install"]["rc"] == 0 and ck["pip_check_rc"] == 0,
        "installed_matches_lock": not ck["lock_vs_installed"]["missing"] and not ck["lock_vs_installed"]["extra"],
        "imports_ok": ck["imports"]["rc"] == 0,
        "weights_present": ck["yolo_weights"]["exists"],
        "static_complete_no_external": not ck["static"]["missing"] and not ck["static"]["external_resource_urls"],
        "yolo_cpu_loaded": ck.get("yolo_loaded_logged", False) and ck.get("meta", {}).get("yolo") is True,
        "cv_inference_running": bool(ck.get("cv_bench_streams")) and all(s["value"] is not None and s["frames"] > 0 for s in ck["cv_bench_streams"]),
        "hmi_served": ck.get("hmi", {}).get("index") == 200 and ck["hmi"]["assets_ok"] == ck["hmi"]["assets_total"],
        "sqlite_written": ck["sqlite"]["journal_mode"] == "wal" and ck["sqlite"]["instrument_readings"] > 0 and ck["sqlite"]["events"] > 0,
        "analytics_36": ck.get("analytics", {}).get("instruments") == 36,
        "docx_generated": ck.get("docx", {}).get("valid") is True,
        "modbus_serves": isinstance(ck.get("modbus_system_block"), list) and ck["modbus_system_block"][0] == 36,
        "no_external_network_attempts": not ck["runtime_network_audit"]["external_attempts"],
        "no_server_errors": ck.get("log_errors", 1) == 0,
    }
    res["verdict"] = verdict
    res["passed"] = all(verdict.values())
    res["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (out / "offline_install_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    print("OFFLINE INSTALL PASSED" if res["passed"] else "OFFLINE INSTALL FAILED")
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
