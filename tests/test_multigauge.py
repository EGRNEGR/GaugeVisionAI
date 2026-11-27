"""
Испытания Multi-Gauge Vision (этап 3).

1. Модульные проверки трекера: устойчивость ID при сдвиге камеры больше окна сопоставления,
   неоднозначность, потеря и повторный захват, ручной ROI, защита от дубликатов при регистрации.
2. Сценарии на синтетическом щите (app/panel_sim.py) из 1, 2, 4, 8 и 16 приборов: регистрация по
   первому кадру, затем 48 кадров — случайное блуждание значений, дрожание и плавный сдвиг камеры,
   пропуск кадров, перекрытие одного прибора, падение освещённости. Измеряются ошибка показаний,
   ID Switch, пропуски, корректный отказ на перекрытом приборе, задержка, FPS и загрузка CPU.

Запуск (строго CPU):
  CUDA_VISIBLE_DEVICES="" GAUGEVISION_DEVICE=cpu python -B tests/test_multigauge.py
Результат в JSON: reports/next_generation/evidence/multigauge/multigauge_synthetic.json
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("GAUGEVISION_DEVICE", "cpu")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config, multigauge, panel_sim, vision  # noqa: E402

OUT = ROOT / "reports" / "next_generation" / "evidence" / "multigauge"


# ---------------------------------------------------------------------------
# 1. Модульные проверки трекера
# ---------------------------------------------------------------------------
def _roi(cx: float, cy: float, r: float) -> vision.DialROI:
    return vision.roi_from_ellipse(cx, cy, r, r, 0.0, score=0.97, source="yolo+ellipse")


def _anchor(cx: float, cy: float, r: float, shape=(720, 1280), mode: str = "auto") -> dict:
    return multigauge.roi_to_anchor(_roi(cx, cy, r), shape, mode)


def test_tracker_units() -> dict:
    shape = (720, 1280)
    grid = [(200 + 220 * c, 180 + 220 * r) for r in range(2) for c in range(4)]
    anchors = {f"g{i}": _anchor(x, y, 80) for i, (x, y) in enumerate(grid)}
    tr = multigauge.InstrumentTracker()
    tr.set_anchors(anchors)

    # исходное положение: все захвачены
    st = tr.update(shape, [_roi(x, y, 80) for x, y in grid])
    assert all(s.state == "locked" for s in st.values())

    # сдвиг камеры на 70 px (0,9 радиуса — больше окна 0,45 r) и порядок детекций перемешан
    dets = [_roi(x + 70, y - 20, 80) for x, y in grid]
    random.Random(1).shuffle(dets)
    st = tr.update(shape, dets)
    for i, (x, y) in enumerate(grid):
        s = st[f"g{i}"]
        assert s.state == "locked", (i, s.state)
        assert abs(s.roi.center[0] - (x + 70)) < 1 and abs(s.roi.center[1] - (y - 20)) < 1, "ID перепутаны"

    # один прибор не найден детектором: положение предсказывается по соседям
    dets = [_roi(x + 72, y - 20, 80) for x, y in grid[1:]]
    st = tr.update(shape, dets)
    assert st["g0"].state == "predicted" and st["g0"].roi is not None
    assert abs(st["g0"].roi.center[0] - (grid[0][0] + 72)) < 3

    # повторный захват
    st = tr.update(shape, [_roi(x + 72, y - 20, 80) for x, y in grid])
    assert st["g0"].state == "reacquired"

    # единственный прибор: один кадр без детекции — удержание, после MG_LOST_AFTER — потерян
    t1 = multigauge.InstrumentTracker()
    t1.set_anchors({"solo": _anchor(640, 360, 120)})
    t1.update(shape, [_roi(640, 360, 120)])
    states = [t1.update(shape, [])["solo"].state for _ in range(config.MG_LOST_AFTER)]
    assert states[0] == "coasting" and states[-1] == "lost", states
    assert t1.tracks["solo"].roi is None

    # неоднозначность: два циферблата одинаково близко к якорю — без угадывания
    t2 = multigauge.InstrumentTracker()
    t2.set_anchors({"a": _anchor(640, 360, 100)})
    st = t2.update(shape, [_roi(640 - 30, 360, 100), _roi(640 + 30, 360, 100)])
    assert st["a"].state == "ambiguous" and st["a"].roi is None

    # чужой прибор вдвое крупнее в окне сопоставления не принимается
    t3 = multigauge.InstrumentTracker()
    t3.set_anchors({"a": _anchor(640, 360, 60)})
    st = t3.update(shape, [_roi(650, 360, 130)])
    assert st["a"].state != "locked"

    # ручной ROI не зависит от детектора
    t4 = multigauge.InstrumentTracker()
    t4.set_anchors({"m": _anchor(300, 300, 90, mode="manual")})
    st = t4.update(shape, None)
    assert st["m"].state == "manual" and st["m"].roi is not None

    # регистрация: кандидат на месте существующего прибора помечается, новый — нет
    cands = [{"anchor": _anchor(205, 182, 79)}, {"anchor": _anchor(1100, 600, 70)}]
    marked = multigauge.match_candidates(cands, [{"id": "g0", "roi": anchors["g0"]}], shape)
    assert marked[0]["registered_instrument_id"] == "g0" and marked[1]["registered_instrument_id"] is None
    return {"cases": 9}


# ---------------------------------------------------------------------------
# 2. Сценарии на синтетическом щите
# ---------------------------------------------------------------------------
FRAMES = 48
PAN = range(10, 21)          # плавный сдвиг камеры
DROPPED = {15, 16, 33}       # кадры не дошли до конвейера
OCCLUDED = range(24, 31)     # прибор 0 наполовину закрыт
DIM = range(36, 41)          # освещённость 70 %


def run_scenario(n: int, seed: int = 0) -> dict:
    rng = random.Random(seed)
    scene = panel_sim.make_panel(n, seed=seed + n, size_jitter=0.35)
    s = float(min(scene.width, scene.height))
    frame0, truth0 = panel_sim.render_panel(scene)

    # регистрация: инженер подтверждает кандидатов детектора на первом кадре
    dets, _ = multigauge.detect_dials_multi(frame0)
    cands = [{"anchor": multigauge.roi_to_anchor(d, frame0.shape), "roi": d} for d in dets]
    instruments, own = [], {}
    for c in multigauge.match_candidates(cands, [], frame0.shape):
        d = c["roi"]
        t = min(truth0, key=lambda t: math.hypot(t["cx"] - d.center[0], t["cy"] - d.center[1]))
        if math.hypot(t["cx"] - d.center[0], t["cy"] - d.center[1]) > 0.3 * t["r"] or t["index"] in own.values():
            continue
        g = scene.gauges[t["index"]]
        iid = f"inst-{t['index']:02d}"
        own[iid] = t["index"]
        instruments.append({"id": iid, "code": g.code, "unit": g.unit, "calibration": g.calibration,
                            "thresholds": {}, "roi": c["anchor"]})
    registered = len(instruments)

    proc = multigauge.MultiGaugeProcessor(f"panel-{n}")
    errs, gross, valid_cnt, expected_cnt = [], 0, 0, 0
    switches, occl_frames, occl_refused, occl_gross = 0, 0, 0, 0
    lat, detect_frames = [], 0
    miss_reasons: dict[str, int] = {}
    gross_cases: list[dict] = []
    cpu0, wall0 = time.process_time(), time.perf_counter()
    last_owner: dict[str, int] = {}
    shift = (0.0, 0.0)
    for k in range(FRAMES):
        panel_sim.step_values(scene, rng)
        if k in PAN:
            shift = (0.05 * (k - PAN.start + 1) / len(PAN), 0.025 * (k - PAN.start + 1) / len(PAN))
        jitter = (rng.uniform(-0.002, 0.002), rng.uniform(-0.002, 0.002))
        occ = {0} if k in OCCLUDED else set()
        frame, truth = panel_sim.render_panel(scene, shift=(shift[0] + jitter[0], shift[1] + jitter[1]),
                                              occlude=occ, brightness=0.7 if k in DIM else 1.0,
                                              noise_sigma=2.0, seed=k)
        if k in DROPPED:
            continue
        t0 = time.perf_counter()
        res = proc.process(frame, instruments, with_overlay=(k == FRAMES - 1))
        lat.append((time.perf_counter() - t0) * 1000.0)
        detect_frames += int(res.detected)
        if k == FRAMES - 1 and res.overlay is not None:
            import cv2
            OUT.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(OUT / f"panel_{n:02d}_overlay.jpg"), res.overlay, [cv2.IMWRITE_JPEG_QUALITY, 80])
        for inst in instruments:
            iid = inst["id"]
            gi = own[iid]
            t = truth[gi]
            r = res.readings[iid]
            tr = proc.tracker.tracks.get(iid)
            # ID Switch: ROI прибора оказался на другом приборе щита
            if tr is not None and tr.roi is not None:
                near = min(truth, key=lambda q: math.hypot(q["cx"] - tr.roi.center[0], q["cy"] - tr.roi.center[1]))
                if math.hypot(near["cx"] - tr.roi.center[0], near["cy"] - tr.roi.center[1]) < near["r"]:
                    if last_owner.get(iid) is not None and near["index"] != last_owner[iid]:
                        switches += 1
                    last_owner[iid] = near["index"]
            if t["occluded"]:
                occl_frames += 1
                if not r.valid:
                    occl_refused += 1
                elif abs(r.value - t["value"]) / t["span"] > 0.10:
                    occl_gross += 1
                continue
            expected_cnt += 1
            if r.valid and r.value is not None:
                valid_cnt += 1
                e = abs(r.value - t["value"]) / t["span"]
                errs.append(e)
                if e > 0.10:
                    gross += 1
                    gross_cases.append({"frame": k, "gauge": t["code"], "radius_px": round(t["r"]),
                                        "truth": round(t["value"], 3), "value": round(r.value, 3),
                                        "method": r.debug.get("needle_method"),
                                        "track": (r.debug.get("track") or {}).get("state")})
            else:
                why = r.debug.get("invalid_reason") or "unknown"
                miss_reasons[why] = miss_reasons.get(why, 0) + 1
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    processed = FRAMES - len(DROPPED)
    pct = lambda v: round(100.0 * v, 3)  # noqa: E731
    errs.sort()
    return {
        "gauges": n, "registered": registered, "frames": processed, "frame_size": [scene.width, scene.height],
        "gauge_radius_px": [round(min(g.r for g in scene.gauges) * s), round(max(g.r for g in scene.gauges) * s)],
        "valid_rate": pct(valid_cnt / max(1, expected_cnt)),
        "miss_rate": pct(1 - valid_cnt / max(1, expected_cnt)),
        "mae_norm_pct": pct(statistics.fmean(errs)) if errs else None,
        "p95_norm_pct": pct(errs[int(0.95 * (len(errs) - 1))]) if errs else None,
        "max_norm_pct": pct(errs[-1]) if errs else None,
        "gross_rate_pct": pct(gross / max(1, len(errs))),
        "id_switches": switches, "miss_reasons": miss_reasons, "gross_cases": gross_cases,
        "occluded_frames": occl_frames, "occluded_refused": occl_refused, "occluded_gross": occl_gross,
        "latency_ms_mean": round(statistics.fmean(lat), 1),
        "latency_ms_p95": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 1),
        "latency_ms_max": round(max(lat), 1),
        "detect_frames": detect_frames,
        "fps": round(1000.0 / statistics.fmean(lat), 2),
        "cpu_cores_busy": round(cpu / wall, 2),
    }


def main() -> int:
    print("[unit]", test_tracker_units())
    vision._load_yolo()  # прогрев вне замеров
    rows = []
    for n in (1, 2, 4, 8, 16):
        row = run_scenario(n)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"device": "cpu", "yolo": vision.yolo_available(), "workers": config.MG_WORKERS,
            "cpu_count": os.cpu_count(), "frames_per_scenario": FRAMES, "dropped": sorted(DROPPED),
            "pan_frames": [PAN.start, PAN.stop - 1], "occluded_frames": [OCCLUDED.start, OCCLUDED.stop - 1],
            "dim_frames": [DIM.start, DIM.stop - 1], "synthetic": True}
    (OUT / "multigauge_synthetic.json").write_text(json.dumps({"meta": meta, "scenarios": rows},
                                                              ensure_ascii=False, indent=1), encoding="utf-8")
    failures = []
    for r in rows:
        if r["registered"] != r["gauges"]:
            failures.append(f"{r['gauges']}: зарегистрировано {r['registered']}")
        if r["id_switches"]:
            failures.append(f"{r['gauges']}: ID Switch = {r['id_switches']}")
        if r["occluded_gross"]:
            failures.append(f"{r['gauges']}: грубые показания перекрытого прибора = {r['occluded_gross']}")
        if r["gross_rate_pct"] > 1.0:
            failures.append(f"{r['gauges']}: грубых {r['gross_rate_pct']} %")
        if r["valid_rate"] < 90.0:
            failures.append(f"{r['gauges']}: достоверных {r['valid_rate']} %")
    if failures:
        print("FAILED:", "; ".join(failures))
        return 1
    print("ALL MULTI-GAUGE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
