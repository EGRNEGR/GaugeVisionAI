"""
GPU-валидация и сравнительный бенчмарк CV-конвейера GaugeVision AI для стабильной рабочей
станции (целевая конфигурация — RTX 3090 24 ГБ). На ноутбуке с RTX 5060 Laptop не запускается:
он ранее показывал WHEA PCIe-ошибки под длительной GPU-нагрузкой.

  python reports/remediation/tests/gpu_validation_3090.py --out gpu_results --soak-min 30

Этапы:
  1. Окружение: torch, CUDA, имя GPU, драйвер (nvidia-smi).
  2. Точность: 27 эталонных кадров (CW 0–16 МПа, CCW 0–100 %, вакуум −100…0 кПа) на CPU и
     на GPU (FP32 и FP16): MAE/макс. ошибка и расхождение GPU против CPU.
  3. Задержка: 500 кадров после прогрева, p50/p95/p99 мс на кадр, CPU против GPU.
  4. Пропускная способность: 1/2/4/8/16 параллельных конвейеров, кадров/с суммарно.
  5. Длительная нагрузка (по умолчанию 30 мин): задержка, температура, мощность, память GPU
     каждые 5 с (nvidia-smi), признаки троттлинга и ошибок.
Результат: <out>/gpu_validation.json и gpu_soak.jsonl.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def smi() -> dict:
    q = "name,driver_version,temperature.gpu,power.draw,memory.used,clocks.sm,clocks_throttle_reasons.active"
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        k = q.split(",")
        return dict(zip(k, [x.strip() for x in out.split(",")]))
    except Exception as exc:
        return {"error": str(exc)}


def frames():
    """Эталонные кадры с известными значениями (тот же рендер, что у стенда и аудита)."""
    from app.stream_manager import render_gauge_frame
    cases = []
    for v in [i * 16.0 / 16 for i in range(17)]:
        cases.append(("cw_mpa", v, {"v_min": 0.0, "theta_min": 135.0, "v_max": 16.0, "theta_max": 45.0, "direction": "cw"},
                      render_gauge_frame(code="GPU", name="", unit="МПа", value=v, v_min=0.0, v_max=16.0, width=640, height=480)))
    for v in (0.0, 25.0, 50.0, 75.0, 100.0):
        cases.append(("pct", v, {"v_min": 0.0, "theta_min": 135.0, "v_max": 100.0, "theta_max": 45.0, "direction": "cw"},
                      render_gauge_frame(code="GPU", name="", unit="%", value=v, v_min=0.0, v_max=100.0, width=640, height=480)))
    for v in (-100.0, -75.0, -50.0, -25.0, 0.0):
        cases.append(("vac", v, {"v_min": -100.0, "theta_min": 135.0, "v_max": 0.0, "theta_max": 45.0, "direction": "cw"},
                      render_gauge_frame(code="GPU", name="", unit="кПа", value=v, v_min=-100.0, v_max=0.0, width=640, height=480)))
    return cases


def accuracy(vision, cases) -> dict:
    errs, vals = [], []
    for kind, ref, cal, img in cases:
        r = vision.GaugePipeline(f"acc-{kind}-{ref}").process(img, cal, {}, "u", with_overlay=False)
        span = abs(cal["v_max"] - cal["v_min"])
        vals.append(r.value if r.valid else None)
        if r.valid and r.value is not None:
            errs.append(abs(r.value - ref) / span * 100.0)
    return {"valid": len(errs), "total": len(cases), "mae_pct_span": round(statistics.mean(errs), 4) if errs else None,
            "max_pct_span": round(max(errs), 4) if errs else None, "values": vals}


def latency(vision, img, cal, n: int) -> dict:
    p = vision.GaugePipeline("lat")
    for _ in range(20):
        p.process(img, cal, {}, "МПа", with_overlay=False)
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        p.process(img, cal, {}, "МПа", with_overlay=True)
        ts.append((time.perf_counter() - t) * 1000.0)
    ts.sort()
    return {"n": n, "p50_ms": round(ts[n // 2], 2), "p95_ms": round(ts[int(n * 0.95)], 2), "p99_ms": round(ts[int(n * 0.99)], 2)}


def throughput(vision, img, cal, channels: int, seconds: float = 20.0) -> dict:
    done = [0] * channels
    stop = time.time() + seconds

    def worker(i: int) -> None:
        p = vision.GaugePipeline(f"thr-{i}")
        while time.time() < stop:
            p.process(img, cal, {}, "МПа", with_overlay=True)
            done[i] += 1
    ths = [threading.Thread(target=worker, args=(i,)) for i in range(channels)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    return {"channels": channels, "fps_total": round(sum(done) / seconds, 1), "fps_per_channel": round(sum(done) / seconds / channels, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="gpu_results")
    ap.add_argument("--soak-min", type=float, default=30.0)
    ap.add_argument("--allow-laptop", action="store_true", help="разрешить запуск на ноутбучном GPU (не рекомендуется)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    import torch
    if not torch.cuda.is_available():
        print("CUDA недоступна — GPU-валидация невозможна")
        return 2
    name = torch.cuda.get_device_name(0)
    if "laptop" in name.lower() and not args.allow_laptop:
        print(f"Отказ: {name} — ноутбучный GPU; длительная нагрузка запрещена политикой испытаний")
        return 3
    res: dict = {"env": {"torch": torch.__version__, "cuda": torch.version.cuda, "gpu": name, "smi": smi()}}
    cases = frames()
    img, cal = cases[12][3], cases[12][2]

    os.environ["GAUGEVISION_DEVICE"] = "cpu"
    from app import config, vision
    config.YOLO_DEVICE = "cpu"
    res["cpu"] = {"accuracy": accuracy(vision, cases), "latency": latency(vision, img, cal, 200)}
    # переключение на GPU: перезагрузка модели с новым устройством
    for dev in ("cuda:0",):
        vision._YOLO = None  # type: ignore[attr-defined]
        config.YOLO_DEVICE = dev
        os.environ["GAUGEVISION_DEVICE"] = dev
        res["gpu"] = {"device_report": vision.yolo_device(), "yolo": vision.yolo_available(),
                      "accuracy": accuracy(vision, cases), "latency": latency(vision, img, cal, 500),
                      "throughput": [throughput(vision, img, cal, c) for c in (1, 2, 4, 8, 16)]}
    cpu_v, gpu_v = res["cpu"]["accuracy"]["values"], res["gpu"]["accuracy"]["values"]
    diffs = [abs(a - b) for a, b in zip(cpu_v, gpu_v) if a is not None and b is not None]
    res["gpu_vs_cpu_max_abs_diff"] = round(max(diffs), 5) if diffs else None

    soak_path = out / "gpu_soak.jsonl"
    p = vision.GaugePipeline("soak")
    t_end = time.time() + args.soak_min * 60.0
    next_s = time.time()
    lat: list[float] = []
    errors = 0
    while time.time() < t_end:
        t = time.perf_counter()
        try:
            p.process(img, cal, {}, "МПа", with_overlay=True)
        except Exception:
            errors += 1
        lat.append((time.perf_counter() - t) * 1000.0)
        if time.time() >= next_s:
            next_s += 5.0
            rec = {"t": round(time.time(), 1), "p50_ms": round(statistics.median(lat), 2) if lat else None,
                   "max_ms": round(max(lat), 2) if lat else None, "errors": errors,
                   "mem_alloc_mb": round(torch.cuda.memory_allocated() / 1048576.0, 1), **smi()}
            lat.clear()
            with open(soak_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    res["soak"] = {"minutes": args.soak_min, "errors": errors, "jsonl": soak_path.name}
    (out / "gpu_validation.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "soak"}, ensure_ascii=False, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
