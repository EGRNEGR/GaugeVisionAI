"""Run GaugeVision's own CV stage (YOLO + ellipse + needle) on every frame of the hero video.

Output: compact JSON track for the site HUD (coordinates normalised to frame size).
Strictly CPU. Imports the stable product code read-only; nothing in the repo is modified.
Usage: python annotate.py <repo_root> <video> <out_json>
"""
import json
import os
import sys
import time

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

repo, video, out = sys.argv[1:4]
sys.path.insert(0, repo)

import cv2  # noqa: E402
from app import vision  # noqa: E402

cap = cv2.VideoCapture(video)
fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
frames = []
t0 = time.time()
i = 0
while True:
    ok, frame = cap.read()
    if not ok:
        break
    rec = {"i": i}
    boxes = vision.yolo_gauge_boxes(frame) or []
    if boxes:
        x, y, w, h, conf = boxes[0]
        rec["box"] = [round(x / W, 4), round(y / H, 4), round(w / W, 4), round(h / H, 4)]
        rec["conf"] = round(conf, 3)
    roi = vision.detect_dial(frame)
    if roi is not None:
        (cx, cy), (a, b) = roi.center, roi.axes
        rec["ell"] = [round(cx / W, 4), round(cy / H, 4), round(a / W, 4), round(b / H, 4), round(float(roi.angle_deg), 1)]
        rec["src"] = roi.source
        try:
            dial = vision.normalize_dial(frame, roi)
            nr = vision.estimate_needle(dial)
            if nr.angle_deg is not None:
                rec["needle"] = round(float(nr.angle_deg), 1)
                rec["nconf"] = round(float(nr.confidence), 3)
        except Exception as exc:  # noqa: BLE001 — record and continue
            rec["err"] = str(exc)[:80]
    frames.append(rec)
    i += 1
    if i % 40 == 0:
        print(f"{i} frames, {time.time() - t0:.1f}s", flush=True)

meta = {
    "source": os.path.basename(video), "width": W, "height": H, "fps": fps, "frames": len(frames),
    "device": vision.yolo_device(), "yolo": vision.yolo_available(),
    "note": "Разметка рассчитана модулем app/vision.py GaugeVision AI v3.0.0 (YOLO + эллипс OpenCV + стрелка) на CPU по каждому кадру ролика.",
    "elapsed_s": round(time.time() - t0, 1),
}
json.dump({"meta": meta, "frames": frames}, open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
found = sum(1 for f in frames if "box" in f)
ell = sum(1 for f in frames if "ell" in f)
nd = sum(1 for f in frames if "needle" in f)
print(json.dumps({**meta, "with_box": found, "with_ellipse": ell, "with_needle": nd}, ensure_ascii=False))
