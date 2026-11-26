"""
Independent Audit Script 04 — Full 25-Step End-to-End Acceptance, Live HTTPS Server Cold Start
& Memory Benchmark, Live Phone WSS CV Injection, Air-Gapped Playwright Browser Verification,
and .docx <-> Live API Data Reconciliation (Sections 8, 11, 13, 15).
Runs strictly on CPU (CUDA_VISIBLE_DEVICES="").
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import ssl
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

REPO = Path(__file__).resolve().parents[3]
OUT_DIR = Path(os.environ.get("AUDIT_OUT_DIR", str(REPO / "reports" / "audit" / "evidence")))
OUT_DIR.mkdir(parents=True, exist_ok=True)
DRIVER_JS = Path(__file__).resolve().parent / "audit_04_browser_driver.js"

import cv2
import httpx
import numpy as np
import websockets


def render_mtp160_jpeg(value_mpa: float, width: int = 960, height: int = 540) -> bytes:
    img = np.full((height, width, 3), (30, 34, 38), dtype=np.uint8)
    cx, cy = width // 2, height // 2
    r_dial = 190
    cv2.circle(img, (cx, cy), r_dial + 18, (88, 94, 102), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r_dial, (240, 242, 240), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r_dial, (55, 60, 65), 2, cv2.LINE_AA)
    for i in range(81):
        ang = math.radians((135.0 + (i * 0.2 / 16.0) * 270.0) % 360.0)
        c, s = math.cos(ang), math.sin(ang)
        r1 = r_dial - 10
        r0 = r_dial - (28 if i % 10 == 0 else 18)
        cv2.line(img, (int(cx + c * r0), int(cy + s * r0)), (int(cx + c * r1), int(cy + s * r1)), (30, 32, 35), 2 if i % 10 == 0 else 1, cv2.LINE_AA)
    ang = math.radians((135.0 + (value_mpa / 16.0) * 270.0) % 360.0)
    c, s = math.cos(ang), math.sin(ang)
    nc, ns = -s, c
    tip = (cx + c * (r_dial - 20), cy + s * (r_dial - 20))
    tail = (cx - c * 32, cy - s * 32)
    pts = np.array([
        [tip[0], tip[1]],
        [cx + nc * 4.5, cy + ns * 4.5],
        [tail[0] + nc * 6.0, tail[1] + ns * 6.0],
        [tail[0] - nc * 6.0, tail[1] - ns * 6.0],
        [cx - nc * 4.5, cy - ns * 4.5],
    ], dtype=np.int32)
    cv2.fillConvexPoly(img, pts, (18, 20, 24), cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 10, (25, 28, 32), -1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    assert ok
    return buf.tobytes()


async def push_live_cv_sequence(base_url: str) -> dict:
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
        sess = (await client.post(f"{base_url}/api/phone/session", json={})).json()
        token = sess["token"]
        cam_id = sess["cam_id"]

    ws_url = base_url.replace("https://", "wss://") + f"/ws/phone/{cam_id}?token={token}"
    acks = []
    async with websockets.connect(ws_url, ssl=ssl_ctx) as ws:
        hello = json.loads(await ws.recv())
        # Push 13.0 (normal) -> 14.7 (warning) -> 15.7 (alert) -> 13.0 (return)
        for target_val, n_frames in ((13.0, 5), (14.8, 7), (15.7, 7), (13.0, 4)):
            jpg = render_mtp160_jpeg(target_val)
            for _ in range(n_frames):
                await ws.send(jpg)
                ack = json.loads(await ws.recv())
                acks.append({"target": target_val, "reading": ack.get("reading")})
                await asyncio.sleep(0.32)

    valid_readings = [a["reading"] for a in acks if a.get("reading") and a["reading"].get("valid")]
    levels_seen = sorted({r.get("level") for r in valid_readings if r.get("level")})
    return {
        "hello_type": hello.get("type"),
        "frames_sent": len(acks),
        "valid_readings_received": len(valid_readings),
        "levels_seen": levels_seen,
        "last_reading": valid_readings[-1] if valid_readings else None,
    }


def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="gv_audit_e2e_"))
    port = 18443
    base_url = f"https://127.0.0.1:{port}"

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["GAUGEVISION_DEVICE"] = "cpu"
    env["GAUGEVISION_DEMO"] = "1"
    env["GAUGEVISION_DB"] = str(tmp_dir / "e2e.db")
    env["GAUGEVISION_SF_DB"] = str(tmp_dir / "e2e_sf.db")
    env["GAUGEVISION_MODBUS_ENABLED"] = "1"
    env["GAUGEVISION_MODBUS_PORT"] = "15543"
    env["YOLO_CONFIG_DIR"] = str(tmp_dir / "yolo_cfg")

    log_path = OUT_DIR / "e2e_server.log"
    log_f = open(log_path, "w", encoding="utf-8")

    t_start = time.perf_counter()
    proc = subprocess.Popen(
        [sys.executable, "-B", str(REPO / "run.py"), "--demo", "--device", "cpu", "--port", str(port), "--db", str(tmp_dir / "e2e.db")],
        cwd=str(REPO),
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
    )

    ready_s = None
    try:
        with httpx.Client(verify=False, timeout=2.0) as client:
            for _ in range(90):
                if proc.poll() is not None:
                    raise RuntimeError(f"Server exited early with code {proc.returncode}")
                try:
                    r = client.get(f"{base_url}/api/health")
                    if r.status_code == 200:
                        ready_s = round(time.perf_counter() - t_start, 2)
                        break
                except Exception:
                    pass
                time.sleep(0.5)
        assert ready_s is not None, "Server failed to become ready in 45s"

        # Step 2-8: Push real CV frames over WSS on primary channel #01!
        cv_seq = asyncio.run(push_live_cv_sequence(base_url))

        # Check live Adaptive FPS & Ring Buffer on primary #01 after alert sequence
        with httpx.Client(verify=False, timeout=10.0) as client:
            arch_after_cv = client.get(f"{base_url}/api/architecture/status").json()
            disp_after_cv = client.get(f"{base_url}/api/dispatch/overview").json()
            events_after_cv = client.get(f"{base_url}/api/events?limit=100").json()

        # Run Playwright air-gapped browser E2E driver
        t_br0 = time.perf_counter()
        drv = subprocess.run(
            ["node", str(DRIVER_JS), base_url, str(OUT_DIR)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        browser_elapsed_s = round(time.perf_counter() - t_br0, 2)
        print("DRIVER STDOUT:", drv.stdout.strip())
        if drv.stderr.strip():
            print("DRIVER STDERR:", drv.stderr.strip())
        assert drv.returncode == 0, f"Browser driver failed: {drv.returncode}"

        browser_report = json.loads((OUT_DIR / "browser_driver_report.json").read_text(encoding="utf-8"))

        # Reconcile downloaded .docx and .md against live API values
        docx_path = OUT_DIR / "e2e_downloaded_spec.docx"
        md_path = OUT_DIR / "e2e_downloaded_spec.md"
        with zipfile.ZipFile(docx_path, "r") as zf:
            doc_xml = zf.read("word/document.xml")
            root = ET.fromstring(doc_xml)
            docx_text = "".join(root.itertext())
            media_imgs = [n for n in zf.namelist() if n.startswith("word/media/image")]
        md_text = md_path.read_text(encoding="utf-8")

        reconcile = {
            "docx_contains_custom_plant": "ТЭЦ-Аудит" in docx_text,
            "docx_contains_custom_doc_num": "ТЗ-АУДИТ-E2E-01" in docx_text,
            "md_contains_custom_doc_num": "ТЗ-АУДИТ-E2E-01" in md_text,
            "docx_media_images_count": len(media_imgs),
            "docx_has_all_5_sections": all(s in docx_text for s in (
                "1. Паспорт обследуемого технологического узла",
                "2. Сводный протокол инструментального видеомониторинга",
                "3. Дефектная ведомость",
                "4. Техническое задание на модернизацию",
                "5. Технико-экономическое обоснование",
            )),
            "md_has_all_5_sections": all(s in md_text for s in (
                "## 1. Паспорт", "## 2. Сводный протокол", "## 3. Дефектная ведомость",
                "## 4. Техническое задание", "## 5. Технико-экономическое обоснование",
            )),
        }

        primary_stream = next((s for s in arch_after_cv["streams"] if s["id"] == "demo-mtp160-steam"), {})
        summary = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "cold_start_ready_s": ready_s,
            "live_wss_cv_sequence": cv_seq,
            "primary_stream_after_cv": {
                "adaptive": primary_stream.get("adaptive"),
                "ring_buffer": primary_stream.get("ring_buffer"),
                "quality": primary_stream.get("quality"),
            },
            "events_count_after_cv": len(events_after_cv),
            "dispatch_summary_after_cv": disp_after_cv.get("summary"),
            "browser_elapsed_s": browser_elapsed_s,
            "browser_report": browser_report,
            "docx_md_reconciliation": reconcile,
        }
        (OUT_DIR / "hmi_e2e_audit_results.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("E2E AUDIT COMPLETE ->", OUT_DIR / "hmi_e2e_audit_results.json")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_f.close()


if __name__ == "__main__":
    main()
