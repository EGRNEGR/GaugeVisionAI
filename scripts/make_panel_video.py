"""Демонстрационный видеофайл щита приборов для вкладки «Щит» (Multi-Gauge Vision).

Кадры синтетические (app/panel_sim.py) и в интерфейсе так и подписываются: это стенд для показа
регистрации и сопровождения нескольких приборов одной камерой, а не фотография действующего объекта.
Файл пишется в каталог видеофайлов (data/videos, вне git) и подключается как источник video_file.

    python scripts/make_panel_video.py --gauges 8 --seconds 60
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
    args = ap.parse_args()

    scene = panel_sim.make_panel(args.gauges, seed=args.seed, size_jitter=0.3)
    out = args.out or config.get_videos_dir() / f"panel_{args.gauges:02d}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (scene.width, scene.height))
    if not writer.isOpened():
        print(f"не удалось открыть {out} на запись", file=sys.stderr)
        return 1
    rng = random.Random(args.seed)
    frames = int(args.seconds * args.fps)
    for k in range(frames):
        panel_sim.step_values(scene, rng, rate=0.004)
        # лёгкое покачивание камеры — проверка компенсации сдвига кадра
        shift = (0.01 * ((k // 50) % 2), 0.0)
        frame, _ = panel_sim.render_panel(scene, shift=shift, noise_sigma=1.5, seed=k)
        writer.write(frame)
    writer.release()
    legend = [{"index": i, "v_min": g.v_min, "v_max": g.v_max, "unit": g.unit} for i, g in enumerate(scene.gauges)]
    print(json.dumps({"file": str(out), "frames": frames, "gauges": legend}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
