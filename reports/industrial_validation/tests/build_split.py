"""
Фиксация состава выборок REQ-CV-05 до любых изменений алгоритма.

Роли:
  • final — окончательная независимая проверка: модели приборов M1, M4, M6 из MeterFL целиком,
    снимки MeasureBench из MeterFL (кроме похожих на модели разработки), отобранные снимки
    MeasureBench вне MeterFL с ручной калибровкой;
  • dev   — разработка и настройка: модели M2, M3, M5 из MeterFL целиком.
Модель прибора — кластер эмбеддингов (group_instruments.py) с ручной проверкой контактных листов;
для снимков с человеческой разметкой шкалы модель уточняется по диапазону шкалы.

  python build_split.py --meterfl <dir> --measurebench <export_dir> --labels <labels.json>
                        --mb-annotations <mb_calibration.json> --out <dataset_manifest.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cv_gt  # noqa: E402

# Кластер k-means (k=16) → модель прибора, по контактным листам (README, раздел «Выборки»)
MODEL_OF_CLUSTER = {
    0: "M2", 15: "M2",                                   # HONGQI 0–25 МПа
    1: "M1", 3: "M1", 4: "M1", 8: "M1", 9: "M1", 10: "M1", 11: "M1", 14: "M1",   # ELECALL 0–0,1 МПа
    5: "M4",                                             # 0–1,6 МПа, виброустойчивый
    6: "M3",                                             # 0–1 МПа, чёрный корпус, стенд
    7: "M5",                                             # мембранный 0–1,6 кПа
    12: "M6",                                            # −2…10 / 0–10 МПа, чёрный корпус
    2: "misc", 13: "misc",                               # разнородные снимки MeasureBench
}
MODEL_OF_SCALE = {(0, 0.1, "МПа"): "M1", (0, 25, "МПа"): "M2", (0, 1, "МПа"): "M3",
                  (0, 1.6, "МПа"): "M4", (0, 1.6, "кПа"): "M5", (0, 10, "МПа"): "M6"}
MODEL_NAMES = {
    "M1": "ELECALL 0–0,1 МПа (в руке, крупный план)", "M2": "HONGQI 0–25 МПа", "M3": "0–1 МПа, чёрный корпус (стенд)",
    "M4": "0–1,6 МПа виброустойчивый", "M5": "мембранный 0–1,6 кПа", "M6": "0–10 МПа, чёрный корпус",
}
FINAL_MODELS = {"M1", "M4", "M6"}
DEV_MODELS = {"M2", "M3", "M5"}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meterfl", required=True)
    ap.add_argument("--measurebench", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--mb-annotations", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    mb = cv_gt.load_measurebench(Path(args.measurebench))
    gts = cv_gt.load_meterfl(Path(args.meterfl))
    items = []
    hashes = {}
    for g in gts:
        cl = labels.get(g.file)
        model = MODEL_OF_CLUSTER.get(cl, "misc")
        if g.has_scale and g.source != "MeasureBench":
            key = (g.scale_min, g.scale_max, g.unit)
            if key in MODEL_OF_SCALE:
                model = MODEL_OF_SCALE[key]
        if g.source == "MeasureBench":
            role = "dev" if model in DEV_MODELS else "final"
            group = f"MB:{Path(g.file).stem}"
        else:
            role = "final" if model in FINAL_MODELS else "dev"
            group = model
        qid = Path(g.file).stem if g.source == "MeasureBench" else None
        interval = None
        if qid and qid in mb and mb[qid]["evaluator"] == "interval_matching":
            interval = mb[qid]["kw"].get("interval")
        excl = [f for f in g.flags if f in ("too_few_ticks", "no_pointer", "center_fit_failed", "endpoints_failed")]
        rec = g.to_json()
        rec.update(role=role, model=model, group=group, cluster=cl, sha256=sha256(g.path),
                   mb_interval=interval, mb_units=(mb[qid]["kw"].get("units") if qid in mb else None),
                   excluded=excl or None, calibration_source="meterfl_tick_polygons")
        items.append(rec)
        hashes[rec["sha256"]] = g.file
        img = cv2.imread(str(g.path))
        rec["dhash"] = cv_gt.dhash(img) if img is not None else None
    # Снимки MeasureBench вне MeterFL с ручной калибровкой
    ann = json.loads(Path(args.mb_annotations).read_text(encoding="utf-8"))
    mfl_dh = [(r["dhash"], r["file"]) for r in items if r["dhash"] is not None]
    for qid, a in ann["items"].items():
        r = mb[qid]
        p = Path(args.measurebench) / "img" / r["file"]
        img = cv2.imread(str(p))
        dh = cv_gt.dhash(img)
        dup = [f for h, f in mfl_dh if cv_gt.hamming(h, dh) <= 6]
        excl = list(a.get("exclude") or [])
        if dup:
            excl.append(f"near_duplicate_of:{dup[0]}")
        if r["sha256"] in hashes:
            excl.append(f"exact_duplicate_of:{hashes[r['sha256']]}")
        interval = r["kw"].get("interval") if r["evaluator"] == "interval_matching" else None
        items.append({
            "dataset": "MeasureBench", "file": r["file"], "width": r["width"], "height": r["height"],
            "client": r["image_type"], "side": None, "source": (r.get("meta_info") or {}).get("source"),
            "series": None, "center": a.get("center"), "first_tick": a.get("first"), "last_tick": a.get("last"),
            "scale_min": a.get("v_min"), "scale_max": a.get("v_max"), "direction": a.get("direction", "cw"),
            "unit": a.get("unit"), "reading_gt": None, "mb_interval": interval, "mb_units": r["kw"].get("units"),
            "role": "final", "model": "misc", "group": f"MB:{qid}", "cluster": None, "sha256": r["sha256"],
            "dhash": dh, "excluded": excl or None, "flags": [], "calibration_source": "manual_annotation",
            "annotation_note": a.get("note"), "tags": a.get("tags") or [],
            "gt_interval": a.get("gt_interval"),
        })
    # Основная независимая выборка: финальная роль и человеческий эталон (показание или интервал)
    for r in items:
        human = r.get("reading_gt") is not None or bool(r.get("mb_interval")) or bool(
            (ann["items"].get(Path(r["file"]).stem) or {}).get("gt_interval"))
        r["gt_type"] = ("human_reading" if r.get("reading_gt") is not None
                        else "mb_interval" if human else "mask_proxy")
        r["primary"] = bool(r["role"] == "final" and human and not r.get("excluded"))
    roles = {"primary": sum(1 for r in items if r["primary"])}
    for r in items:
        if not r.get("excluded"):
            roles.setdefault(r["role"], 0)
            roles[r["role"]] += 1
    manifest = {
        "frozen_note": "Состав зафиксирован до прогона конвейера и до любых изменений алгоритма.",
        "licenses": {"MeterFL": "CC BY-SA 4.0 (данные), github.com/weidazhaoooo/Meter-FL",
                     "MeasureBench": "CC BY-SA 4.0, huggingface.co/datasets/FlagEval/MeasureBench"},
        "models": MODEL_NAMES, "final_models": sorted(FINAL_MODELS), "dev_models": sorted(DEV_MODELS),
        "counts": roles, "items": items,
    }
    Path(args.out).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(roles, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
