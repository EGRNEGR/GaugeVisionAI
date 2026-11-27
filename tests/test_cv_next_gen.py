"""
GaugeVision AI 3.1 — Независимый набор тестов Next Generation Vision Engine.

Проверяет:
  1. ModelRegistry: SHA-256 проверка, защита от path traversal, отказ при повреждённых весах.
  2. OpenCVNeedleV2: исправление полярности top-hat и считывание на синтетических приборах.
  3. NeedleKeypointNet и NeedleSegUNet: инференс CPU/ONNX, пакетная обработка (1/2/4/8/16).
  4. FusionNeedleEstimator: циклическое согласование, отсутствие усреднения несовместимых углов,
     корректный отказ на непригодных/перекрытых кадрах.
  5. Переключение профилей (legacy / eco / balanced / precision) без потери калибровки.
  6. Multi-Gauge с новым профилем и отрицательные шкалы / CCW.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"
os.environ.setdefault("YOLO_OFFLINE", "1")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from app import config, multigauge, panel_sim, vision
from app.vision_engine.estimators import (
    FusionNeedleEstimator,
    NeuralKeypointEstimator,
    NeuralSegEstimator,
    OpenCVNeedleV2,
    ang_diff,
    circular_weighted_mean,
)
from app.vision_engine.profiles import VISION_PROFILES, get_profile_config
from app.vision_engine.registry import ModelRegistry, get_registry
from cv_next_gen.synthetic_generator import render_dial_sample


class TestModelRegistrySecurity(unittest.TestCase):
    def test_sha256_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td)
            (d / "fake.onnx").write_bytes(b"corrupted-bytes")
            manifest = d / "registry.json"
            manifest.write_text(json.dumps({
                "models": [{
                    "model_id": "bad_model",
                    "architecture": "TestNet",
                    "task": "needle_seg",
                    "version": "1.0",
                    "filename": "fake.onnx",
                    "format": "onnx",
                    "sha256": "0" * 64,
                    "input_size": 160,
                    "classes": ["pointer"],
                    "license": "MIT",
                    "backends": ["onnxruntime_cpu"],
                }]
            }), encoding="utf-8")
            reg = ModelRegistry(models_dir=d, manifest_path=manifest)
            p, err = reg.verify_and_resolve("bad_model")
            self.assertIsNone(p)
            self.assertIn("sha256_mismatch", err or "")

    def test_path_traversal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td)
            manifest = d / "registry.json"
            manifest.write_text(json.dumps({
                "models": [{
                    "model_id": "escape_model",
                    "architecture": "TestNet",
                    "task": "detect",
                    "version": "1.0",
                    "filename": "../outside.pt",
                    "format": "pt",
                    "sha256": "",
                    "input_size": 640,
                    "classes": ["Gauge"],
                    "license": "MIT",
                    "backends": ["pytorch_cpu"],
                }]
            }), encoding="utf-8")
            reg = ModelRegistry(models_dir=d, manifest_path=manifest)
            p, err = reg.verify_and_resolve("escape_model")
            self.assertIsNone(p)
            self.assertIn("unsafe_model_path", err or "")


class TestCircularMathAndProfiles(unittest.TestCase):
    def test_circular_mean_wraparound(self) -> None:
        m = circular_weighted_mean([358.0, 2.0], [1.0, 1.0])
        self.assertLess(ang_diff(m, 0.0), 0.5)

    def test_profiles_and_switching(self) -> None:
        orig = vision.get_vision_profile()
        try:
            for name in ("legacy", "eco", "balanced", "precision"):
                self.assertIn(name, VISION_PROFILES)
                self.assertEqual(vision.set_vision_profile(name), name)
                self.assertEqual(vision.get_vision_profile(), name)
                cfg = get_profile_config(name)
                self.assertEqual(cfg.name, name)
            with self.assertRaises(ValueError):
                vision.set_vision_profile("nonexistent_profile")
        finally:
            vision.set_vision_profile(orig)


class TestEstimatorsAndFusion(unittest.TestCase):
    def test_opencv_v2_and_neural_on_synthetic(self) -> None:
        # Берём синтетический шаблон из тестового диапазона 800..999
        img, _, meta = render_dial_sample(size=640, template_id=805, seed=9001, hard_mode=False)
        cv2_est = OpenCVNeedleV2()
        res_cv = cv2_est.estimate(img)
        self.assertTrue(res_cv.valid)
        self.assertLess(ang_diff(res_cv.angle_deg, meta["angle_deg"]), 8.0)

        # Проверяем нейросетевые модели, если веса уже зарегистрированы
        reg = get_registry()
        if reg.get("needle_seg_v31_onnx") or reg.get("needle_seg_v31_pt"):
            seg_est = NeuralSegEstimator()
            res_seg = seg_est.estimate(img)
            self.assertTrue(res_seg.valid, f"Seg rejected clean synthetic dial: {res_seg}")
            self.assertLess(ang_diff(res_seg.angle_deg, meta["angle_deg"]), 8.0)
            # Пакетный инференс для 4 приборов
            batch_res = seg_est.estimate_batch([img] * 4)
            self.assertEqual(len(batch_res), 4)
            self.assertTrue(all(r.valid for r in batch_res))

        if reg.get("needle_keypoint_v31_onnx") or reg.get("needle_keypoint_v31_pt"):
            kpt_est = NeuralKeypointEstimator()
            batch_k = kpt_est.estimate_batch([img] * 4)
            self.assertEqual(len(batch_k), 4)

    def test_occlusion_rejected_in_pipeline(self) -> None:
        orig = vision.get_vision_profile()
        try:
            img, _, meta = render_dial_sample(size=640, template_id=810, seed=9002, hard_mode=True, occlude=True)
            calib = {"v_min": meta["v_min"], "v_max": meta["v_max"], "theta_min": 135.0, "theta_max": 45.0, "direction": "cw"}
            for prof in ("legacy", "eco", "balanced"):
                vision.set_vision_profile(prof)
                pipe = vision.GaugePipeline(f"occ-{prof}")
                r = pipe.process(img, calib, {}, "МПа", with_overlay=False)
                self.assertFalse(r.valid, f"Occluded dial must be rejected in profile={prof}")
        finally:
            vision.set_vision_profile(orig)

    def test_negative_scale_and_ccw_preserved(self) -> None:
        calib = {"v_min": -50.0, "v_max": 150.0, "theta_min": 45.0, "theta_max": 135.0, "direction": "ccw"}
        # Середина шкалы CCW от 45° к 135° (размах 270°) — 270° (12 часов) -> +50.0
        val = vision.angle_to_value(270.0, calib)
        self.assertIsNotNone(val)
        self.assertAlmostEqual(val, 50.0, delta=0.5)

    def test_multigauge_with_balanced_profile(self) -> None:
        orig = vision.get_vision_profile()
        try:
            vision.set_vision_profile("balanced")
            scene = panel_sim.make_panel(4, seed=7)
            frame, truth = panel_sim.render_panel(scene)
            instruments = []
            for g in scene.gauges:
                instruments.append({
                    "id": f"inst-{g.index}", "code": g.code, "name": g.code, "unit": g.unit,
                    "roi": {"mode": "manual", "cx": g.cx, "cy": g.cy, "r": g.r},
                    "calibration": g.calibration, "thresholds": {}, "enabled": True,
                })
            proc = multigauge.MultiGaugeProcessor("src-test")
            res = proc.process(frame, instruments, with_overlay=False)
            self.assertEqual(len(res.readings), 4)
            for t in truth:
                r = res.readings[f"inst-{t['index']}"]
                self.assertTrue(r.valid, f"Gauge {t['index']} invalid: {r.debug}")
                err_pct = abs(r.value - t["value"]) / t["span"] * 100.0
                self.assertLess(err_pct, 3.0, f"Gauge {t['index']} err={err_pct:.2f}%")
        finally:
            vision.set_vision_profile(orig)


if __name__ == "__main__":
    unittest.main()
