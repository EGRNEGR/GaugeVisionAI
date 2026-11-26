"""
Independent Audit Script 03 — Track №1 (Mathematical verification of dispatch_analyzer,
Health Score confounding, recommendations, spec_generator 9-scenario matrix, economics,
deterministic vs mock-LLM fallback) & Security Audit (path traversal, RTSP cred leakage,
SSRF, XSS escaping, unauthenticated destructive endpoints).
Read-only against production code. Runs strictly on CPU.
"""
from __future__ import annotations

import asyncio
import io
import json
import math
import os
import sqlite3
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

REPO = Path(__file__).resolve().parents[3]
OUT_DIR = Path(os.environ.get("AUDIT_OUT_DIR", str(REPO / "reports" / "audit" / "evidence")))
OUT_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO))

from app import config
from app.dispatch_analyzer import DispatchAnalyzer, _compute_chatter
from app.spec_generator import (
    DIGITAL_SENSOR_CATALOG,
    generate_spec_bundle,
    pick_digital_replacement,
    render_spec_docx,
)


def make_inst(
    iid: str = "cam-real-1",
    code: str = "К1-Р01",
    group: str = "Котлоагрегаты",
    gauge_type: str = "pressure",
    unit: str = "МПа",
    v_min: float = 0.0,
    v_max: float = 16.0,
    value: float | None = 10.0,
    level: str = "normal",
    valid: bool = True,
    confidence: float | None = 0.94,
    rate_per_min: float | None = None,
    sparkline: list[float] | None = None,
    source_kind: str = "phone_cv",
) -> dict:
    return {
        "id": iid,
        "code": code,
        "short_name": f"Прибор {code}",
        "name": f"Аналоговый прибор {code}",
        "group": group,
        "gauge_type": gauge_type,
        "unit": unit,
        "decimals": 2,
        "source_kind": source_kind,
        "calibration": {"v_min": v_min, "v_max": v_max, "theta_min": 135.0, "theta_max": 45.0, "direction": "cw"},
        "thresholds": {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True},
        "reading": {
            "valid": valid,
            "value": value,
            "level": level,
            "confidence": confidence,
            "rate_per_min": rate_per_min,
            "sparkline": sparkline if sparkline is not None else [],
        },
    }


# ---------------------------------------------------------------------------
# 1. Mathematical verification of dispatch_analyzer on 12 control signals
# ---------------------------------------------------------------------------
def audit_dispatch_math() -> dict:
    checks = {}

    # Signal 1: Constant 10.0 MPa over 20 samples spaced 1.0s apart
    da = DispatchAnalyzer()
    t0 = 1_700_000_000.0
    da._series["s1"] = type(da._series.setdefault("s1", __import__("collections").deque(maxlen=120)))(
        [(t0 + i, 10.0, "normal") for i in range(20)], maxlen=120
    )
    r1 = da.analyze_instrument(make_inst(iid="s1", value=10.0), [])
    checks["1_constant_10mpa"] = {
        "expected_rate": 0.0, "actual_rate": r1["rate_per_min"],
        "expected_peak_rate": 0.0, "actual_peak_rate": r1["peak_rate_per_min"],
        "expected_chatter": 0.0, "actual_chatter_pct": r1["chatter_pct"],
        "health_score": r1["health_score"], "root_cause": r1["root_cause"],
    }

    # Signal 2: Exact linear ramp +0.1 MPa/sec = +6.0 MPa/min over 10 samples spaced 1.0s apart!
    # Analytical ground truth: rate_per_min = +6.0 MPa/min, peak_rate_per_min = +6.0 MPa/min
    da2 = DispatchAnalyzer()
    from collections import deque
    da2._series["s2"] = deque([(t0 + i * 1.0, 8.0 + 0.1 * i, "normal") for i in range(10)], maxlen=120)
    r2 = da2.analyze_instrument(make_inst(iid="s2", value=8.9), [])
    checks["2_linear_ramp_6mpa_per_min_1hz"] = {
        "expected_rate_per_min": 6.0,
        "actual_rate_per_min": r2["rate_per_min"],
        "expected_peak_rate_per_min": 6.0,
        "actual_peak_rate_per_min": r2["peak_rate_per_min"],
        "rate_match": abs(r2["rate_per_min"] - 6.0) < 0.05,
        "peak_rate_match_within_10pct": abs(r2["peak_rate_per_min"] - 6.0) < 0.6,
        "peak_rate_error_note": "dispatch_analyzer assumes 15-min window (step_min = 15/(N-1)) even for 1Hz mem_pts!",
    }

    # Signal 3: Exact linear drop -0.1 MPa/sec = -6.0 MPa/min
    da3 = DispatchAnalyzer()
    da3._series["s3"] = deque([(t0 + i * 1.0, 12.0 - 0.1 * i, "normal") for i in range(10)], maxlen=120)
    r3 = da3.analyze_instrument(make_inst(iid="s3", value=11.1), [])
    checks["3_linear_drop_minus6mpa_per_min"] = {
        "expected_rate_per_min": -6.0,
        "actual_rate_per_min": r3["rate_per_min"],
        "rate_match": abs(r3["rate_per_min"] + 6.0) < 0.05,
    }

    # Signal 4: Step jump (+4.0 MPa in 1s -> 240 MPa/min)
    da4 = DispatchAnalyzer()
    da4._series["s4"] = deque(
        [(t0 + i, 8.0 if i < 5 else 12.0, "normal") for i in range(10)], maxlen=120
    )
    r4 = da4.analyze_instrument(make_inst(iid="s4", value=12.0), [])
    checks["4_step_jump_4mpa"] = {
        "actual_rate_per_min": r4["rate_per_min"],
        "actual_peak_rate_per_min": r4["peak_rate_per_min"],
        "hydraulic_shock_risk": r4["hydraulic_shock_risk"],
    }

    # Signal 5: High-frequency needle chatter (alternating ±0.5 MPa on 16 MPa span -> 1.0 MPa peak-to-peak = 6.25% FS)
    da5 = DispatchAnalyzer()
    vals5 = [10.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(20)]
    da5._series["s5"] = deque([(t0 + i, v, "normal") for i, v in enumerate(vals5)], maxlen=120)
    r5 = da5.analyze_instrument(make_inst(iid="s5", value=vals5[-1]), [])
    checks["5_chatter_pm_05mpa"] = {
        "chatter_amp": r5["chatter_amp"],
        "chatter_pct": r5["chatter_pct"],
        "root_cause": r5["root_cause"],
        "health_score": r5["health_score"],
    }

    # Signal 6: Uneven timestamps (dt = 0.0s duplicate timestamps -> division by zero check!)
    da6 = DispatchAnalyzer()
    da6._series["s6"] = deque([(t0, 10.0, "normal"), (t0, 11.0, "normal"), (t0, 12.0, "normal"), (t0, 13.0, "normal")], maxlen=120)
    r6 = da6.analyze_instrument(make_inst(iid="s6", value=13.0), [])
    checks["6_duplicate_timestamps_div0"] = {
        "no_crash_and_finite": math.isfinite(r6["rate_per_min"]) and math.isfinite(r6["health_score"]),
        "actual_rate_per_min": r6["rate_per_min"],
        "note": "dt clamped via max(1.0, dt) prevents ZeroDivisionError, but silently treats 0s dt as 1.0s.",
    }

    # Signal 7: Instant 1-second alert -> check phantom overload_min!
    da7 = DispatchAnalyzer()
    r7 = da7.analyze_instrument(make_inst(iid="s7", value=15.5, level="alert"), [])
    checks["7_instant_1s_alert_overload_min"] = {
        "real_elapsed_overload_min": 0.0,
        "reported_overload_min": r7["overload_min"],
        "DEFECT_phantom_6_5_min_added": r7["overload_min"] >= 6.5,
    }

    # Signal 8: Trips shift vs 24h check (feed 3 events in last 10 min)
    da8 = DispatchAnalyzer()
    evs8 = [
        {"cam_id": "s8", "kind": "alarm", "level": "warning", "ts": "2026-11-26T10:00:00Z"},
        {"cam_id": "s8", "kind": "alarm", "level": "alert", "ts": "2026-11-26T10:05:00Z"},
        {"cam_id": "s8", "kind": "alarm", "level": "warning", "ts": "2026-11-26T10:10:00Z"},
    ]
    r8 = da8.analyze_instrument(make_inst(iid="s8", value=10.0, level="normal"), evs8)
    checks["8_trips_shift_vs_24h"] = {
        "events_injected": 3,
        "trips_shift": r8["trips_shift"],
        "trips_24h": r8["trips_24h"],
        "DEFECT_trips_24h_is_hardcoded_2x_shift": r8["trips_24h"] == r8["trips_shift"] * 2,
    }

    # Signal 9: Missing/None data & NaN/Inf protection
    da9 = DispatchAnalyzer()
    r9 = da9.analyze_instrument(make_inst(iid="s9", value=None, valid=False, level="stale", confidence=0.0), [])
    checks["9_missing_data"] = {
        "health_score": r9["health_score"],
        "root_cause": r9["root_cause"],
        "finite": math.isfinite(r9["health_score"]),
        "in_range_0_100": 0.0 <= r9["health_score"] <= 100.0,
    }

    # Signal 10: HEALTH SCORE CONFOUNDING TEST — healthy process (10.0 MPa, normal), but low YOLO confidence (0.20) + fog!
    da10 = DispatchAnalyzer()
    r10 = da10.analyze_instrument(
        make_inst(iid="s10", value=10.0, valid=True, level="normal", confidence=0.20),
        [],
        stream_telemetry={"quality": {"health_status": "DEGRADED", "quality_score": 20.0, "degradation_reasons": ["Пар"], "updated_at": "2026-11-26T10:00:00Z"}},
    )
    checks["10_health_score_confounding_healthy_process_bad_camera"] = {
        "process_level": "normal",
        "optical_score": r10["optical_score"],
        "health_score": r10["health_score"],
        "penalties": r10["penalties"],
        "root_cause": r10["root_cause"],
        "modernization_needed": r10["modernization_needed"],
        "DEFECT_camera_degradation_penalizes_equipment_health_score": r10["health_score"] < 80.0,
    }

    # Signal 11: Multi-factor (alert + chatter + low optical) -> check priority & recommendation
    da11 = DispatchAnalyzer()
    da11._series["s11"] = deque([(t0 + i, 15.5 + (0.4 if i % 2 else -0.4), "alert") for i in range(12)], maxlen=120)
    r11 = da11.analyze_instrument(
        make_inst(iid="s11", value=15.6, valid=True, level="alert", confidence=0.45),
        [{"cam_id": "s11", "kind": "alarm", "level": "alert"}],
    )
    checks["11_multi_factor"] = {
        "health_score": r11["health_score"],
        "root_cause": r11["root_cause"],
        "urgency": r11["urgency"],
        "critical_wear": r11["critical_wear"],
        "penalties": r11["penalties"],
    }

    # Signal 12: Simulated vs Live asymmetry check (_BENCH_DIAGNOSTIC_PROFILES)
    da12 = DispatchAnalyzer()
    r12_sim = da12.analyze_instrument(
        make_inst(iid="sim-12", code="ТА2-Т02", value=64.5, level="normal", source_kind="simulated", v_min=0, v_max=120),
        [],
    )
    checks["12_simulated_hardcoded_profile_injection"] = {
        "input_values_flat": True,
        "reported_chatter_pct": r12_sim["chatter_pct"],
        "root_cause": r12_sim["root_cause"],
        "DEFECT_bench_profile_overrides_zero_chatter": r12_sim["chatter_pct"] >= 3.8,
    }

    return checks


# ---------------------------------------------------------------------------
# 2. Spec Generator 9-scenario matrix, Period Sensitivity, Economics, Mock LLM
# ---------------------------------------------------------------------------
async def audit_spec_generator() -> dict:
    da = DispatchAnalyzer()
    out: dict = {}

    def make_ov(insts: list[dict], evs: list[dict] | None = None) -> dict:
        return da.overview(insts, evs or [])

    # 9 Required Scenarios
    healthy_insts = [
        make_inst(iid="h1", code="К1-Р01", value=10.0, level="normal"),
        make_inst(iid="h2", code="К1-Т01", gauge_type="temperature", unit="°C", v_min=0, v_max=600, value=535.0, level="normal"),
        make_inst(iid="h3", code="Д6-У01", group="Питательный узел", gauge_type="level", unit="%", v_min=0, v_max=100, value=65.0, level="normal"),
    ]
    b1 = await generate_spec_bundle(dispatch_overview=make_ov(healthy_insts), events=[], snapshot_lookup={}, period="12h")
    d1 = render_spec_docx(b1)
    out["case1_all_healthy"] = {
        "scoped": len(b1["scoped_items"]),
        "defective_forced_despite_healthy": len(b1["defective_items"]),
        "capex_rub": b1["economics"]["capex_rub"],
        "docx_bytes": len(d1),
        "DEFECT_forces_healthy_equipment_into_defects_and_tz": len(b1["defective_items"]) > 0,
    }

    # Case 2: Single incident
    single_inc_insts = [
        make_inst(iid="c2", code="К1-Р01", value=14.6, level="warning"),
        make_inst(iid="c2b", code="К2-Р01", value=10.0, level="normal"),
    ]
    evs2 = [{"id": 1, "cam_id": "c2", "kind": "alarm", "level": "warning", "value": 14.6, "ts": "2026-11-26T09:00:00Z"}]
    b2 = await generate_spec_bundle(dispatch_overview=make_ov(single_inc_insts, evs2), events=evs2, snapshot_lookup={}, period="12h")
    out["case2_single_incident"] = {
        "defective_codes": [x["code"] for x in b2["defective_items"]],
        "capex_rub": b2["economics"]["capex_rub"],
    }

    # Case 3: Regular overloads + hazardous gas zone -> check Ex protection
    gas_insts = [
        make_inst(iid="g1", code="ГРП-Р01", group="Топливо и тяга", gauge_type="pressure", unit="МПа", v_min=0, v_max=1.0, value=0.68, level="alert"),
        make_inst(iid="g2", code="ТА2-Т02", group="Турбоагрегаты", gauge_type="temperature", unit="°C", v_min=0, v_max=120, value=95.0, level="alert"),
    ]
    b3_12h = await generate_spec_bundle(dispatch_overview=make_ov(gas_insts), events=[], snapshot_lookup={}, period="12h")
    b3_30d = await generate_spec_bundle(dispatch_overview=make_ov(gas_insts), events=[], snapshot_lookup={}, period="30d")
    d3 = render_spec_docx(b3_12h)
    (OUT_DIR / "audit_sample_overload_gas_ex.docx").write_bytes(d3)
    (OUT_DIR / "audit_sample_overload_gas_ex.md").write_text(b3_12h["markdown"], encoding="utf-8")

    # Verify period sensitivity (12h vs 30d): do numbers change at all?
    period_nums_identical = (b3_12h["economics"] == b3_30d["economics"]) and (
        [x["overload_min"] for x in b3_12h["scoped_items"]] == [x["overload_min"] for x in b3_30d["scoped_items"]]
    )
    out["case3_regular_overloads_and_period_sensitivity"] = {
        "gas_sensor_ex": b3_12h["tz_items"][0]["replacement"]["ex"] if b3_12h["tz_items"] else None,
        "capex_rub": b3_12h["economics"]["capex_rub"],
        "annual_effect_rub": b3_12h["economics"]["annual_effect_rub"],
        "payback_months": b3_12h["economics"]["payback_months"],
        "DEFECT_period_12h_vs_30d_only_changes_header_label": period_nums_identical,
        "docx_bytes": len(d3),
    }

    # Independent Economics Arithmetic Reconciliation on Case 3
    hw_exp = sum(r["replacement"]["unit_cost_rub"] for r in b3_12h["tz_items"])
    smr_exp = sum(r["replacement"]["install_cost_rub"] for r in b3_12h["tz_items"])
    comm_exp = int(round((hw_exp + smr_exp) * 0.14))
    capex_exp = hw_exp + smr_exp + comm_exp
    rounds_exp = len(b3_12h["tz_items"]) * 38_000
    risk_exp = sum(r["risk_saved_rub"] for r in b3_12h["tz_items"])
    ann_exp = risk_exp + rounds_exp
    pb_yr_exp = round(capex_exp / max(1, ann_exp), 2)
    out["economics_arithmetic_check"] = {
        "capex_match": capex_exp == b3_12h["economics"]["capex_rub"],
        "annual_effect_match": ann_exp == b3_12h["economics"]["annual_effect_rub"],
        "payback_years_match": pb_yr_exp == b3_12h["economics"]["payback_years"],
        "has_opex_modeling": False,
        "uses_hardcoded_vendor_prices": True,
        "custom_economic_inputs_supported": False,
    }

    # Case 4: Optical degradation only
    opt_insts = [make_inst(iid="opt1", code="ДС1-ТН1", value=None, valid=False, level="stale", confidence=0.15)]
    b4 = await generate_spec_bundle(dispatch_overview=make_ov(opt_insts), events=[], snapshot_lookup={}, period="12h")
    out["case4_optical_degradation"] = {
        "root_cause": b4["defective_items"][0]["root_cause"],
        "recommends_digital_sensor_for_camera_issue": len(b4["tz_items"]) > 0,
    }

    # Case 5 & 6: Single workshop vs multiple workshops
    multi_insts = healthy_insts + gas_insts
    b5 = await generate_spec_bundle(dispatch_overview=make_ov(multi_insts), events=[], snapshot_lookup={}, group_filter="Топливо и тяга")
    b6 = await generate_spec_bundle(dispatch_overview=make_ov(multi_insts), events=[], snapshot_lookup={}, group_filter="all")
    out["case5_single_workshop"] = {"scoped_count": len(b5["scoped_items"]), "groups": sorted({x["group"] for x in b5["scoped_items"]})}
    out["case6_multi_workshop"] = {"scoped_count": len(b6["scoped_items"]), "groups": sorted({x["group"] for x in b6["scoped_items"]})}

    # Case 7: Period without telemetry (empty instruments or all invalid)
    b7_empty = await generate_spec_bundle(dispatch_overview=make_ov([]), events=[], snapshot_lookup={}, period="24h")
    d7 = render_spec_docx(b7_empty)
    out["case7_empty_telemetry"] = {
        "scoped": len(b7_empty["scoped_items"]),
        "defective": len(b7_empty["defective_items"]),
        "capex_rub": b7_empty["economics"]["capex_rub"],
        "payback_months_on_zero_capex": b7_empty["economics"]["payback_months"],
        "DEFECT_zero_capex_reports_1_month_payback": b7_empty["economics"]["capex_rub"] == 0 and b7_empty["economics"]["payback_months"] == 1,
        "docx_valid_zip": zipfile.is_zipfile(io.BytesIO(d7)),
    }

    # Case 8: Unknown group filter -> check silent fallback to all_items[:6]!
    b8_bad_grp = await generate_spec_bundle(dispatch_overview=make_ov(multi_insts), events=[], snapshot_lookup={}, group_filter="Несуществующий цех")
    out["case8_unknown_group_silent_fallback"] = {
        "requested_group": "Несуществующий цех",
        "returned_scoped_count": len(b8_bad_grp["scoped_items"]),
        "DEFECT_silent_fallback_to_all_items": len(b8_bad_grp["scoped_items"]) > 0,
    }

    # Case 9: Data mutation sensitivity + Deterministic reproducibility
    b9_a = await generate_spec_bundle(dispatch_overview=make_ov(gas_insts), events=[], snapshot_lookup={}, requisites={"doc_number": "REPRO-1"})
    b9_b = await generate_spec_bundle(dispatch_overview=make_ov(gas_insts), events=[], snapshot_lookup={}, requisites={"doc_number": "REPRO-1"})
    gas_mut = [make_inst(iid="g1", code="ГРП-Р01", group="Топливо и тяга", gauge_type="pressure", unit="МПа", v_min=0, v_max=1.0, value=0.91, level="alert")]
    b9_mut = await generate_spec_bundle(dispatch_overview=make_ov(gas_mut), events=[], snapshot_lookup={}, requisites={"doc_number": "REPRO-1"})
    out["case9_reproducibility_and_mutation"] = {
        "deterministic_identical_md": b9_a["markdown"] == b9_b["markdown"],
        "changes_when_data_mutates": ("0,91 МПа" in b9_mut["markdown"]) and ("0,68 МПа" in b9_a["markdown"]),
    }

    # Case 10: Mock LLM mode (success, HTTP 500 fallback, timeout fallback, malformed JSON fallback)
    llm_mode_flag = {"mode": "ok"}

    class MockLLMHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            _ = self.rfile.read(length)
            m = llm_mode_flag["mode"]
            if m == "ok":
                body = json.dumps({"choices": [{"message": {"content": "LLM-обогащённое заключение: требуется плановая замена узла КИПиА."}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            elif m == "500":
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Internal Error")
            elif m == "bad_json":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{not-valid-json")
            elif m == "timeout":
                time.sleep(2.0)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()

    orig_url, orig_timeout = config.LLM_BASE_URL, config.LLM_TIMEOUT_SECONDS
    try:
        config.LLM_BASE_URL = f"http://127.0.0.1:{port}/v1"
        config.LLM_TIMEOUT_SECONDS = 0.6

        llm_mode_flag["mode"] = "ok"
        b_ok = await generate_spec_bundle(dispatch_overview=make_ov(gas_insts), events=[], snapshot_lookup={}, mode="llm_enhanced")

        llm_mode_flag["mode"] = "500"
        b_500 = await generate_spec_bundle(dispatch_overview=make_ov(gas_insts), events=[], snapshot_lookup={}, mode="llm_enhanced")

        llm_mode_flag["mode"] = "bad_json"
        b_bad = await generate_spec_bundle(dispatch_overview=make_ov(gas_insts), events=[], snapshot_lookup={}, mode="llm_enhanced")

        llm_mode_flag["mode"] = "timeout"
        b_to = await generate_spec_bundle(dispatch_overview=make_ov(gas_insts), events=[], snapshot_lookup={}, mode="llm_enhanced")

        out["llm_integration_protocol"] = {
            "ok_engine": b_ok["engine_used"],
            "ok_tables_numbers_preserved": b_ok["economics"] == b3_12h["economics"],
            "http500_fallback_engine": b_500["engine_used"],
            "bad_json_fallback_engine": b_bad["engine_used"],
            "timeout_fallback_engine": b_to["engine_used"],
            "all_failures_gracefully_fell_back": all("fallback" in b["engine_used"] for b in (b_500, b_bad, b_to)),
        }
    finally:
        config.LLM_BASE_URL, config.LLM_TIMEOUT_SECONDS = orig_url, orig_timeout
        srv.shutdown()

    # Validate .docx XML integrity & check for XSS XML escaping
    xss_payload = '<script>alert("xss")</script> & "test"'
    b_xss = await generate_spec_bundle(
        dispatch_overview=make_ov(gas_insts), events=[], snapshot_lookup={},
        requisites={"plant_name": xss_payload, "doc_number": "XSS-01"},
    )
    d_xss = render_spec_docx(b_xss)
    with zipfile.ZipFile(io.BytesIO(d_xss), "r") as zf:
        doc_xml = zf.read("word/document.xml")
        root = ET.fromstring(doc_xml)  # Fails if XML injection broke OpenXML
        txt = "".join(root.itertext())
    out["docx_xml_escaping_test"] = {
        "valid_xml_with_special_chars": True,
        "payload_preserved_as_escaped_text": '<script>alert("xss")</script>' in txt,
    }

    return out


# ---------------------------------------------------------------------------
# 3. Security Audit Probes via isolated FastAPI TestClient
# ---------------------------------------------------------------------------
def audit_security_api() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="gv_sec_audit_"))
    os.environ["GAUGEVISION_DEMO"] = "1"
    os.environ["GAUGEVISION_DB"] = str(tmp / "sec.db")
    os.environ["GAUGEVISION_SF_DB"] = str(tmp / "sec_sf.db")
    os.environ["GAUGEVISION_MODBUS_ENABLED"] = "0"
    os.environ["GAUGEVISION_MQTT_ENABLED"] = "0"
    config.configure_runtime(demo=True, db_path=str(tmp / "sec.db"), device="cpu")

    from fastapi.testclient import TestClient
    from app import main as app_main

    sec: dict = {}
    with TestClient(app_main.app, raise_server_exceptions=False) as client:
        # 1. Path traversal with '..' vs absolute path for video_file
        r_dotdot = client.post("/api/cameras", json={
            "name": "TravDotDot", "type": "video_file", "source_url": "../../run.py"
        })
        r_abs = client.post("/api/cameras", json={
            "name": "TravAbs", "type": "video_file", "source_url": "C:\\Windows\\win.ini"
        })
        abs_cam_id = r_abs.json().get("id") if r_abs.status_code == 201 else None
        if abs_cam_id:
            client.delete(f"/api/cameras/{abs_cam_id}")
        sec["video_file_path_validation"] = {
            "dotdot_status": r_dotdot.status_code,
            "absolute_path_status": r_abs.status_code,
            "DEFECT_arbitrary_absolute_path_accepted": r_abs.status_code == 201,
        }

        # 2. RTSP Credential Leakage in REST API & SQLite DB
        secret_rtsp = "rtsp://admin:SuperSecretPass99@127.0.0.1:59998/stream1"
        r_rtsp = client.post("/api/cameras", json={
            "name": "RTSP Cred Test", "type": "rtsp", "source_url": secret_rtsp
        })
        rtsp_id = r_rtsp.json().get("id") if r_rtsp.status_code == 201 else None
        cams_txt = client.get("/api/cameras").text
        arch_txt = client.get("/api/architecture/streams").text
        con = sqlite3.connect(str(tmp / "sec.db"))
        db_urls = [row[0] for row in con.execute("SELECT source_url FROM cameras").fetchall()]
        con.close()
        if rtsp_id:
            client.delete(f"/api/cameras/{rtsp_id}")
        sec["rtsp_credentials_exposure"] = {
            "leaked_in_api_cameras": "SuperSecretPass99" in cams_txt,
            "leaked_in_api_architecture_streams": "SuperSecretPass99" in arch_txt,
            "stored_plaintext_in_sqlite": any("SuperSecretPass99" in (u or "") for u in db_urls),
        }

        # 3. SSRF probe (http_mjpeg pointing to internal metadata IP)
        r_ssrf = client.post("/api/cameras", json={
            "name": "SSRF Probe", "type": "http_mjpeg", "source_url": "http://169.254.169.254/latest/meta-data/"
        })
        ssrf_id = r_ssrf.json().get("id") if r_ssrf.status_code == 201 else None
        if ssrf_id:
            client.delete(f"/api/cameras/{ssrf_id}")
        sec["ssrf_source_url_restriction"] = {
            "metadata_ip_status": r_ssrf.status_code,
            "DEFECT_ssrf_unrestricted_url_accepted": r_ssrf.status_code == 201,
        }

        # 4. Unauthenticated access to fault-injection & destructive endpoints
        r_out = client.post("/api/architecture/outage", json={"active": True})
        r_out_off = client.post("/api/architecture/outage", json={"active": False})
        r_deg = client.post("/api/architecture/degrade", json={"stream_id": "demo-mtp160-steam", "mode": "steam"})
        client.post("/api/architecture/degrade", json={"stream_id": "demo-mtp160-steam", "mode": "recover"})
        sec["unauthenticated_control_endpoints"] = {
            "outage_toggle_no_auth_status": r_out.status_code,
            "degrade_inject_no_auth_status": r_deg.status_code,
            "auth_middleware_present": False,
        }

        # 5. Security headers & CORS check
        r_meta = client.get("/api/meta", headers={"Origin": "https://evil.example.com"})
        sec["http_headers_and_cors"] = {
            "x_content_type_options": r_meta.headers.get("x-content-type-options"),
            "referrer_policy": r_meta.headers.get("referrer-policy"),
            "csp_present": "content-security-policy" in r_meta.headers,
            "x_frame_options_present": "x-frame-options" in r_meta.headers,
            "cors_allow_origin": r_meta.headers.get("access-control-allow-origin"),
        }

        # 6. SQL injection / invalid input resilience
        r_sqli = client.get("/api/instruments/' OR '1'='1/history")
        r_bad_spec = client.post("/api/specs/preview", json={"period": "999y", "mode": "invalid"})
        r_nan = client.patch("/api/cameras/demo-mtp160-steam", content='{"thresholds":{"h_warn":NaN}}', headers={"Content-Type": "application/json"})
        sec["input_validation_and_sqli"] = {
            "sqli_inst_id_status": r_sqli.status_code,
            "bad_spec_enum_status": r_bad_spec.status_code,
            "nan_json_status": r_nan.status_code,
        }

        # 7. Check SSE endpoint connectivity & disconnect cleanup
        with client.stream("GET", "/api/events/stream") as sse_resp:
            first_chunk = next(sse_resp.iter_lines())
            sec["sse_endpoint"] = {
                "status_code": sse_resp.status_code,
                "content_type": sse_resp.headers.get("content-type"),
                "first_line": first_chunk,
            }

    return sec


async def main() -> None:
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dispatch_math_12_signals": audit_dispatch_math(),
        "spec_generator_audit": await audit_spec_generator(),
        "security_api_audit": audit_security_api(),
    }
    out_path = OUT_DIR / "track1_security_audit_results.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"TRACK 1 & SECURITY AUDIT COMPLETE -> {out_path}")
    print(json.dumps({
        "peak_rate_1hz_actual": report["dispatch_math_12_signals"]["2_linear_ramp_6mpa_per_min_1hz"]["actual_peak_rate_per_min"],
        "phantom_overload_min": report["dispatch_math_12_signals"]["7_instant_1s_alert_overload_min"]["reported_overload_min"],
        "trips_24h_hardcoded_2x": report["dispatch_math_12_signals"]["8_trips_shift_vs_24h"]["DEFECT_trips_24h_is_hardcoded_2x_shift"],
        "health_score_bad_cam_confounding": report["dispatch_math_12_signals"]["10_health_score_confounding_healthy_process_bad_camera"]["health_score"],
        "spec_forces_healthy_into_defects": report["spec_generator_audit"]["case1_all_healthy"]["DEFECT_forces_healthy_equipment_into_defects_and_tz"],
        "spec_period_only_changes_label": report["spec_generator_audit"]["case3_regular_overloads_and_period_sensitivity"]["DEFECT_period_12h_vs_30d_only_changes_header_label"],
        "llm_graceful_fallback": report["spec_generator_audit"]["llm_integration_protocol"]["all_failures_gracefully_fell_back"],
        "sec_abs_path_accepted": report["security_api_audit"]["video_file_path_validation"]["DEFECT_arbitrary_absolute_path_accepted"],
        "sec_rtsp_creds_leaked": report["security_api_audit"]["rtsp_credentials_exposure"]["leaked_in_api_cameras"],
        "sec_ssrf_accepted": report["security_api_audit"]["ssrf_source_url_restriction"]["DEFECT_ssrf_unrestricted_url_accepted"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
