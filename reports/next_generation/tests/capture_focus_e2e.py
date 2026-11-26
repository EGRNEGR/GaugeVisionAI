"""
Браузерная проверка Tap-to-Focus клиента «Смартфон как камера» (этап 0).

Запускает настоящий сервер `run.py --demo` (HTTPS, RBAC, CPU), выдаёт QR-сессию через
`POST /api/phone/session` и открывает выданную ссылку в Chromium с файловой фейковой
камерой (кадры отрисованного манометра, Y4M). Возможности объектива (focusMode, zoom,
torch, pointsOfInterest) эмулируются в браузере, каждый вызов applyConstraints
протоколируется. Аппаратный автофокус смартфона этим тестом НЕ подтверждается.

  python reports/next_generation/tests/capture_focus_e2e.py --out reports/next_generation/evidence/tap_to_focus
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "remediation" / "tests"))
import gv_harness as H  # noqa: E402

import cv2  # noqa: E402

GAUGE_VALUE = 9.0


def write_y4m(path: Path, width: int, height: int, frames: int = 20) -> Path:
    """Y4M 4:2:0 из кадров отрисованного манометра — вход файловой фейковой камеры Chromium."""
    with path.open("wb") as fh:
        fh.write(f"YUV4MPEG2 W{width} H{height} F10:1 Ip A1:1 C420jpeg\n".encode())
        for i in range(frames):
            bgr = H.gauge_frame(GAUGE_VALUE + 0.05 * (i % 2), width=width, height=height)
            yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420)
            fh.write(b"FRAME\n")
            fh.write(yuv.tobytes())
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(H.ROOT / "reports" / "next_generation" / "evidence" / "tap_to_focus"))
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    tools = H.load_tools()
    env = dict(os.environ)
    if tools.get("playwright_core"):
        env["GV_PLAYWRIGHT_CORE"] = tools["playwright_core"]

    work = Path(tempfile.mkdtemp(prefix="gv_focus_e2e_"))
    videos = {
        "16x9": write_y4m(work / "gauge_1280x720.y4m", 1280, 720),
        "4x3": write_y4m(work / "gauge_640x480.y4m", 640, 480),
    }
    server = H.GaugeServer(work / "server")
    result: dict = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        server.start()
        api = H.Api(server.base)
        sess = api.post("/api/phone/session", {}).json()
        cam_id, token = sess["cam_id"], sess["token"]
        capture_url = f"{server.base}/capture?cam_id={cam_id}&token={token}"
        before = api.get(f"/api/cameras/{cam_id}")
        proc = subprocess.run(
            ["node", str(HERE / "capture_focus_driver.js"), capture_url, str(out),
             json.dumps({k: str(v) for k, v in videos.items()})],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900, env=env)
        print(proc.stdout[-4000:])
        if proc.stderr.strip():
            print("STDERR:", proc.stderr[-3000:])
        rep = json.loads((out / "capture_focus_report.json").read_text(encoding="utf-8"))
        after = api.get(f"/api/cameras/{cam_id}")
        result.update({
            "cam_id": cam_id,
            "camera_before": {k: before.get(k) for k in ("status", "stream")},
            "camera_after": {k: after.get(k) for k in ("status", "stream", "last_reading")},
            "driver_exit": proc.returncode,
            "failures": rep.get("failures", []),
            "scenarios": len(rep.get("scenarios", {})),
        })
        # Сервер должен был принять кадры по WSS и выдать CV-показание по ним
        stream = after.get("stream") or {}
        frames = stream.get("frames_total") or 0
        result["server_frames_received"] = frames
        api.close()
    finally:
        server.stop()
        shutil.copy(server.log_path, out / "server.log")
    (out / "capture_focus_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = result.get("driver_exit") == 0 and not result.get("failures")
    print(json.dumps({"ok": ok, "failures": result.get("failures"), "scenarios": result.get("scenarios")},
                     ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
