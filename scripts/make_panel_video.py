"""Демонстрационный видеофайл щита приборов для вкладки «Щит» (Multi-Gauge Vision).

Кадры синтетические (app/panel_sim.py) и в интерфейсе так и подписываются: это стенд для показа
регистрации и сопровождения нескольких приборов одной камерой, а не фотография действующего объекта.
Файл пишется в каталог видеофайлов (data/videos, вне git) и подключается как источник video_file.

    python scripts/make_panel_video.py --gauges 8 --seconds 60
    python scripts/make_panel_video.py --gauges 8 --seconds 1800 --fps 2 --rate 0 --drift 1:0.93:20

`--rate 0` — значения постоянны (известная истина для сверки показаний); `--drift I:FRAC:MIN` — прибор I
линейно уходит к доле FRAC шкалы за MIN минут (проверка прогноза времени до уставки). Легенда (JSON в
stdout и рядом с видео) содержит шкалы, коды и истину для сверки.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config, panel_sim  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gauges", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--out", type=Path, default=None, help="по умолчанию data/videos/panel_NN.mp4")
    ap.add_argument("--rate", type=float, default=0.004, help="шаг случайного блуждания, доля шкалы (0 — постоянно)")
    ap.add_argument("--drift", default=None, help="I:FRAC:MIN — линейный дрейф прибора I к доле FRAC шкалы за MIN минут")
    args = ap.parse_args()
    drift = None
    if args.drift:
        di, dfrac, dmin = args.drift.split(":")
        drift = (int(di), float(dfrac), float(dmin) * 60.0)

    scene = panel_sim.make_panel(args.gauges, seed=args.seed, size_jitter=0.3)
    out = args.out or config.get_videos_dir() / f"panel_{args.gauges:02d}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (scene.width, scene.height))
    if not writer.isOpened():
        print(f"не удалось открыть {out} на запись", file=sys.stderr)
        return 1
    rng = random.Random(args.seed)
    frames = int(args.seconds * args.fps)
    d_start = scene.gauges[drift[0]].value if drift else None
    for k in range(frames):
        if args.rate > 0:
            panel_sim.step_values(scene, rng, rate=args.rate)
        if drift:
            g = scene.gauges[drift[0]]
            target = g.v_min + drift[1] * (g.v_max - g.v_min)
            g.value = d_start + (target - d_start) * min(1.0, (k / args.fps) / drift[2])
        # лёгкое покачивание камеры — проверка компенсации сдвига кадра
        shift = (0.01 * ((k // 50) % 2), 0.0)
        frame, _ = panel_sim.render_panel(scene, shift=shift, noise_sigma=1.5, seed=k)
        writer.write(frame)
    writer.release()
    legend = [{"index": i, "code": g.code, "v_min": g.v_min, "v_max": g.v_max, "unit": g.unit,
               "calibration": g.calibration, "cx": g.cx, "cy": g.cy, "r": g.r,
               "value_last": round(g.value, 6)} for i, g in enumerate(scene.gauges)]
    info = {"file": str(out), "frames": frames, "fps": args.fps, "rate": args.rate, "synthetic": True,
            "drift": {"index": drift[0], "start": d_start, "to_frac": drift[1], "minutes": drift[2] / 60.0}
            if drift else None, "gauges": legend}
    out.with_suffix(".json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
