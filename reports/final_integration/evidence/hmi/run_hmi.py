"""
Стенд браузерной приёмки пульта: сервер в демопрофиле (36 позиций для прогноза и оптимизатора) плюс
синтетический видеофайл щита для вкладки «Щит»; затем hmi_check.mjs на трёх разрешениях.

    python run_hmi.py --video <panel.mp4> --work <каталог> --pw <playwright-core> --out <каталог результатов>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))
import run_e2e as E  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--pw", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    (work / "videos").mkdir(parents=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    video = Path(args.video)
    shutil.copy(video, work / "videos" / video.name)
    legend = json.loads(video.with_suffix(".json").read_text(encoding="utf-8"))
    port = E.free_port()
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "GAUGEVISION_DEVICE": "cpu", "PYTHONIOENCODING": "utf-8",
           "GAUGEVISION_DEMO": "1", "GAUGEVISION_DB": str(work / "demo.db"), "GAUGEVISION_SF_DB": str(work / "sf.db"),
           "GAUGEVISION_VIDEOS_DIR": str(work / "videos"), "GAUGEVISION_INCIDENTS_DIR": str(work / "incidents"),
           "GAUGEVISION_AUTO_SPECS_DIR": str(work / "auto_specs"), "GAUGEVISION_LAN_IP": "127.0.0.1",
           "GAUGEVISION_MODBUS_ENABLED": "0", "GAUGEVISION_MQTT_ENABLED": "0"}
    srv = subprocess.Popen([sys.executable, "-B", "run.py", "--demo", "--host", "127.0.0.1", "--port", str(port),
                            "--device", "cpu", "--log-level", "warning"], cwd=str(E.ROOT), env=env,
                           stdout=open(work / "server.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT)
    base = f"https://127.0.0.1:{port}"
    try:
        if not E.wait_for(lambda: httpx.get(f"{base}/api/health", verify=False, timeout=2).status_code == 200, 90):
            raise RuntimeError("сервер не поднялся")
        c = httpx.Client(base_url=base, verify=False, timeout=60)
        # демопрофиль: стендовые учётные записи по умолчанию (config.ADMIN_PASSWORD и т. д.)
        sys.path.insert(0, str(E.ROOT))
        from app import config
        assert c.post("/api/auth/login", json={"username": "admin", "password": config.ADMIN_PASSWORD}).status_code == 200
        cam = c.post("/api/cameras", json={"name": "Щит КИП (синтетическое видео)", "type": "video_file",
                                           "source_url": video.name}).json()
        sid = cam["id"]
        det = E.wait_for(lambda: (lambda d: d.json() if d.status_code == 200 and len(d.json()["candidates"]) >= 4 else None)(
            c.post(f"/api/sources/{sid}/instruments/detect")), 120, 2.0)
        fw, fh = det["frame"]["w"], det["frame"]["h"]
        n = 0
        for cand in det["candidates"]:
            if cand["is_primary_dial"] or n >= 4:
                continue
            ax, ay = cand["anchor"]["cx"], cand["anchor"]["cy"]
            if ax > 1.5:
                ax, ay = ax / fw, ay / fh
            g = min(legend["gauges"], key=lambda g: (g["cx"] - ax) ** 2 + (g["cy"] - ay) ** 2)
            r = c.post(f"/api/sources/{sid}/instruments", json={"name": g["code"], "code": g["code"], "unit": g["unit"],
                                                                "roi": cand["anchor"], "calibration": g["calibration"]})
            n += r.status_code == 201
        time.sleep(20)  # прогноз и сводка диспетчеризации набирают ряд
        cookie = c.cookies.get("gv_session")
        node = subprocess.run(["node", str(Path(__file__).with_name("hmi_check.mjs"))], capture_output=True, text=True,
                              encoding="utf-8", timeout=900,
                              env={**os.environ, "PW": args.pw, "HMI_URL": base + "/", "HMI_COOKIE": cookie,
                                   "HMI_OUT": str(out)})
        (out / "hmi_node.log").write_text(node.stdout + "\n" + node.stderr, encoding="utf-8")
        print(node.stdout[-4000:], node.stderr[-2000:])
        return node.returncode
    finally:
        srv.terminate()
        try:
            srv.wait(15)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    sys.exit(main())
