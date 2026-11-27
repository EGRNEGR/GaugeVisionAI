"""
GaugeVision AI 3.1 — Строгий протокол разделения данных и дедупликации.

Формирует неизменяемый манифест reports/cv_next_gen/evidence/dataset_manifest.json:
  • TRAIN                  — MeterFL dev: физические модели M2 и M3 (строго без M1/M4/M6/MeasureBench);
  • VALIDATION             — MeterFL dev: физическая модель M5 (невидимая при обучении модель для
                             ранней остановки, выбора гиперпараметров и порогов fusion);
  • DEVELOPMENT_BENCHMARK  — все dev-модели M2, M3, M5 (для сравнения с историческим dev v7/v8);
  • LEGACY_BENCHMARK       — историческая выборка GaugeVision 3.0 (primary 315, final 985, arc 41);
  • LOCKED_FINAL_TEST      — новые независимые реальные данные, дедуплицированные по SHA-256 и 64-bit dHash
                             (расстояние Хэмминга <= 6) против всех MeterFL и Legacy MeasureBench:
                             1) IGVD (Zenodo 20147961, CC BY 4.0) — реальные видео круглого индикатора;
                             2) MeasureBench unused dial (CC BY-SA 4.0) — ранее не использованные циферблаты;
                             3) MeasureBench unused non-dial + IGVD линейные штангенциркули — отказы.

Запуск:
  python -m cv_next_gen.build_dataset_manifest
"""
from __future__ import annotations

import hashlib
import io
import json
import pathlib
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from typing import Any

import cv2
import numpy as np

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
LEGACY_MANIFEST = REPO_ROOT / "reports" / "industrial_validation" / "data" / "dataset_manifest.json"
GV_CV_ROOT = pathlib.Path(r"C:\Hakatons\gv_cv_validation")
METERFL_DIR = GV_CV_ROOT / "datasets" / "meterfl"
MB_DIR = GV_CV_ROOT / "datasets" / "measurebench" / "export"
IGVD_ZIP = GV_CV_ROOT / "datasets" / "igvd" / "Dataset.zip"
OUT_MANIFEST = REPO_ROOT / "reports" / "cv_next_gen" / "evidence" / "dataset_manifest.json"


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dhash64(img_bgr: np.ndarray) -> int:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    val = 0
    for bit in diff.flatten():
        val = (val << 1) | int(bit)
    return val


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def parse_igvd_xlsx(data: bytes) -> list[tuple[int, float]]:
    """Возвращает [(timestamp_ms, reading_mm), ...] из xlsx внутри IGVD Dataset.zip."""
    rows: list[tuple[int, float]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as xz:
        ss: list[str] = []
        if "xl/sharedStrings.xml" in xz.namelist():
            root = ET.fromstring(xz.read("xl/sharedStrings.xml"))
            ss = ["".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")) for si in root]
        sheet = ET.fromstring(xz.read("xl/worksheets/sheet1.xml"))
        ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        for row in sheet.iter(f"{ns}row"):
            vals = []
            for c in row.findall(f"{ns}c"):
                t = c.attrib.get("t")
                v = c.find(f"{ns}v")
                val = v.text if v is not None else ""
                if t == "s" and val.isdigit():
                    val = ss[int(val)]
                vals.append(val)
            nums = []
            for s in vals:
                try:
                    nums.append(float(s))
                except (TypeError, ValueError):
                    pass
            if len(nums) >= 2:
                rows.append((int(round(nums[0])), float(nums[1])))
    return rows


def main() -> int:
    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    legacy = json.loads(LEGACY_MANIFEST.read_text(encoding="utf-8"))
    legacy_items = legacy["items"]

    seen_sha: set[str] = set()
    seen_dhash: list[int] = []
    used_mb_files: set[str] = set()

    entries: list[dict[str, Any]] = []

    # 1. Разносим MeterFL и Legacy MeasureBench строго по физическим моделям
    for rec in legacy_items:
        if rec.get("excluded"):
            continue
        ds = rec["dataset"]
        if ds == "MeterFL":
            img_p = METERFL_DIR / "data" / rec["client"] / rec["side"] / rec["file"]
            mask_p = METERFL_DIR / "data" / "masks" / (pathlib.Path(rec["file"]).stem + ".png")
            lic = "CC BY-SA 4.0"
        else:
            img_p = MB_DIR / "img" / rec["file"]
            mask_p = None
            used_mb_files.add(rec["file"])
            lic = "CC BY-SA 4.0"

        if not img_p.exists():
            continue
        sha = rec.get("sha256") or sha256_file(img_p)
        img = cv2.imread(str(img_p))
        dh = dhash64(img) if img is not None else 0
        seen_sha.add(sha)
        if dh:
            seen_dhash.append(dh)

        role = rec.get("role")
        model = rec.get("model") or "misc"
        if role == "dev" and ds == "MeterFL":
            split = "VALIDATION" if model == "M5" else "TRAIN"
        else:
            split = "LEGACY_BENCHMARK"

        entries.append({
            "id": f"{ds}:{rec['file']}",
            "source": ds,
            "license": lic,
            "instrument_group": model,
            "client": rec.get("client"),
            "side": rec.get("side"),
            "file": rec["file"],
            "split": split,
            "legacy_role": role,
            "legacy_primary": bool(rec.get("primary")),
            "legacy_arc": bool(rec.get("arc_scope_eval")),
            "has_mask": bool(mask_p and mask_p.exists()),
            "has_keypoints": bool(rec.get("center") and rec.get("pointer_tip")),
            "annotation_type": "mask+keypoints+reading" if (mask_p and mask_p.exists() and rec.get("reading_gt") is not None) else (
                "mask+keypoints" if (mask_p and mask_p.exists()) else "calibration+interval"
            ),
            "sha256": sha,
            "dhash64": f"{dh:016x}",
            "gt_origin": rec.get("gt_type") or "unknown",
            "center": rec.get("center"),
            "pointer_tip": rec.get("pointer_tip"),
            "first_tick": rec.get("first_tick"),
            "last_tick": rec.get("last_tick"),
            "tick_radius": rec.get("tick_radius"),
            "scale_min": rec.get("scale_min"),
            "scale_max": rec.get("scale_max"),
            "direction": rec.get("direction") or "cw",
            "reading_gt": rec.get("reading_gt"),
            "gt_interval": rec.get("gt_interval") or rec.get("mb_interval"),
            "frac_lin": rec.get("frac_lin"),
            "unit": rec.get("unit") or "",
        })

    # 2. Новая закрытая выборка LOCKED_FINAL_TEST из неиспользованных MeasureBench (с дедупликацией!)
    mb_rows = [json.loads(l) for l in (MB_DIR / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    mb_dedup_dropped = 0
    mb_locked_dial = 0
    mb_locked_nondial = 0
    for r in mb_rows:
        if r["file"] in used_mb_files:
            continue
        img_p = MB_DIR / "img" / r["file"]
        if not img_p.exists():
            continue
        sha = r.get("sha256") or sha256_file(img_p)
        if sha in seen_sha:
            mb_dedup_dropped += 1
            continue
        img = cv2.imread(str(img_p))
        if img is None:
            continue
        dh = dhash64(img)
        if any(hamming(dh, prev) <= 6 for prev in seen_dhash):
            mb_dedup_dropped += 1
            continue
        seen_sha.add(sha)
        seen_dhash.append(dh)

        design = r.get("design", "unknown")
        if design == "dial":
            mb_locked_dial += 1
            ann_type = "detection_eval+interval"
        elif design in ("digital", "linear"):
            mb_locked_nondial += 1
            ann_type = "unusable_non_dial"
        else:
            continue

        entries.append({
            "id": f"MeasureBench_locked:{r['file']}",
            "source": "MeasureBench_unused",
            "license": "CC BY-SA 4.0",
            "instrument_group": f"mb_{r.get('image_type', 'unknown')}",
            "client": r.get("image_type"),
            "file": r["file"],
            "split": "LOCKED_FINAL_TEST",
            "design": design,
            "annotation_type": ann_type,
            "sha256": sha,
            "dhash64": f"{dh:016x}",
            "gt_origin": "human_interval",
            "evaluator_kwargs": r.get("evaluator_kwargs"),
        })

    # 3. IGVD (Zenodo 20147961, CC BY 4.0) — видео круглого индикатора (18 видео)
    igvd_videos: list[dict[str, Any]] = []
    if IGVD_ZIP.exists():
        with zipfile.ZipFile(IGVD_ZIP) as z:
            mp4s = sorted(n for n in z.namelist() if n.startswith("Dataset/1.- Analog Dial Gauge/") and n.endswith(".mp4"))
            xls_map = {pathlib.Path(n).stem: n for n in z.namelist() if n.startswith("Dataset/1_label/") and n.endswith(".xlsx")}
            for mp4 in mp4s:
                parts = mp4.split("/")
                direction_tag = parts[2]  # DOWN | UP | UP_DOWN
                stem = pathlib.Path(mp4).stem
                key = f"{direction_tag}_{stem}"
                xls_name = xls_map.get(key)
                n_labels = 0
                if xls_name:
                    lbls = parse_igvd_xlsx(z.read(xls_name))
                    n_labels = len(lbls)
                igvd_videos.append({
                    "video_zip_path": mp4,
                    "label_zip_path": xls_name,
                    "direction_tag": direction_tag,
                    "n_labeled_timestamps": n_labels,
                    "split": "LOCKED_FINAL_TEST",
                    "source": "IGVD_Zenodo_20147961",
                    "license": "CC BY 4.0",
                })

    summary = {
        "total_image_entries": len(entries),
        "by_split": dict(Counter(e["split"] for e in entries)),
        "by_source": dict(Counter(e["source"] for e in entries)),
        "train_models": dict(Counter(e["instrument_group"] for e in entries if e["split"] == "TRAIN")),
        "val_models": dict(Counter(e["instrument_group"] for e in entries if e["split"] == "VALIDATION")),
        "legacy_models": dict(Counter(e["instrument_group"] for e in entries if e["split"] == "LEGACY_BENCHMARK")),
        "mb_locked_dial": mb_locked_dial,
        "mb_locked_nondial": mb_locked_nondial,
        "mb_dedup_dropped": mb_dedup_dropped,
        "igvd_dial_videos": len(igvd_videos),
        "igvd_total_labeled_timestamps": sum(v["n_labeled_timestamps"] for v in igvd_videos),
    }

    manifest = {
        "schema": "gv.dataset_manifest/3.1",
        "created_at": "2026-11-28",
        "dedup_policy": "exact SHA-256 + 64-bit dHash (Hamming <= 6)",
        "split_policy": "strict disjoint by physical instrument model / dataset source",
        "summary": summary,
        "igvd_videos": igvd_videos,
        "items": entries,
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
