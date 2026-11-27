"""
Auto Calibration (NG-AC-01): безопасность экспериментального модуля.

Точность модуля оценивается отдельно (reports/next_generation/tests/autocal_eval.py); здесь — инварианты:
модуль выключен по умолчанию, не подключён к API, на пустом и синтетическом кадре не падает и либо
отказывает с причиной, либо возвращает предложение в формате калибровки vision.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("GAUGEVISION_DEVICE", "cpu")
os.environ.pop("GAUGEVISION_AUTOCAL", None)
os.environ["GAUGEVISION_DB"] = str(Path(tempfile.mkdtemp(prefix="gv_ac_test_")) / "x.db")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from app import autocal, config, panel_sim, vision  # noqa: E402


def test_disabled_and_not_wired() -> None:
    assert config.AUTOCAL_ENABLED is False
    for rel in ("app/main.py", "app/multigauge_service.py", "static/js/console/control.js"):
        assert "autocal" not in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_parse_number() -> None:
    cases = {"25": 25.0, "1,6": 1.6, "0.4": 0.4, "02": 0.2, "−5": -5.0, "MPa": None, "12810126": None, "1.6.": None}
    for text, want in cases.items():
        assert autocal.parse_number(text) == want, (text, autocal.parse_number(text))


def test_blank_frame_refuses() -> None:
    frame = np.full((480, 480, 3), 255, np.uint8)
    roi = vision.roi_from_ellipse(240, 240, 200, 200, 0.0, score=1.0, source="manual")
    pr = autocal.propose(frame, roi)
    assert not pr.ok and pr.reason, pr.reason
    json.dumps(pr.to_json())


def test_synthetic_dial_contract() -> None:
    scene = panel_sim.make_panel(1, seed=1)
    frame, ref = panel_sim.render_panel(scene)
    g = ref[0]
    roi = vision.roi_from_ellipse(g["cx"], g["cy"], g["r"], g["r"], 0.0, score=1.0, source="manual")
    pr = autocal.propose(frame, roi)
    out = pr.to_json()
    json.dumps(out)
    if pr.ok:
        cal = pr.calibration
        assert set(cal) == {"v_min", "theta_min", "v_max", "theta_max", "direction"}
        assert cal["direction"] in ("cw", "ccw") and cal["v_max"] > cal["v_min"]
        assert vision.angle_to_value(cal["theta_min"], cal) is not None
    else:
        assert pr.reason
    print(f"[synthetic] ok={pr.ok} reason={pr.reason} calibration={pr.calibration} ms={pr.ms:.0f}")


if __name__ == "__main__":
    test_disabled_and_not_wired()
    test_parse_number()
    if autocal.available():
        test_blank_frame_refuses()
        test_synthetic_dial_contract()
    else:
        print("rapidocr-onnxruntime не установлен: проверяется отказ без OCR")
        roi = vision.roi_from_ellipse(240, 240, 200, 200, 0.0, score=1.0, source="manual")
        pr = autocal.propose(np.full((480, 480, 3), 255, np.uint8), roi)
        assert not pr.ok and pr.reason == "ocr_unavailable"
    print("ALL AUTOCAL SAFETY TESTS PASSED")
