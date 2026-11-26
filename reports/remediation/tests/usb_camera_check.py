"""
Проверка захвата с физической USB/UVC-камеры через рабочий сервер (тип источника `device`).

  python reports/remediation/tests/usb_camera_check.py --index 0 --out reports/remediation/evidence/usb_camera

Камера добавляется через REST, проверяются подключение (DirectShow), частота кадров, работа
CV-конвейера на её кадрах, перезапуск потока и освобождение устройства после удаления.
Кадры с камеры на диск не сохраняются (в кадр может попасть человек); в отчёт пишутся только
числовые метрики. Прибора в кадре нет, поэтому достоверное показание не ожидается.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gv_harness as H  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="0")
    ap.add_argument("--out", default=str(H.ROOT / "reports" / "remediation" / "evidence" / "usb_camera"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    srv = H.GaugeServer(Path(tempfile.mkdtemp(prefix="gv_usb_")) / "server")
    res: dict = {}
    try:
        srv.start()
        api = H.Api(srv.base, "engineer", H.ENGINEER_PASS)
        adm = H.Api(srv.base, "admin", H.ADMIN_PASS)
        r = api.post("/api/cameras", {"name": "USB-камера", "type": "device", "source_url": args.index,
                                      "calibration": H.CALIBRATION, "thresholds": H.THRESHOLDS})
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        t0 = time.time()
        online = None
        while time.time() - t0 < 30:
            st = api.get(f"/api/cameras/{cid}")
            if st["status"] == "online":
                online = round(time.time() - t0, 2)
                break
            time.sleep(0.5)
        res["connect_s"] = online
        samples = []
        for _ in range(20):
            st = api.get(f"/api/cameras/{cid}")
            rd = st.get("reading") or {}
            samples.append({"status": st["status"], "fps": (st.get("stream") or {}).get("fps"),
                            "frames": (st.get("stream") or {}).get("frames_total"),
                            "process_ms": rd.get("process_ms"), "dial_found": rd.get("dial_found"), "valid": rd.get("valid")})
            time.sleep(1.0)
        res["samples"] = samples
        res["frames_progress"] = (samples[-1]["frames"] or 0) - (samples[0]["frames"] or 0)
        res["fps_median"] = sorted(s["fps"] or 0 for s in samples)[len(samples) // 2]
        res["cv_processed"] = any(s["process_ms"] for s in samples)
        r2 = api.post(f"/api/cameras/{cid}/restart")
        t1 = time.time()
        back = None
        while time.time() - t1 < 30:
            if api.get(f"/api/cameras/{cid}")["status"] == "online":
                back = round(time.time() - t1, 2)
                break
            time.sleep(0.5)
        res["restart_status"], res["restart_online_s"] = r2.status_code, back
        d = adm.client.delete(f"/api/cameras/{cid}")
        res["delete_status"] = d.status_code
        time.sleep(2)
        import cv2
        cap = cv2.VideoCapture(int(args.index), cv2.CAP_DSHOW)
        res["device_released_after_delete"] = bool(cap.isOpened())
        cap.release()
        api.close()
        adm.close()
    finally:
        srv.stop()
    res["verdict"] = {
        "connected": res.get("connect_s") is not None,
        "frames_flowing": res.get("frames_progress", 0) > 0,
        "cv_pipeline_ran": res.get("cv_processed", False),
        "restart_ok": res.get("restart_online_s") is not None,
        "device_released": res.get("device_released_after_delete", False),
    }
    res["passed"] = all(res["verdict"].values())
    (out / "usb_camera_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res["verdict"], ensure_ascii=False, indent=2))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
