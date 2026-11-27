"""
GaugeVision AI 3.1 — Воспроизводимое CPU-обучение компактных нейросетей стрелки:
  1) NeedleKeypointNet (Подход B2: keypoints center+tip + cyclic sin/cos + visibility)
  2) NeedleSegUNet     (Подход C2: пиксельная сегментация 0=фон, 1=риски, 2=стрелка + tip)

Строгий протокол без утечек:
  • TRAIN      = MeterFL модели M2 + M3 (435 реальных фото с масками и ключевыми точками)
                 + синтетический генератор (template_id 0..699, воспроизводит M1-блики, боковой свет, противовесы).
  • VALIDATION = MeterFL модель M5 (71 реальное фото невидимого прибора) + синтетика (template_id 700..799).
  • LEGACY / LOCKED FINAL при обучении и выборе эпох НЕ используются вообще.

Запуск:
  CUDA_VISIBLE_DEVICES="" GAUGEVISION_DEVICE=cpu python -m cv_next_gen.train_needle --epochs 28
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import random
import time
from typing import Any

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

from .models_needle import CROP_SIZE, NeedleKeypointNet, NeedleSegUNet, extract_angle_from_seg
from .synthetic_generator import render_dial_sample

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "reports" / "cv_next_gen" / "evidence" / "dataset_manifest.json"
METERFL_DIR = pathlib.Path(r"C:\Hakatons\gv_cv_validation\datasets\meterfl")
OUT_MODELS_DIR = REPO_ROOT / "models"
OUT_EVIDENCE_DIR = REPO_ROOT / "reports" / "cv_next_gen" / "evidence" / "training"


def _ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _crop_real_sample(rec: dict[str, Any], size: int = CROP_SIZE) -> tuple[np.ndarray, np.ndarray, dict[str, Any]] | None:
    """Вырезает квадратный кроп вокруг размеченного центра шкалы MeterFL (с запасом 1,28 радиуса)."""
    img_p = METERFL_DIR / "data" / rec["client"] / rec["side"] / rec["file"]
    mask_p = METERFL_DIR / "data" / "masks" / (pathlib.Path(rec["file"]).stem + ".png")
    if not img_p.exists() or not mask_p.exists() or not rec.get("center") or not rec.get("pointer_tip"):
        return None
    img = cv2.imread(str(img_p))
    mask = cv2.imread(str(mask_p), cv2.IMREAD_UNCHANGED)
    if img is None or mask is None:
        return None
    if mask.ndim == 3:
        mask = mask[:, :, 0]

    cx, cy = float(rec["center"][0]), float(rec["center"][1])
    tx, ty = float(rec["pointer_tip"][0]), float(rec["pointer_tip"][1])
    r = float(rec.get("tick_radius") or 0.0)
    if r <= 5.0:
        r = max(math.hypot(tx - cx, ty - cy) * 1.15, min(img.shape[:2]) * 0.35)
    half = r * 1.28

    # Аффинная матрица к квадрату size×size
    scale = size / (2.0 * half)
    M = np.array([
        [scale, 0.0, size / 2.0 - cx * scale],
        [0.0, scale, size / 2.0 - cy * scale],
    ], dtype=np.float64)
    crop_img = cv2.warpAffine(img, M, (size, size), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE)
    crop_mask = cv2.warpAffine(mask, M, (size, size), flags=cv2.INTER_NEAREST, borderValue=0)

    c_new = M @ np.array([cx, cy, 1.0])
    t_new = M @ np.array([tx, ty, 1.0])
    angle_deg = math.degrees(math.atan2(t_new[1] - c_new[1], t_new[0] - c_new[0])) % 360.0
    meta = {
        "center": [float(c_new[0]), float(c_new[1])],
        "tip": [float(t_new[0]), float(t_new[1])],
        "angle_deg": angle_deg,
        "visibility": 1.0,
        "source": f"MeterFL:{rec['instrument_group']}",
    }
    return crop_img, crop_mask, meta


class NeedleDataset(Dataset):
    """Объединённый датасет реальных кропов (MeterFL) и синтетических кропов с 360° аугментацией."""

    def __init__(
        self,
        real_samples: list[tuple[np.ndarray, np.ndarray, dict[str, Any]]],
        n_synth: int,
        template_range: tuple[int, int],
        seed: int,
        augment: bool = True,
        occlude_prob: float = 0.08,
    ) -> None:
        self.real_samples = real_samples
        self.augment = augment
        self.occlude_prob = occlude_prob
        self.rng = random.Random(seed)
        self.synth_samples: list[tuple[np.ndarray, np.ndarray, dict[str, Any]]] = []
        lo_t, hi_t = template_range
        for i in range(n_synth):
            tid = lo_t + (i % (hi_t - lo_t))
            occ = (i % 14 == 0) if occlude_prob > 0 else False
            img, msk, meta = render_dial_sample(size=CROP_SIZE, template_id=tid, seed=seed * 10000 + i, hard_mode=True, occlude=occ)
            self.synth_samples.append((img, msk, meta))
        # Балансируем реальные и синтетические (реальные повторяем 3x при обучении)
        self.items: list[tuple[np.ndarray, np.ndarray, dict[str, Any]]] = []
        rep = 3 if augment else 1
        for _ in range(rep):
            self.items.extend(self.real_samples)
        self.items.extend(self.synth_samples)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        img, mask, meta = self.items[idx]
        img = img.copy()
        mask = mask.copy()
        cx, cy = float(meta["center"][0]), float(meta["center"][1])
        tx, ty = float(meta["tip"][0]), float(meta["tip"][1])
        vis = float(meta["visibility"])
        s = CROP_SIZE

        if self.augment:
            # 1. Случайный поворот на 0..360° + сдвиг/масштаб (имитация ошибки детектора!)
            rot = self.rng.uniform(0.0, 360.0)
            sc = self.rng.uniform(0.86, 1.14)
            dx = self.rng.uniform(-0.08 * s, 0.08 * s)
            dy = self.rng.uniform(-0.08 * s, 0.08 * s)
            M = cv2.getRotationMatrix2D((s / 2.0, s / 2.0), rot, sc)
            M[0, 2] += dx
            M[1, 2] += dy
            img = cv2.warpAffine(img, M, (s, s), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            mask = cv2.warpAffine(mask, M, (s, s), flags=cv2.INTER_NEAREST, borderValue=0)
            c_pt = M @ np.array([cx, cy, 1.0])
            t_pt = M @ np.array([tx, ty, 1.0])
            cx, cy = float(c_pt[0]), float(c_pt[1])
            tx, ty = float(t_pt[0]), float(t_pt[1])

            # 2. Фотометрическая аугментация (боковой свет, яркость/контраст, блик, шум)
            alpha = self.rng.uniform(0.65, 1.35)
            beta = self.rng.uniform(-28.0, 28.0)
            img_f = img.astype(np.float32) * alpha + beta
            if self.rng.random() < 0.35:
                ang = self.rng.uniform(0, 2 * math.pi)
                yy, xx = np.mgrid[0:s, 0:s].astype(np.float32) / float(s) - 0.5
                grad = (xx * math.cos(ang) + yy * math.sin(ang)) * self.rng.uniform(0.18, 0.45)
                img_f = img_f * (1.0 + grad[:, :, None])
            if self.rng.random() < 0.25:
                p0 = (self.rng.randint(0, s), self.rng.randint(0, s))
                p1 = (self.rng.randint(0, s), self.rng.randint(0, s))
                g = np.zeros((s, s), dtype=np.float32)
                cv2.line(g, p0, p1, self.rng.uniform(50, 120), self.rng.randint(4, 14), cv2.LINE_AA)
                g = cv2.GaussianBlur(g, (0, 0), 3.0)
                img_f += g[:, :, None]
            img = np.clip(img_f, 0, 255).astype(np.uint8)
            if self.rng.random() < 0.25:
                img = cv2.GaussianBlur(img, (3, 3), self.rng.uniform(0.5, 1.2))
            # Имитация непригодного кадра (темнота/засветка/перекрытие) с малой вероятностью
            if vis > 0.5 and self.rng.random() < self.occlude_prob:
                kind = self.rng.choice(["dark", "over", "occ"])
                if kind == "dark":
                    img = (img.astype(np.float32) * 0.05).astype(np.uint8)
                elif kind == "over":
                    img = np.clip(238.0 + img.astype(np.float32) * 0.06, 0, 255).astype(np.uint8)
                else:
                    cv2.rectangle(img, (0, 0), (int(s * 0.72), s), (28, 30, 32), -1)
                mask[:] = 0
                vis = 0.0

        # Координаты в [0, 1] и циклический угол
        cx_n = float(np.clip(cx / s, 0.0, 1.0))
        cy_n = float(np.clip(cy / s, 0.0, 1.0))
        tx_n = float(np.clip(tx / s, 0.0, 1.0))
        ty_n = float(np.clip(ty / s, 0.0, 1.0))
        ang_rad = math.atan2(ty - cy, tx - cx)
        sincos = np.array([math.sin(ang_rad), math.cos(ang_rad)], dtype=np.float32)
        coords = np.array([[cx_n, cy_n], [tx_n, ty_n]], dtype=np.float32)

        # Маска 80×80 и гауссова карта кончика 80×80
        ms = s // 2
        mask_small = cv2.resize(mask, (ms, ms), interpolation=cv2.INTER_NEAREST).astype(np.int64)
        tip_map = np.zeros((ms, ms), dtype=np.float32)
        if vis > 0.5:
            gy, gx = np.mgrid[0:ms, 0:ms].astype(np.float32)
            tip_map = np.exp(-((gx - tx_n * ms) ** 2 + (gy - ty_n * ms) ** 2) / (2.0 * 3.5 ** 2))

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        rgb = (rgb - 0.5) / 0.5
        x_t = torch.from_numpy(np.transpose(rgb, (2, 0, 1)))
        return {
            "x": x_t,
            "coords": torch.from_numpy(coords),
            "sincos": torch.from_numpy(sincos),
            "vis": torch.tensor(vis, dtype=torch.float32),
            "mask": torch.from_numpy(mask_small),
            "tip_map": torch.from_numpy(tip_map[None, ...]),
        }


def eval_keypoint_model(model: NeedleKeypointNet, loader: DataLoader) -> dict[str, float]:
    model.eval()
    ang_errs_kpt: list[float] = []
    ang_errs_sc: list[float] = []
    vis_preds: list[int] = []
    vis_gts: list[int] = []
    with torch.no_grad():
        for batch in loader:
            coords, sincos, vis_logit = model(batch["x"])
            gt_coords = batch["coords"].numpy()
            gt_vis = batch["vis"].numpy()
            pred_c = coords.numpy()
            pred_sc = sincos.numpy()
            pred_v = torch.sigmoid(vis_logit).numpy()
            for i in range(len(gt_vis)):
                vis_gts.append(int(gt_vis[i] > 0.5))
                vis_preds.append(int(pred_v[i] > 0.5))
                if gt_vis[i] > 0.5:
                    gt_a = math.degrees(math.atan2(gt_coords[i, 1, 1] - gt_coords[i, 0, 1],
                                                   gt_coords[i, 1, 0] - gt_coords[i, 0, 0])) % 360.0
                    k_a = math.degrees(math.atan2(pred_c[i, 1, 1] - pred_c[i, 0, 1],
                                                  pred_c[i, 1, 0] - pred_c[i, 0, 0])) % 360.0
                    s_a = math.degrees(math.atan2(pred_sc[i, 0], pred_sc[i, 1])) % 360.0
                    ang_errs_kpt.append(_ang_diff(k_a, gt_a))
                    ang_errs_sc.append(_ang_diff(s_a, gt_a))
    vis_acc = sum(p == g for p, g in zip(vis_preds, vis_gts)) / max(1, len(vis_gts))
    return {
        "mae_deg_kpt": round(float(np.mean(ang_errs_kpt)), 3),
        "med_deg_kpt": round(float(np.median(ang_errs_kpt)), 3),
        "p95_deg_kpt": round(float(np.percentile(ang_errs_kpt, 95)), 3),
        "gross_15deg_pct": round(100.0 * float(np.mean(np.array(ang_errs_kpt) > 15.0)), 2),
        "mae_deg_sincos": round(float(np.mean(ang_errs_sc)), 3),
        "vis_acc": round(vis_acc, 4),
    }


def eval_seg_model(model: NeedleSegUNet, loader: DataLoader) -> dict[str, float]:
    model.eval()
    ang_errs: list[float] = []
    inter = union = 0.0
    with torch.no_grad():
        for batch in loader:
            seg_logits, tip_logits = model(batch["x"])
            probs = F.softmax(seg_logits, dim=1).numpy()
            t_np = tip_logits[:, 0].numpy()
            gt_mask = batch["mask"].numpy()
            gt_coords = batch["coords"].numpy()
            gt_vis = batch["vis"].numpy()
            for i in range(len(gt_vis)):
                if gt_vis[i] <= 0.5:
                    continue
                pred_ptr = probs[i, 2] >= 0.35
                gt_ptr = gt_mask[i] == 2
                inter += float(np.logical_and(pred_ptr, gt_ptr).sum())
                union += float(np.logical_or(pred_ptr, gt_ptr).sum())
                res = extract_angle_from_seg(probs[i], t_np[i], center_norm=(gt_coords[i, 0, 0], gt_coords[i, 0, 1]))
                if res["angle_deg"] is not None:
                    gt_a = math.degrees(math.atan2(gt_coords[i, 1, 1] - gt_coords[i, 0, 1],
                                                   gt_coords[i, 1, 0] - gt_coords[i, 0, 0])) % 360.0
                    ang_errs.append(_ang_diff(res["angle_deg"], gt_a))
    iou = inter / max(1.0, union)
    return {
        "pointer_iou": round(iou, 4),
        "valid_rate": round(len(ang_errs) / max(1, sum(int(b["vis"].sum()) for b in loader)), 4),
        "mae_deg_seg": round(float(np.mean(ang_errs)) if ang_errs else 999.0, 3),
        "med_deg_seg": round(float(np.median(ang_errs)) if ang_errs else 999.0, 3),
        "p95_deg_seg": round(float(np.percentile(ang_errs, 95)) if ang_errs else 999.0, 3),
        "gross_15deg_pct": round(100.0 * float(np.mean(np.array(ang_errs) > 15.0)) if ang_errs else 100.0, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=26)
    ap.add_argument("--n-synth-train", type=int, default=1400)
    ap.add_argument("--n-synth-val", type=int, default=180)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.set_num_threads(min(12, os.cpu_count() or 4))

    OUT_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MODELS_DIR.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    train_real = []
    val_real = []
    for rec in manifest["items"]:
        if rec["split"] == "TRAIN":
            s = _crop_real_sample(rec)
            if s is not None:
                train_real.append(s)
        elif rec["split"] == "VALIDATION":
            s = _crop_real_sample(rec)
            if s is not None:
                val_real.append(s)

    print(f"Loaded real samples: TRAIN={len(train_real)} (M2+M3), VAL={len(val_real)} (M5)", flush=True)
    ds_train = NeedleDataset(train_real, args.n_synth_train, (0, 700), seed=args.seed, augment=True)
    ds_val_real = NeedleDataset(val_real, 0, (700, 800), seed=args.seed + 1, augment=False, occlude_prob=0.0)
    ds_val_mix = NeedleDataset(val_real, args.n_synth_val, (700, 800), seed=args.seed + 2, augment=False, occlude_prob=0.08)

    dl_train = DataLoader(ds_train, batch_size=args.batch, shuffle=True, num_workers=0, drop_last=True)
    dl_val_real = DataLoader(ds_val_real, batch_size=args.batch, shuffle=False, num_workers=0)
    dl_val_mix = DataLoader(ds_val_mix, batch_size=args.batch, shuffle=False, num_workers=0)

    # ------------------------------------------------------------------
    # 1. Обучение NeedleKeypointNet (Подход B2)
    # ------------------------------------------------------------------
    print("\n=== Training NeedleKeypointNet (Approach B2) ===", flush=True)
    t0 = time.time()
    kpt_model = NeedleKeypointNet(base_ch=24)
    opt = torch.optim.AdamW(kpt_model.parameters(), lr=2.5e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs, eta_min=1e-4)
    best_score = 1e9
    kpt_history = []
    kpt_path = OUT_MODELS_DIR / "needle_keypoint_v31.pt"

    for ep in range(1, args.epochs + 1):
        kpt_model.train()
        tot_loss = 0.0
        for b in dl_train:
            opt.zero_grad()
            coords, sincos, vis_logit = kpt_model(b["x"])
            vis = b["vis"]
            v_mask = (vis > 0.5).float()
            n_vis = v_mask.sum().clamp(min=1.0)
            loss_kpt = (F.smooth_l1_loss(coords, b["coords"], reduction="none").mean(dim=(1, 2)) * v_mask).sum() / n_vis
            loss_sc = ((1.0 - (sincos * b["sincos"]).sum(dim=-1)) * v_mask).sum() / n_vis
            loss_vis = F.binary_cross_entropy_with_logits(vis_logit, vis)
            loss = 12.0 * loss_kpt + 1.5 * loss_sc + 0.5 * loss_vis
            loss.backward()
            opt.step()
            tot_loss += float(loss.item())
        sched.step()
        m_real = eval_keypoint_model(kpt_model, dl_val_real)
        m_mix = eval_keypoint_model(kpt_model, dl_val_mix)
        score = 0.65 * m_real["mae_deg_kpt"] + 0.35 * m_mix["mae_deg_kpt"]
        kpt_history.append({"epoch": ep, "loss": round(tot_loss / len(dl_train), 4), "val_real_M5": m_real, "val_mix": m_mix})
        if score < best_score:
            best_score = score
            torch.save({"arch": "NeedleKeypointNet", "base_ch": 24, "crop_size": CROP_SIZE,
                        "state_dict": kpt_model.state_dict(), "val_real_M5": m_real, "val_mix": m_mix,
                        "epoch": ep, "seed": args.seed}, str(kpt_path))
        if ep in (1, 5, 10, 15, 20, args.epochs) or score == best_score:
            print(f"  [KPT] ep {ep:2d}/{args.epochs} loss={tot_loss/len(dl_train):.4f} "
                  f"M5_MAE={m_real['mae_deg_kpt']:.2f}° M5_med={m_real['med_deg_kpt']:.2f}° "
                  f"mix_MAE={m_mix['mae_deg_kpt']:.2f}° vis_acc={m_mix['vis_acc']:.3f}", flush=True)
    kpt_secs = round(time.time() - t0, 1)

    # ------------------------------------------------------------------
    # 2. Обучение NeedleSegUNet (Подход C2)
    # ------------------------------------------------------------------
    print("\n=== Training NeedleSegUNet (Approach C2) ===", flush=True)
    t1 = time.time()
    seg_model = NeedleSegUNet(base_ch=20)
    opt_s = torch.optim.AdamW(seg_model.parameters(), lr=2.5e-3, weight_decay=1e-4)
    sched_s = torch.optim.lr_scheduler.CosineAnnealingLR(opt_s, T_max=args.epochs, eta_min=1e-4)
    cls_w = torch.tensor([0.25, 1.5, 4.5], dtype=torch.float32)
    best_seg = 1e9
    seg_history = []
    seg_path = OUT_MODELS_DIR / "needle_seg_v31.pt"

    for ep in range(1, args.epochs + 1):
        seg_model.train()
        tot_loss = 0.0
        for b in dl_train:
            opt_s.zero_grad()
            seg_logits, tip_logits = seg_model(b["x"])
            loss_ce = F.cross_entropy(seg_logits, b["mask"], weight=cls_w)
            # Soft Dice по классу 2 (стрелка)
            p_ptr = F.softmax(seg_logits, dim=1)[:, 2]
            gt_ptr = (b["mask"] == 2).float()
            dice = 1.0 - (2.0 * (p_ptr * gt_ptr).sum() + 1.0) / (p_ptr.sum() + gt_ptr.sum() + 1.0)
            loss_tip = F.mse_loss(torch.sigmoid(tip_logits), b["tip_map"])
            loss = loss_ce + 1.5 * dice + 8.0 * loss_tip
            loss.backward()
            opt_s.step()
            tot_loss += float(loss.item())
        sched_s.step()
        m_real = eval_seg_model(seg_model, dl_val_real)
        m_mix = eval_seg_model(seg_model, dl_val_mix)
        score = 0.65 * m_real["mae_deg_seg"] + 0.35 * m_mix["mae_deg_seg"]
        seg_history.append({"epoch": ep, "loss": round(tot_loss / len(dl_train), 4), "val_real_M5": m_real, "val_mix": m_mix})
        if score < best_seg:
            best_seg = score
            torch.save({"arch": "NeedleSegUNet", "base_ch": 20, "crop_size": CROP_SIZE,
                        "state_dict": seg_model.state_dict(), "val_real_M5": m_real, "val_mix": m_mix,
                        "epoch": ep, "seed": args.seed}, str(seg_path))
        if ep in (1, 5, 10, 15, 20, args.epochs) or score == best_seg:
            print(f"  [SEG] ep {ep:2d}/{args.epochs} loss={tot_loss/len(dl_train):.4f} "
                  f"M5_IoU={m_real['pointer_iou']:.3f} M5_MAE={m_real['mae_deg_seg']:.2f}° "
                  f"mix_MAE={m_mix['mae_deg_seg']:.2f}°", flush=True)
    seg_secs = round(time.time() - t1, 1)

    summary = {
        "seed": args.seed,
        "epochs": args.epochs,
        "train_real_count": len(train_real),
        "val_real_M5_count": len(val_real),
        "n_synth_train": args.n_synth_train,
        "n_synth_val": args.n_synth_val,
        "keypoint_train_seconds": kpt_secs,
        "keypoint_sha256": hashlib.sha256(kpt_path.read_bytes()).hexdigest(),
        "keypoint_size_bytes": kpt_path.stat().st_size,
        "keypoint_best": min(kpt_history, key=lambda h: 0.65 * h["val_real_M5"]["mae_deg_kpt"] + 0.35 * h["val_mix"]["mae_deg_kpt"]),
        "seg_train_seconds": seg_secs,
        "seg_sha256": hashlib.sha256(seg_path.read_bytes()).hexdigest(),
        "seg_size_bytes": seg_path.stat().st_size,
        "seg_best": min(seg_history, key=lambda h: 0.65 * h["val_real_M5"]["mae_deg_seg"] + 0.35 * h["val_mix"]["mae_deg_seg"]),
    }
    (OUT_EVIDENCE_DIR / "training_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_EVIDENCE_DIR / "kpt_history.json").write_text(json.dumps(kpt_history, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_EVIDENCE_DIR / "seg_history.json").write_text(json.dumps(seg_history, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nTRAINING COMPLETE:", json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
